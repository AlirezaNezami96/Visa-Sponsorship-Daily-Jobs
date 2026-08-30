"""OAuth flow orchestrator for VisaLane authentication.

Coordinates:
  1. Flow initiation: CSRF state creation + authorization URL generation
  2. Rate limiting for protection against rapid attempts
  3. Callback handling: state verification, code exchange, profile extraction
  4. Account linking and profile update payload construction
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional

from .errors import (
    AccountAlreadyLinkedError,
    EmailAlreadyExistsError,
    OAuthCancelledError,
    OAuthError,
    OAuthProviderError,
    OAuthStateMismatchError,
    OAuthTimeoutError,
)
from .oauth_providers import OAuthUserProfile, get_oauth_provider
from .utils import (
    check_oauth_rate_limit,
    generate_oauth_state,
    verify_oauth_state,
)

logger = logging.getLogger(__name__)


class OAuthHandler:
    """Orchestrates OAuth authentication flows for Google and GitHub."""

    def __init__(self, db_client: Optional[Any] = None):
        self.db_client = db_client

    def initiate_flow(
        self,
        provider_name: str,
        redirect_uri: str,
        client_key: str = "",
        client_state: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Initiate OAuth flow: checks rate limit, creates state token, generates auth URL.

        Returns:
            {"authorization_url": str, "state": str, "provider": str}
        """
        # 1. Rate limiting
        if client_key and not check_oauth_rate_limit(client_key):
            raise OAuthError(
                message="Too many OAuth sign-in attempts. Please wait a minute and try again.",
                user_message="Too many attempts. Please wait a moment before trying again.",
                user_action="Wait 60 seconds before retrying.",
                provider=provider_name,
            )

        provider = get_oauth_provider(provider_name)
        state_token = generate_oauth_state(
            provider=provider.name,
            redirect_uri=redirect_uri,
            client_state=client_state,
            extra_data=extra_data,
        )

        auth_url = provider.get_authorization_url(state=state_token, redirect_uri=redirect_uri)
        return {
            "authorization_url": auth_url,
            "state": state_token,
            "provider": provider.name,
        }

    def handle_callback(
        self,
        provider_name: str,
        code: Optional[str],
        state: Optional[str],
        redirect_uri: str,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
        current_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle the callback return from the OAuth provider.

        Args:
            provider_name: 'google' | 'github'
            code: Authorization code from provider
            state: State parameter returned by provider
            redirect_uri: Redirect URI registered with provider
            error: Error query param if user cancelled
            error_description: Provider error description
            current_user_id: If already authenticated and linking an account

        Returns:
            Dictionary with user profile, profile updates, and linking outcome.
        """
        # 1. Check for cancellation / provider error
        if error:
            if error in ("access_denied", "user_cancelled_authorize", "consent_required"):
                raise OAuthCancelledError(
                    f"User cancelled or denied authorization: {error_description or error}",
                    provider=provider_name,
                )
            raise OAuthProviderError(
                f"OAuth provider error: {error_description or error}",
                provider=provider_name,
                technical_details={"error": error, "description": error_description},
            )

        if not code:
            raise OAuthError("No authorization code provided in callback", provider=provider_name)

        if not state:
            raise OAuthStateMismatchError("No state parameter received in callback", provider=provider_name)

        # 2. Verify CSRF State
        is_valid, state_payload, reason = verify_oauth_state(state, expected_provider=provider_name)
        if not is_valid or not state_payload:
            raise OAuthStateMismatchError(
                f"CSRF validation failed: {reason}",
                provider=provider_name,
                technical_details={"reason": reason},
            )

        # 3. Exchange Code for Tokens
        provider = get_oauth_provider(provider_name)
        token_data = provider.exchange_code(code=code, redirect_uri=redirect_uri)

        # 4. Fetch User Profile
        user_profile = provider.get_user_profile(token_data)

        # 5. Process Profile & Linking
        profile_update = self._build_profile_payload(user_profile)

        # If a DB client is provided, execute verification and account linking
        account_action = "login_or_register"
        if self.db_client:
            account_action = self._sync_database_profile(user_profile, current_user_id)

        return {
            "success": True,
            "provider": user_profile.provider,
            "provider_id": user_profile.provider_id,
            "email": user_profile.email,
            "full_name": user_profile.full_name,
            "avatar_url": user_profile.avatar_url,
            "profile_update": profile_update,
            "account_action": account_action,
            "client_state": state_payload.get("client_state", ""),
        }

    def _build_profile_payload(self, profile: OAuthUserProfile) -> Dict[str, Any]:
        """Construct the profile update payload for Supabase profiles table."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "oauth_provider": profile.provider,
            "oauth_provider_id": profile.provider_id,
            "oauth_profile_image": profile.avatar_url,
            "oauth_metadata": {
                "provider": profile.provider,
                "provider_id": profile.provider_id,
                "email_verified": profile.email_verified,
                "synced_at": now_iso,
            },
            "last_login_at": now_iso,
        }

    def _sync_database_profile(
        self,
        profile: OAuthUserProfile,
        current_user_id: Optional[str] = None,
    ) -> str:
        """Sync profile with database, enforcing account linking rules."""
        try:
            # Check if an account already exists with this provider + provider_id
            existing_oauth = (
                self.db_client.table("profiles")
                .select("id, email, oauth_provider, oauth_provider_id")
                .eq("oauth_provider", profile.provider)
                .eq("oauth_provider_id", profile.provider_id)
                .maybe_single()
                .execute()
            )
            existing_oauth_row = existing_oauth.data if existing_oauth else None

            # If currently logged in user is linking this account:
            if current_user_id:
                if existing_oauth_row and existing_oauth_row["id"] != current_user_id:
                    raise AccountAlreadyLinkedError(
                        "This social account is already linked to a different VisaLane account",
                        provider=profile.provider,
                    )
                # Link to current user
                self.db_client.table("profiles").update(
                    self._build_profile_payload(profile)
                ).eq("id", current_user_id).execute()
                return "linked"

            # Check if account with same email already exists
            existing_email = (
                self.db_client.table("profiles")
                .select("id, email, oauth_provider, oauth_provider_id, login_count")
                .eq("email", profile.email)
                .maybe_single()
                .execute()
            )
            existing_email_row = existing_email.data if existing_email else None

            if existing_email_row:
                user_id = existing_email_row["id"]
                current_provider = existing_email_row.get("oauth_provider")
                if current_provider and current_provider != profile.provider:
                    # Email matches an existing account linked to a different provider
                    logger.info("Linking new OAuth provider %s to existing email user %s", profile.provider, user_id)

                # Update existing profile
                payload = self._build_profile_payload(profile)
                payload["login_count"] = (existing_email_row.get("login_count") or 0) + 1
                self.db_client.table("profiles").update(payload).eq("id", user_id).execute()
                return "existing_login"

            return "new_user"
        except (AccountAlreadyLinkedError, EmailAlreadyExistsError):
            raise
        except Exception as exc:
            logger.warning("Database profile sync warning: %s", exc)
            return "sync_deferred"

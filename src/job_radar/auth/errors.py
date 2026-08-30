"""OAuth-specific error classes for VisaLane authentication.

Each error carries:
  - Stable machine-readable error code
  - User-friendly message (safe for UI)
  - Technical debugging details
  - Suggested user action
"""
from __future__ import annotations

from typing import Any, Optional
from job_radar.errors.base import VisaLaneError


class OAuthError(VisaLaneError):
    """Base class for all OAuth-related failures."""

    code: str = "oauth_error"
    http_status: int = 400
    default_user_message: str = "Sign in with provider failed. Please try again."

    def __init__(
        self,
        message: str,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        provider: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        meta = metadata or {}
        if provider:
            meta["provider"] = provider
        if user_action:
            meta["user_action"] = user_action
        if technical_details:
            meta["technical_details"] = technical_details
        super().__init__(message, user_message, meta)
        self.provider = provider
        self.user_action = user_action or "Please try signing in again."
        self.technical_details = technical_details or {}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["error"]["user_action"] = self.user_action
        data["error"]["technical_details"] = self.technical_details
        return data


class OAuthProviderError(OAuthError):
    """Communication failure with OAuth provider (provider down or unreachable)."""

    code = "oauth_provider_error"
    http_status = 502
    default_user_message = "Unable to connect to the authentication provider. Please try again in a few moments."

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Check provider status or try again shortly.",
            provider=provider,
            technical_details=technical_details,
        )


class OAuthTokenError(OAuthError):
    """Failed to exchange authorization code for access token."""

    code = "oauth_token_exchange_failed"
    http_status = 400
    default_user_message = "The authorization code was invalid or expired. Please sign in again."

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Restart the sign-in flow from the login page.",
            provider=provider,
            technical_details=technical_details,
        )


class OAuthProfileError(OAuthError):
    """Failed to fetch user profile from provider."""

    code = "oauth_profile_fetch_failed"
    http_status = 502
    default_user_message = "Could not retrieve your profile information from the provider."

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Ensure you granted permission to access your profile and email.",
            provider=provider,
            technical_details=technical_details,
        )


class OAuthStateMismatchError(OAuthError):
    """CSRF state parameter missing or mismatched."""

    code = "oauth_state_mismatch"
    http_status = 403
    default_user_message = "Security check failed (state mismatch). Please restart the sign-in process."

    def __init__(
        self,
        message: str = "OAuth state parameter mismatch or expired",
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Clear your browser cookies and try signing in again.",
            provider=provider,
            technical_details=technical_details,
        )


class AccountAlreadyLinkedError(OAuthError):
    """OAuth account is already linked to a different VisaLane user."""

    code = "oauth_account_already_linked"
    http_status = 409
    default_user_message = "This social account is already linked to another VisaLane user."

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Sign in using the original account or link a different social account.",
            provider=provider,
            technical_details=technical_details,
        )


class EmailAlreadyExistsError(OAuthError):
    """Email address conflict during OAuth registration or linking."""

    code = "email_already_exists"
    http_status = 409
    default_user_message = "An account with this email address already exists. Would you like to link them?"

    def __init__(
        self,
        message: str,
        email: str,
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        details = technical_details or {}
        details["email"] = email
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Log in with your existing credentials to link this social account.",
            provider=provider,
            technical_details=details,
        )
        self.email = email


class OAuthCancelledError(OAuthError):
    """User cancelled or denied permissions in the OAuth flow."""

    code = "oauth_cancelled"
    http_status = 400
    default_user_message = "Sign in was cancelled or permissions were denied."

    def __init__(
        self,
        message: str = "User cancelled OAuth authorization",
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Grant the requested permissions to sign in with this provider.",
            provider=provider,
            technical_details=technical_details,
        )


class OAuthTimeoutError(OAuthError):
    """OAuth communication or flow timed out."""

    code = "oauth_timeout"
    http_status = 504
    default_user_message = "The sign-in attempt timed out. Please try again."

    def __init__(
        self,
        message: str = "OAuth request timed out",
        provider: Optional[str] = None,
        user_message: Optional[str] = None,
        user_action: Optional[str] = None,
        technical_details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            user_message=user_message or self.default_user_message,
            user_action=user_action or "Check your internet connection and try again.",
            provider=provider,
            technical_details=technical_details,
        )

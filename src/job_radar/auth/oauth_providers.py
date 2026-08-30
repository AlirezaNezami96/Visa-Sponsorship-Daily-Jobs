"""OAuth provider implementations for Google and GitHub.

Handles:
  - Authorization URL generation with proper scopes
  - Code exchange for tokens with timeout & retry handling
  - User profile and email fetching with normalization
  - Profile avatar image extraction
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from .errors import (
    OAuthProfileError,
    OAuthProviderError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from .utils import sanitize_avatar_url

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass
class OAuthUserProfile:
    """Normalized user profile from an OAuth provider."""

    provider: str
    provider_id: str
    email: str
    email_verified: bool = True
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


class BaseOAuthProvider:
    """Base interface for OAuth providers."""

    name: str = "base"

    def get_authorization_url(self, state: str, redirect_uri: str, **kwargs: Any) -> str:
        raise NotImplementedError

    def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise NotImplementedError

    def get_user_profile(self, token_data: Dict[str, Any]) -> OAuthUserProfile:
        raise NotImplementedError


class GoogleOAuthProvider(BaseOAuthProvider):
    """Google OAuth2 provider."""

    name = "google"
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    SCOPES = ["openid", "email", "profile"]

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    def get_authorization_url(
        self,
        state: str,
        redirect_uri: str,
        prompt: str = "select_account",
        **kwargs: Any,
    ) -> str:
        """Generate Google OAuth authorization URL."""
        if not self.client_id:
            raise OAuthProviderError("Google Client ID is not configured", provider=self.name)

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": prompt,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens."""
        if not self.client_id or not self.client_secret:
            raise OAuthProviderError("Google OAuth credentials missing", provider=self.name)

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        try:
            resp = requests.post(
                self.TOKEN_URL,
                data=payload,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise OAuthTimeoutError("Google token exchange timed out", provider=self.name) from exc
        except requests.RequestException as exc:
            raise OAuthProviderError(f"Network error communicating with Google: {exc}", provider=self.name) from exc

        if resp.status_code != 200:
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise OAuthTokenError(
                f"Google token exchange failed ({resp.status_code}): {err_data.get('error_description', resp.text)}",
                provider=self.name,
                technical_details=err_data,
            )

        return resp.json()

    def get_user_profile(self, token_data: Dict[str, Any]) -> OAuthUserProfile:
        """Fetch user profile and email from Google UserInfo endpoint."""
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthTokenError("No access token provided for profile fetch", provider=self.name)

        try:
            resp = requests.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise OAuthTimeoutError("Google userinfo request timed out", provider=self.name) from exc
        except requests.RequestException as exc:
            raise OAuthProviderError(f"Failed to fetch Google profile: {exc}", provider=self.name) from exc

        if resp.status_code != 200:
            raise OAuthProfileError(
                f"Google userinfo returned status {resp.status_code}: {resp.text}",
                provider=self.name,
                technical_details={"status": resp.status_code, "response": resp.text},
            )

        data = resp.json()
        provider_id = data.get("id") or data.get("sub")
        email = data.get("email")
        if not provider_id or not email:
            raise OAuthProfileError("Google profile missing id or email", provider=self.name, technical_details=data)

        full_name = data.get("name") or (f"{data.get('given_name', '')} {data.get('family_name', '')}".strip() or None)
        avatar_url = sanitize_avatar_url(data.get("picture"))

        return OAuthUserProfile(
            provider=self.name,
            provider_id=str(provider_id),
            email=str(email).lower().strip(),
            email_verified=bool(data.get("verified_email", True)),
            full_name=full_name,
            avatar_url=avatar_url,
            raw_metadata=data,
        )


class GitHubOAuthProvider(BaseOAuthProvider):
    """GitHub OAuth provider."""

    name = "github"
    AUTH_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USERINFO_URL = "https://api.github.com/user"
    EMAILS_URL = "https://api.github.com/user/emails"
    SCOPES = ["read:user", "user:email"]

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("GITHUB_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.getenv("GITHUB_CLIENT_SECRET", "").strip()

    def get_authorization_url(
        self,
        state: str,
        redirect_uri: str,
        **kwargs: Any,
    ) -> str:
        """Generate GitHub OAuth authorization URL."""
        if not self.client_id:
            raise OAuthProviderError("GitHub Client ID is not configured", provider=self.name)

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.SCOPES),
            "state": state,
            "allow_signup": "true",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for GitHub access token."""
        if not self.client_id or not self.client_secret:
            raise OAuthProviderError("GitHub OAuth credentials missing", provider=self.name)

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        try:
            resp = requests.post(
                self.TOKEN_URL,
                data=payload,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise OAuthTimeoutError("GitHub token exchange timed out", provider=self.name) from exc
        except requests.RequestException as exc:
            raise OAuthProviderError(f"Network error communicating with GitHub: {exc}", provider=self.name) from exc

        if resp.status_code != 200:
            raise OAuthTokenError(
                f"GitHub token exchange failed ({resp.status_code}): {resp.text}",
                provider=self.name,
            )

        data = resp.json()
        if "error" in data:
            raise OAuthTokenError(
                f"GitHub token error: {data.get('error_description') or data['error']}",
                provider=self.name,
                technical_details=data,
            )

        return data

    def get_user_profile(self, token_data: Dict[str, Any]) -> OAuthUserProfile:
        """Fetch user profile and verified primary email from GitHub APIs."""
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthTokenError("No access token provided for profile fetch", provider=self.name)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "VisaLane-OAuth",
        }

        try:
            user_resp = requests.get(self.USERINFO_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.Timeout as exc:
            raise OAuthTimeoutError("GitHub user info request timed out", provider=self.name) from exc
        except requests.RequestException as exc:
            raise OAuthProviderError(f"Failed to fetch GitHub profile: {exc}", provider=self.name) from exc

        if user_resp.status_code != 200:
            raise OAuthProfileError(
                f"GitHub user API returned status {user_resp.status_code}",
                provider=self.name,
                technical_details={"status": user_resp.status_code, "response": user_resp.text},
            )

        user_data = user_resp.json()
        provider_id = str(user_data.get("id"))
        email = user_data.get("email")

        # If email is not public on profile, fetch from /user/emails
        email_verified = True
        if not email:
            try:
                emails_resp = requests.get(self.EMAILS_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
                if emails_resp.status_code == 200:
                    emails_data: List[Dict[str, Any]] = emails_resp.json()
                    # Find primary & verified email
                    for em in emails_data:
                        if em.get("primary") and em.get("verified"):
                            email = em.get("email")
                            email_verified = True
                            break
                    if not email and emails_data:
                        # Fallback to first verified or first available email
                        verified_emails = [e["email"] for e in emails_data if e.get("verified")]
                        if verified_emails:
                            email = verified_emails[0]
                        else:
                            email = emails_data[0].get("email")
                            email_verified = False
            except Exception as exc:
                logger.debug("Failed to fetch GitHub emails: %s", exc)

        if not provider_id or not email:
            raise OAuthProfileError(
                "GitHub profile missing id or email",
                provider=self.name,
                technical_details=user_data,
            )

        full_name = user_data.get("name") or user_data.get("login")
        avatar_url = sanitize_avatar_url(user_data.get("avatar_url"))

        return OAuthUserProfile(
            provider=self.name,
            provider_id=provider_id,
            email=str(email).lower().strip(),
            email_verified=email_verified,
            full_name=full_name,
            avatar_url=avatar_url,
            raw_metadata=user_data,
        )


def get_oauth_provider(provider_name: str) -> BaseOAuthProvider:
    """Factory helper to get the configured provider by name."""
    norm = (provider_name or "").lower().strip()
    if norm == "google":
        return GoogleOAuthProvider()
    if norm == "github":
        return GitHubOAuthProvider()
    raise OAuthProviderError(f"Unsupported OAuth provider: '{provider_name}'", provider=provider_name)

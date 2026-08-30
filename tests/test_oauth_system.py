"""Comprehensive unit and integration tests for VisaLane OAuth authentication system."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from job_radar.auth.errors import (
    AccountAlreadyLinkedError,
    EmailAlreadyExistsError,
    OAuthCancelledError,
    OAuthError,
    OAuthProfileError,
    OAuthProviderError,
    OAuthStateMismatchError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from job_radar.auth.oauth_handler import OAuthHandler
from job_radar.auth.oauth_providers import (
    GitHubOAuthProvider,
    GoogleOAuthProvider,
    OAuthUserProfile,
    get_oauth_provider,
)
from job_radar.auth.utils import (
    check_oauth_rate_limit,
    generate_oauth_state,
    sanitize_avatar_url,
    verify_oauth_state,
)


def test_sanitize_avatar_url():
    assert sanitize_avatar_url("https://example.com/avatar.png") == "https://example.com/avatar.png"
    assert sanitize_avatar_url("http://example.com/pic.jpg") == "http://example.com/pic.jpg"
    assert sanitize_avatar_url("ftp://example.com/avatar.png") is None
    assert sanitize_avatar_url("javascript:alert(1)") is None
    assert sanitize_avatar_url("") is None
    assert sanitize_avatar_url(None) is None
    assert sanitize_avatar_url("   ") is None


def test_oauth_state_generation_and_verification():
    state = generate_oauth_state(provider="google", redirect_uri="https://visalane.online/callback", client_state="custom123")
    assert state and "." in state

    # Successful verification
    ok, payload, err = verify_oauth_state(state, expected_provider="google")
    assert ok is True
    assert payload is not None
    assert payload["provider"] == "google"
    assert payload["redirect_uri"] == "https://visalane.online/callback"
    assert payload["client_state"] == "custom123"
    assert err is None

    # Mismatched provider
    ok2, _, err2 = verify_oauth_state(state, expected_provider="github")
    assert ok2 is False
    assert "Provider mismatch" in err2

    # Tampered state
    tampered = state[:-4] + "abcd"
    ok3, _, err3 = verify_oauth_state(tampered, expected_provider="google")
    assert ok3 is False
    assert "State signature mismatch" in err3

    # Expired state
    with patch("time.time", return_value=time.time() + 1000):
        ok4, _, err4 = verify_oauth_state(state, expected_provider="google", max_age_seconds=600)
        assert ok4 is False
        assert "expired" in err4

    # Invalid state formats
    assert verify_oauth_state("")[0] is False
    assert verify_oauth_state("nosignature")[0] is False


def test_oauth_rate_limiting():
    key = "user_ip_test_rate_limit"
    now = 1000.0

    # 10 attempts allowed in 60s window
    for i in range(10):
        assert check_oauth_rate_limit(key, now=now + i) is True

    # 11th attempt is blocked
    assert check_oauth_rate_limit(key, now=now + 10) is False

    # After window passes, allowed again
    assert check_oauth_rate_limit(key, now=now + 70) is True


def test_google_provider_urls_and_profile_extraction():
    provider = GoogleOAuthProvider(client_id="test_google_client_id", client_secret="test_secret")
    assert provider.name == "google"

    auth_url = provider.get_authorization_url(state="test_state", redirect_uri="https://visalane.online/cb")
    assert "accounts.google.com" in auth_url
    assert "client_id=test_google_client_id" in auth_url
    assert "state=test_state" in auth_url
    assert "openid" in auth_url

    # Mock code exchange
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "google_tok_123", "expires_in": 3600}

    with patch("requests.post", return_value=mock_resp):
        token_data = provider.exchange_code("code_abc", "https://visalane.online/cb")
        assert token_data["access_token"] == "google_tok_123"

    # Mock profile fetch
    profile_resp = MagicMock()
    profile_resp.status_code = 200
    profile_resp.json.return_value = {
        "sub": "google_sub_999",
        "email": "Alex@Example.com",
        "name": "Alex Smith",
        "picture": "https://lh3.googleusercontent.com/avatar.jpg",
        "verified_email": True,
    }

    with patch("requests.get", return_value=profile_resp):
        profile = provider.get_user_profile(token_data)
        assert profile.provider == "google"
        assert profile.provider_id == "google_sub_999"
        assert profile.email == "alex@example.com"
        assert profile.full_name == "Alex Smith"
        assert profile.avatar_url == "https://lh3.googleusercontent.com/avatar.jpg"
        assert profile.email_verified is True


def test_github_provider_urls_and_profile_extraction():
    provider = GitHubOAuthProvider(client_id="test_github_client_id", client_secret="test_gh_secret")
    assert provider.name == "github"

    auth_url = provider.get_authorization_url(state="gh_state", redirect_uri="https://visalane.online/cb")
    assert "github.com/login/oauth/authorize" in auth_url
    assert "client_id=test_github_client_id" in auth_url
    assert "state=gh_state" in auth_url

    # Mock profile fetch with fallback to /user/emails
    user_resp = MagicMock()
    user_resp.status_code = 200
    user_resp.json.return_value = {
        "id": 123456,
        "login": "octocat",
        "name": "Mona Lisa Octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/123456",
        "email": None,
    }

    emails_resp = MagicMock()
    emails_resp.status_code = 200
    emails_resp.json.return_value = [
        {"email": "secondary@example.com", "primary": False, "verified": True},
        {"email": "mona@github.com", "primary": True, "verified": True},
    ]

    def mock_get(url: str, **kwargs: Any):
        if "user/emails" in url:
            return emails_resp
        return user_resp

    with patch("requests.get", side_effect=mock_get):
        profile = provider.get_user_profile({"access_token": "gh_access_token"})
        assert profile.provider == "github"
        assert profile.provider_id == "123456"
        assert profile.email == "mona@github.com"
        assert profile.full_name == "Mona Lisa Octocat"
        assert profile.avatar_url == "https://avatars.githubusercontent.com/u/123456"
        assert profile.email_verified is True


def test_provider_factory_and_unsupported_error():
    assert isinstance(get_oauth_provider("google"), GoogleOAuthProvider)
    assert isinstance(get_oauth_provider("github"), GitHubOAuthProvider)
    with pytest.raises(OAuthProviderError) as exc_info:
        get_oauth_provider("facebook")
    assert "Unsupported OAuth provider" in str(exc_info.value)


def test_oauth_handler_initiation_and_rate_limit():
    handler = OAuthHandler()

    with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "mock_id", "GOOGLE_CLIENT_SECRET": "mock_secret"}):
        result = handler.initiate_flow(
            provider_name="google",
            redirect_uri="https://visalane.online/auth/callback",
            client_key="client_ip_1",
            client_state="view_dashboard",
        )
        assert result["provider"] == "google"
        assert "authorization_url" in result
        assert "state" in result


def test_oauth_handler_callback_cancellation_and_mismatch():
    handler = OAuthHandler()

    # User cancelled
    with pytest.raises(OAuthCancelledError):
        handler.handle_callback(
            provider_name="google",
            code=None,
            state=None,
            redirect_uri="https://visalane.online/cb",
            error="access_denied",
            error_description="User denied authorization",
        )

    # State mismatch
    with pytest.raises(OAuthStateMismatchError):
        handler.handle_callback(
            provider_name="google",
            code="code123",
            state="invalid_state_signature.abcd",
            redirect_uri="https://visalane.online/cb",
        )


def test_oauth_handler_callback_success_and_account_linking():
    mock_db = MagicMock()
    handler = OAuthHandler(db_client=mock_db)

    # Generate a valid state
    state = generate_oauth_state("google", "https://visalane.online/cb")

    mock_profile = OAuthUserProfile(
        provider="google",
        provider_id="sub_12345",
        email="testuser@example.com",
        full_name="Test User",
        avatar_url="https://example.com/avatar.png",
    )

    with patch("job_radar.auth.oauth_handler.get_oauth_provider") as mock_get_prov:
        mock_prov = MagicMock()
        mock_prov.name = "google"
        mock_prov.exchange_code.return_value = {"access_token": "tok_123"}
        mock_prov.get_user_profile.return_value = mock_profile
        mock_get_prov.return_value = mock_prov

        # Mock DB response: user already exists with matching email
        mock_select = MagicMock()
        mock_select.data = {"id": "usr_uuid_100", "email": "testuser@example.com", "login_count": 5}
        mock_db.table().select().eq().eq().maybe_single().execute.return_value = None
        mock_db.table().select().eq().maybe_single().execute.return_value = mock_select

        res = handler.handle_callback(
            provider_name="google",
            code="auth_code_xyz",
            state=state,
            redirect_uri="https://visalane.online/cb",
        )

        assert res["success"] is True
        assert res["email"] == "testuser@example.com"
        assert res["avatar_url"] == "https://example.com/avatar.png"
        assert res["profile_update"]["oauth_provider"] == "google"
        assert res["profile_update"]["oauth_provider_id"] == "sub_12345"


def test_oauth_error_serialization():
    err = OAuthProviderError(
        message="Provider connection timed out",
        provider="google",
        technical_details={"timeout_s": 10},
    )
    serialized = err.to_dict()
    assert serialized["error"]["code"] == "oauth_provider_error"
    assert serialized["error"]["user_action"] != ""
    assert serialized["error"]["technical_details"]["timeout_s"] == 10

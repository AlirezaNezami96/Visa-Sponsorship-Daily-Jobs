"""Authentication module for VisaLane."""
from .errors import (
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
from .oauth_handler import OAuthHandler
from .oauth_providers import (
    BaseOAuthProvider,
    GitHubOAuthProvider,
    GoogleOAuthProvider,
    OAuthUserProfile,
    get_oauth_provider,
)
from .utils import (
    check_oauth_rate_limit,
    generate_oauth_state,
    sanitize_avatar_url,
    verify_oauth_state,
)

__all__ = [
    "OAuthError",
    "OAuthProviderError",
    "OAuthTokenError",
    "OAuthProfileError",
    "OAuthStateMismatchError",
    "AccountAlreadyLinkedError",
    "EmailAlreadyExistsError",
    "OAuthCancelledError",
    "OAuthTimeoutError",
    "OAuthUserProfile",
    "BaseOAuthProvider",
    "GoogleOAuthProvider",
    "GitHubOAuthProvider",
    "get_oauth_provider",
    "OAuthHandler",
    "generate_oauth_state",
    "verify_oauth_state",
    "check_oauth_rate_limit",
    "sanitize_avatar_url",
]

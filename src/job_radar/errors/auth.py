"""Authentication and authorization error classes for VisaLane."""
from __future__ import annotations

from .base import AuthenticationError, AuthorizationError, VisaLaneError


class TokenExpiredError(AuthenticationError):
    """JWT token or session has expired."""
    code = "token_expired"
    default_user_message = "Your session has expired. Please sign in again."


class InvalidCredentialsError(AuthenticationError):
    """Invalid username, password, or login credentials."""
    code = "invalid_credentials"
    default_user_message = "Invalid email or password. Please check your credentials and try again."


class RateLimitExceededError(VisaLaneError):
    """Too many authentication or API requests."""
    code = "rate_limit_exceeded"
    http_status = 429
    default_user_message = "Too many requests. Please slow down and try again shortly."

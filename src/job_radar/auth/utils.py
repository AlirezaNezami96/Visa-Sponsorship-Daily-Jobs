"""OAuth utility functions and helpers for VisaLane.

Provides:
  - Cryptographically secure state parameter generation and verification
  - In-memory rate limiting for rapid OAuth attempts
  - Safe avatar URL extraction and validation
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# State expiration in seconds (10 minutes)
STATE_EXPIRATION_SECONDS = 600

# Rate limiting settings: max attempts within window
OAUTH_RATE_LIMIT_WINDOW = 60.0  # 1 minute window
OAUTH_MAX_ATTEMPTS = 10         # max 10 attempts per minute per IP / key

_oauth_attempt_log: Dict[str, list[float]] = {}


def get_oauth_secret() -> str:
    """Get secret key for signing OAuth state parameters."""
    return os.getenv("OAUTH_STATE_SECRET") or os.getenv("JWT_SECRET") or "visalane_oauth_default_hmac_secret_key"


def generate_oauth_state(
    provider: str,
    redirect_uri: str = "",
    client_state: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a signed, tamper-proof state parameter with timestamp.

    Format: base64(json_payload) + "." + hmac_sha256(json_payload, secret)
    """
    now = time.time()
    payload = {
        "provider": provider,
        "nonce": secrets.token_hex(16),
        "timestamp": now,
        "redirect_uri": redirect_uri,
        "client_state": client_state or "",
        "extra": extra_data or {},
    }
    raw_json = json.dumps(payload, sort_keys=True)
    b64_payload = base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("utf-8")

    secret = get_oauth_secret()
    sig = hmac.new(secret.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_oauth_state(
    state_token: str,
    expected_provider: Optional[str] = None,
    max_age_seconds: float = STATE_EXPIRATION_SECONDS,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Verify state token signature and expiration.

    Returns:
        (is_valid, payload_dict_if_valid, error_reason)
    """
    if not state_token or "." not in state_token:
        return False, None, "Malformed state token"

    parts = state_token.split(".", 1)
    if len(parts) != 2:
        return False, None, "Invalid state token structure"

    b64_payload, provided_sig = parts

    secret = get_oauth_secret()
    expected_sig = hmac.new(secret.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, None, "State signature mismatch (possible CSRF attack)"

    try:
        raw_json = base64.urlsafe_b64decode(b64_payload.encode("utf-8")).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception as exc:
        return False, None, f"Failed to decode state payload: {exc}"

    # Check timestamp expiration
    ts = payload.get("timestamp", 0)
    now = time.time()
    if now - ts > max_age_seconds:
        return False, None, "OAuth state token expired"
    if ts > now + 60:  # clock skew tolerance 1 min
        return False, None, "OAuth state timestamp in the future"

    # Check provider matching
    if expected_provider and payload.get("provider") != expected_provider:
        return False, None, f"Provider mismatch in state: expected {expected_provider}, got {payload.get('provider')}"

    return True, payload, None


def check_oauth_rate_limit(client_key: str, now: Optional[float] = None) -> bool:
    """Check if client_key has exceeded the rapid OAuth attempt rate limit.

    Returns True if allowed, False if rate limited.
    """
    if not client_key:
        return True

    now = time.time() if now is None else now
    cutoff = now - OAUTH_RATE_LIMIT_WINDOW

    attempts = _oauth_attempt_log.get(client_key, [])
    # Filter out old attempts
    fresh = [t for t in attempts if t > cutoff]
    if len(fresh) >= OAUTH_MAX_ATTEMPTS:
        _oauth_attempt_log[client_key] = fresh
        return False

    fresh.append(now)
    _oauth_attempt_log[client_key] = fresh
    return True


def sanitize_avatar_url(url: Optional[str]) -> Optional[str]:
    """Validate and sanitize avatar URL. Returns None if invalid or suspicious."""
    if not url or not isinstance(url, str):
        return None

    cleaned = url.strip()
    if not cleaned:
        return None

    try:
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return cleaned
    except Exception:
        return None

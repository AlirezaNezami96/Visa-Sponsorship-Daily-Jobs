"""Error taxonomy and retryability classification for social publishing.

Maps HTTP response status codes, headers, and exceptions to stable
retryable vs. permanent error classifications.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

PERMANENT_HTTP_CODES = {400, 401, 403, 404, 405, 410, 422}
RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def parse_retry_after(
    headers: dict[str, str] | None = None,
    body_text: str | None = None,
) -> float | None:
    """Extract Retry-After value in seconds from HTTP headers or response body JSON."""
    if headers:
        for k, v in headers.items():
            if k.lower() == "retry-after":
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass

    if body_text:
        try:
            data = json.loads(body_text)
            if isinstance(data, dict):
                if "retry_after" in data:
                    return float(data["retry_after"])
                # Telegram style: parameters.retry_after
                if "parameters" in data and isinstance(data["parameters"], dict):
                    if "retry_after" in data["parameters"]:
                        return float(data["parameters"]["retry_after"])
        except Exception:
            pass

    return None


def classify_http_error(
    status_code: int,
    response_text: str = "",
    headers: dict[str, str] | None = None,
) -> tuple[bool, bool, float | None]:
    """Classify an HTTP response status code.

    Returns:
        (retryable: bool, permanent: bool, retry_after: float | None)
    """
    retry_after = parse_retry_after(headers, response_text)

    if status_code in RETRYABLE_HTTP_CODES:
        return True, False, retry_after

    if status_code in PERMANENT_HTTP_CODES:
        return False, True, retry_after

    if status_code >= 500:
        return True, False, retry_after

    return False, True, retry_after


def classify_exception(exc: Exception) -> tuple[bool, bool, float | None]:
    """Classify a network or runtime exception."""
    import requests

    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True, False, None

    exc_name = exc.__class__.__name__.lower()
    if "timeout" in exc_name or "connection" in exc_name or "network" in exc_name:
        return True, False, None

    return False, True, None

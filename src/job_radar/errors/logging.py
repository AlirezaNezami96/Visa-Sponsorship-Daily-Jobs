"""Structured JSON error logger with PII sanitization."""
from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger("visalane.errors")

# PII and credential patterns to mask in logs
_SENSITIVE_KEY_PATTERNS = re.compile(r"(password|token|secret|key|authorization|bearer|cookie|jwt)", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9_.+-]+)@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def sanitize_value(val: Any) -> Any:
    """Recursively mask sensitive values and PII."""
    if isinstance(val, str):
        # Mask emails (show first char + domain)
        val = _EMAIL_PATTERN.sub(r"\1***@\2", val)
        # Mask phone numbers
        val = _PHONE_PATTERN.sub(r"***-***-****", val)
        return val
    elif isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if _SENSITIVE_KEY_PATTERNS.search(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, list):
        return [sanitize_value(item) for item in val]
    return val


def log_structured_error(
    exc: Exception,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Format and emit a structured JSON error log."""
    from .base import VisaLaneError

    error_code = getattr(exc, "code", "internal_error")
    http_status = getattr(exc, "http_status", 500)
    req_id = getattr(exc, "request_id", request_id or "unknown")

    log_entry: Dict[str, Any] = {
        "event": "error",
        "error_code": error_code,
        "http_status": http_status,
        "message": str(exc),
        "request_id": req_id,
        "user_id": user_id,
        "endpoint": endpoint,
        "exception_type": exc.__class__.__name__,
        "context": sanitize_value(extra_context or {}),
        "traceback": traceback.format_exc(),
    }

    sanitized_entry = sanitize_value(log_entry)
    logger.error(json.dumps(sanitized_entry))

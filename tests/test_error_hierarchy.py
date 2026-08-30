"""Unit tests for unified error hierarchy, PII sanitization, and serialization."""
from __future__ import annotations

from job_radar.errors.auth import InvalidCredentialsError, RateLimitExceededError, TokenExpiredError
from job_radar.errors.base import DatabaseError, ValidationError, VisaLaneError
from job_radar.errors.database import DuplicateKeyError, RecordNotFoundError, StorageUploadError
from job_radar.errors.external import LLMQuotaExhaustedError, ScraperBlockedError
from job_radar.errors.logging import sanitize_value
from job_radar.errors.validation import CorruptedFileError, SchemaValidationError


def test_error_to_dict_structure():
    err = ValidationError("Invalid salary range", field="salary_min", user_message="Salary must be a positive number.")
    d = err.to_dict()

    assert "error" in d
    assert d["error"]["code"] == "validation_error"
    assert d["error"]["message"] == "Invalid salary range"
    assert d["error"]["user_message"] == "Salary must be a positive number."
    assert "request_id" in d["error"]
    assert "timestamp" in d["error"]
    assert d["error"]["metadata"]["field"] == "salary_min"


def test_auth_errors():
    err_token = TokenExpiredError("Expired JWT")
    assert err_token.code == "token_expired"
    assert err_token.http_status == 401

    err_creds = InvalidCredentialsError("Bad password")
    assert err_creds.code == "invalid_credentials"
    assert err_creds.http_status == 401

    err_rate = RateLimitExceededError("Rate limit 60/min exceeded")
    assert err_rate.code == "rate_limit_exceeded"
    assert err_rate.http_status == 429


def test_database_and_external_errors():
    db_err = DuplicateKeyError("Email already registered")
    assert db_err.code == "duplicate_key"
    assert db_err.http_status == 409

    rec_err = RecordNotFoundError("Job 123 not found")
    assert rec_err.code == "record_not_found"
    assert rec_err.http_status == 404

    llm_err = LLMQuotaExhaustedError("Daily token limit reached")
    assert llm_err.code == "llm_quota_exhausted"

    block_err = ScraperBlockedError("Cloudflare challenge encountered")
    assert block_err.code == "scraper_blocked"


def test_pii_sanitization():
    raw_payload = {
        "email": "candidate@example.com",
        "phone": "+1 (555) 123-4567",
        "api_key": "sk-123456789",
        "password": "supersecretpassword",
        "user": {
            "name": "Jane Doe",
            "bearer_token": "token-xyz",
        },
    }

    sanitized = sanitize_value(raw_payload)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["user"]["bearer_token"] == "[REDACTED]"
    assert "supersecretpassword" not in str(sanitized)
    assert "***@" in sanitized["email"]

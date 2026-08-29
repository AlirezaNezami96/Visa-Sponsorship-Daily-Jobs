"""Unified error hierarchy for VisaLane backend.

Design principles:
  - Every error has a stable machine-readable code (snake_case).
  - Every error has a user-friendly message (safe to show in the UI).
  - Technical details (internal messages, tracebacks) are never in user_message.
  - Errors can carry optional context (metadata dict) for logging.
  - All errors serialize to a consistent JSON shape used by the API layer.

Error codes are stable: once published, codes are never renamed.
New error variants should use new codes, not rename existing ones.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class VisaLaneError(Exception):
    """Base class for all VisaLane backend errors.

    Attributes:
        code: Stable machine-readable error code (e.g. 'resume_parse_failed').
        message: Technical message for developers / logs.
        user_message: Human-friendly message safe to display in the UI.
        http_status: HTTP status code for API responses.
        metadata: Optional extra context for logging/tracing.
    """

    code: str = "internal_error"
    http_status: int = 500
    default_user_message: str = "An unexpected error occurred. Please try again."

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message or self.default_user_message
        self.metadata = metadata or {}
        self.request_id = str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the standard API error shape."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "user_message": self.user_message,
                "request_id": self.request_id,
                "timestamp": self.timestamp,
                **({"metadata": self.metadata} if self.metadata else {}),
            }
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── Authentication errors ──────────────────────────────────────────────────────

class AuthenticationError(VisaLaneError):
    """User is not authenticated or JWT is invalid."""
    code = "unauthorized"
    http_status = 401
    default_user_message = "Please sign in and try again."


class AuthorizationError(VisaLaneError):
    """User is authenticated but lacks permission."""
    code = "forbidden"
    http_status = 403
    default_user_message = "You do not have permission to perform this action."


# ── Validation errors ──────────────────────────────────────────────────────────

class ValidationError(VisaLaneError):
    """Request or data validation failed."""
    code = "validation_error"
    http_status = 400
    default_user_message = "The provided data is invalid. Please check your input and try again."

    def __init__(
        self,
        message: str,
        field: str | None = None,
        user_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, user_message, metadata)
        if field:
            self.metadata["field"] = field


class FileSizeError(ValidationError):
    """Uploaded file exceeds size limits."""
    code = "file_too_large"
    default_user_message = "Your file is too large. Please upload a file smaller than 10 MB."


class FileTypeError(ValidationError):
    """Uploaded file type is not supported."""
    code = "unsupported_file_type"
    default_user_message = "This file type is not supported. Please upload a PDF, DOCX, or TXT file."


class ContentError(ValidationError):
    """Extracted content does not appear to be a resume."""
    code = "invalid_resume_content"
    default_user_message = "The uploaded file does not appear to be a resume. Please upload your CV."


# ── Resource errors ────────────────────────────────────────────────────────────

class NotFoundError(VisaLaneError):
    """Requested resource not found."""
    code = "not_found"
    http_status = 404
    default_user_message = "The requested resource was not found."


class JobNotFoundError(NotFoundError):
    """Job not found."""
    code = "job_not_found"
    default_user_message = "This job listing is no longer available."


class ResumeNotFoundError(NotFoundError):
    """Resume not found."""
    code = "resume_not_found"
    default_user_message = "Resume not found. Please upload your resume first."


# ── Quota / billing errors ─────────────────────────────────────────────────────

class UsageLimitError(VisaLaneError):
    """Daily usage limit reached."""
    code = "usage_limit_reached"
    http_status = 402
    default_user_message = "You've reached your daily limit. Upgrade your plan to continue."

    def __init__(
        self,
        message: str,
        field: str | None = None,
        limit: int | None = None,
        plan: str | None = None,
        user_message: str | None = None,
    ) -> None:
        meta: dict[str, Any] = {}
        if field:
            meta["field"] = field
        if limit is not None:
            meta["limit"] = limit
        if plan:
            meta["plan"] = plan
        super().__init__(message, user_message, meta)


# ── AI / generation errors ─────────────────────────────────────────────────────

class GenerationError(VisaLaneError):
    """AI generation failed across all providers."""
    code = "generation_failed"
    http_status = 503
    default_user_message = (
        "AI generation is temporarily unavailable. Please try again in a few minutes."
    )


class HallucinationError(GenerationError):
    """AI output failed hallucination cross-check."""
    code = "hallucination_detected"
    default_user_message = (
        "The AI generated content that didn't match your profile. "
        "We stopped it from saving. Please try again."
    )

    def __init__(
        self,
        message: str,
        violations: list[str] | None = None,
        user_message: str | None = None,
    ) -> None:
        meta: dict[str, Any] = {}
        if violations:
            meta["violations"] = violations
        super().__init__(message, user_message, meta)


# ── Resume parsing errors ──────────────────────────────────────────────────────

class ResumeParseError(VisaLaneError):
    """Resume parsing failed."""
    code = "resume_parse_failed"
    http_status = 422
    default_user_message = (
        "We couldn't parse your resume. Please try a different format or contact support."
    )


class ScannedPdfError(ResumeParseError):
    """PDF appears to be image-only (scanned)."""
    code = "scanned_pdf_detected"
    default_user_message = (
        "Your PDF appears to be a scanned image. "
        "Please upload a text-based PDF or a Word document (.docx) instead."
    )


class EncryptedFileError(ResumeParseError):
    """File is password-protected."""
    code = "encrypted_file"
    default_user_message = (
        "Your file is password-protected. Please remove the password and upload again."
    )


# ── External service errors ────────────────────────────────────────────────────

class ExternalServiceError(VisaLaneError):
    """External service (Apollo, email provider, etc.) failed."""
    code = "external_service_error"
    http_status = 503
    default_user_message = "An external service is temporarily unavailable. Please try again later."

    def __init__(
        self,
        message: str,
        service: str | None = None,
        user_message: str | None = None,
    ) -> None:
        meta: dict[str, Any] = {}
        if service:
            meta["service"] = service
        super().__init__(message, user_message, meta)


class EmailDeliveryError(ExternalServiceError):
    """All email providers failed."""
    code = "email_delivery_failed"
    default_user_message = "Email delivery failed. Please try again in a few minutes."


# ── Database errors ────────────────────────────────────────────────────────────

class DatabaseError(VisaLaneError):
    """Database operation failed."""
    code = "database_error"
    http_status = 503
    default_user_message = "A database error occurred. Please try again."


def from_exception(exc: Exception, default_code: str = "internal_error") -> VisaLaneError:
    """Wrap any exception in a VisaLaneError if it isn't one already."""
    if isinstance(exc, VisaLaneError):
        return exc
    err = VisaLaneError(str(exc))
    err.code = default_code
    return err

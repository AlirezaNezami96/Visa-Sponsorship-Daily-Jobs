"""Validation and file format error classes for VisaLane."""
from __future__ import annotations

from .base import ContentError, EncryptedFileError, FileSizeError, FileTypeError, ResumeParseError, ScannedPdfError, ValidationError


class SchemaValidationError(ValidationError):
    """Payload schema validation error."""
    code = "schema_validation_error"
    default_user_message = "The request format is invalid. Please check required fields."


class CorruptedFileError(ResumeParseError):
    """File binary stream is corrupted or unreadable."""
    code = "corrupted_file"
    default_user_message = "The uploaded file appears to be corrupted. Please try uploading a fresh copy."

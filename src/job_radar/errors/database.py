"""Database and storage error classes for VisaLane."""
from __future__ import annotations

from .base import DatabaseError


class RecordNotFoundError(DatabaseError):
    """Database query returned zero rows when record was expected."""
    code = "record_not_found"
    http_status = 404
    default_user_message = "The requested database record was not found."


class DuplicateKeyError(DatabaseError):
    """Database constraint violation (duplicate unique key)."""
    code = "duplicate_key"
    http_status = 409
    default_user_message = "A record with this identifier already exists."


class StorageUploadError(DatabaseError):
    """File storage (Supabase Storage/S3) upload failed."""
    code = "storage_upload_failed"
    http_status = 503
    default_user_message = "File upload failed. Please try again."

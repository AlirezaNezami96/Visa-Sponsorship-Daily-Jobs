"""Data models for LinkedIn Content Repurposing Pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ProcessingStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    PROCESSING = "processing"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED = "skipped"


class MediaType(str, Enum):
    NONE = "none"
    IMAGE = "image"
    MULTI_IMAGE = "multi_image"
    VIDEO = "video"
    DOCUMENT = "document"


class MediaStatus(str, Enum):
    PENDING = "pending"
    ARCHIVED = "archived"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class SourcePostMediaRecord:
    id: Optional[int] = None
    source_post_id: Optional[int] = None
    media_type: str = "image"  # image, video, thumbnail
    source_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    storage_provider: str = "google_drive"
    storage_file_id: Optional[str] = None
    storage_path: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    checksum: Optional[str] = None
    download_status: str = "pending"


@dataclass
class SourcePostRecord:
    id: Optional[int] = None
    source_platform: str = "linkedin"
    source_post_id: str = ""
    source_url: Optional[str] = None
    author_name: Optional[str] = None
    author_username: Optional[str] = None
    content: str = ""
    normalized_content: str = ""
    content_hash: str = ""
    media_type: str = "none"
    media_count: int = 0
    source_json: Optional[Dict[str, Any]] = None
    source_posted_at: Optional[str] = None
    media_archived: bool = False
    media_status: str = "pending"
    processing_status: str = "available"
    reserved_at: Optional[str] = None
    reserved_by: Optional[str] = None
    generated_content: Optional[str] = None
    final_content: Optional[str] = None
    published_linkedin_post_id: Optional[str] = None
    published_linkedin_url: Optional[str] = None
    published_at: Optional[str] = None
    failure_count: int = 0
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    media_items: List[SourcePostMediaRecord] = field(default_factory=list)


@dataclass
class RepurposeJobResult:
    success: bool
    source_post_id: Optional[str] = None
    database_id: Optional[int] = None
    status: str = "completed"
    adapted_content: Optional[str] = None
    media_type: str = "none"
    processed_media_path: Optional[str] = None
    linkedin_post_urn: Optional[str] = None
    linkedin_post_url: Optional[str] = None
    error_message: Optional[str] = None
    skipped_reason: Optional[str] = None

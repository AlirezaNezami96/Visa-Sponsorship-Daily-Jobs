"""Atomic Post Selection and Reservation Service."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional, Tuple

from job_radar.repurpose.models import ProcessingStatus, SourcePostRecord
from job_radar.storage.supabase_client import SupabaseStorageClient

logger = logging.getLogger(__name__)


class SourcePostSelector:
    """Handles atomic concurrency-safe selection of source posts."""

    def __init__(self, supabase_client: Optional[SupabaseStorageClient] = None):
        self.supabase = supabase_client or SupabaseStorageClient()
        self.reuse_enabled = os.environ.get("SOURCE_POST_REUSE_ENABLED", "false").lower() in ("true", "1", "yes")

    def generate_worker_id(self) -> str:
        """Constructs a traceable execution worker ID."""
        run_id = os.environ.get("GITHUB_RUN_ID")
        run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        if run_id:
            return f"gha_{run_id}_{run_attempt}_{uuid.uuid4().hex[:6]}"
        return f"worker_{uuid.uuid4().hex[:10]}"

    def select_and_reserve_post(
        self,
        worker_id: Optional[str] = None,
        max_failures: int = 3,
    ) -> Tuple[Optional[SourcePostRecord], str]:
        """
        Atomically selects and locks the next available source post.
        Returns: (SourcePostRecord, execution_id) or (None, execution_id)
        """
        execution_id = worker_id or self.generate_worker_id()
        logger.info("Starting post selection (Execution ID: %s)", execution_id)

        if not self.supabase.is_configured:
            logger.warning("Supabase is not configured. Cannot select source post.")
            return None, execution_id

        # 1. Attempt atomic reservation via Supabase
        post_data = self.supabase.reserve_next_post(worker_id=execution_id, max_failures=max_failures)

        if not post_data:
            avail_count = self.supabase.get_available_posts_count()
            if avail_count == 0:
                logger.info("No eligible source posts remain.")
            else:
                logger.info("No post could be reserved at this time (all candidates locked or failed).")
            return None, execution_id

        # 2. Build SourcePostRecord
        record = SourcePostRecord(
            id=post_data.get("id"),
            source_platform=post_data.get("source_platform", "linkedin"),
            source_post_id=post_data.get("source_post_id", ""),
            source_url=post_data.get("source_url"),
            author_name=post_data.get("author_name"),
            author_username=post_data.get("author_username"),
            content=post_data.get("content", ""),
            normalized_content=post_data.get("normalized_content", ""),
            content_hash=post_data.get("content_hash", ""),
            media_type=post_data.get("media_type", "none"),
            media_count=post_data.get("media_count", 0),
            source_json=post_data.get("source_json"),
            source_posted_at=post_data.get("source_posted_at"),
            media_archived=bool(post_data.get("media_archived", False)),
            media_status=post_data.get("media_status", "pending"),
            processing_status=ProcessingStatus.RESERVED.value,
            reserved_at=post_data.get("reserved_at"),
            reserved_by=execution_id,
            failure_count=post_data.get("failure_count", 0),
        )

        logger.info(
            "Successfully reserved source post ID: %s (DB ID: %s, Media: %s)",
            record.source_post_id,
            record.id,
            record.media_type,
        )
        return record, execution_id

    def release_reservation(
        self,
        post_id: int,
        execution_id: str,
        retryable: bool = True,
        error_message: Optional[str] = None,
        increment_failure: bool = True,
    ) -> bool:
        """
        Safely releases or fails a reserved source post.
        If retryable, sets processing_status='available'.
        If non-retryable, sets processing_status='failed'.
        """
        if not self.supabase.is_configured or not post_id:
            return False

        new_status = ProcessingStatus.AVAILABLE.value if retryable else ProcessingStatus.FAILED.value
        current = self.supabase.get_post_by_id(post_id)
        current_failures = current.get("failure_count", 0) if current else 0
        new_failures = current_failures + 1 if increment_failure else current_failures

        # If failures exceed limit (3), mark as failed permanently
        if new_failures >= 3:
            new_status = ProcessingStatus.FAILED.value

        extra = {
            "failure_count": new_failures,
            "last_error": error_message or "",
            "reserved_by": None,
        }

        success = self.supabase.update_post_status(
            post_id=post_id,
            status=new_status,
            execution_id=execution_id,
            **extra,
        )
        logger.info(
            "Released post %d: new_status=%s (failures=%d, error=%s)",
            post_id,
            new_status,
            new_failures,
            error_message,
        )
        return success

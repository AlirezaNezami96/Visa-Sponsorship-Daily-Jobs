"""Master Orchestrator for LinkedIn Source Post Repurposing & Auto-Publishing."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from job_radar.repurpose.media_manager import MediaManager
from job_radar.repurpose.models import ProcessingStatus, RepurposeJobResult, SourcePostRecord
from job_radar.repurpose.publisher import LinkedInRepurposePublisher
from job_radar.repurpose.rewriter import ContentRewriter
from job_radar.repurpose.selector import SourcePostSelector
from job_radar.storage.google_drive_client import GoogleDriveStorageClient
from job_radar.storage.supabase_client import SupabaseStorageClient

logger = logging.getLogger(__name__)


class RepurposeOrchestrator:
    """Coordinates selection, rewriting, media processing, LinkedIn publishing, and status tracking."""

    def __init__(
        self,
        supabase_client: Optional[SupabaseStorageClient] = None,
        drive_client: Optional[GoogleDriveStorageClient] = None,
    ):
        self.supabase = supabase_client or SupabaseStorageClient()
        self.drive = drive_client or GoogleDriveStorageClient()
        self.selector = SourcePostSelector(self.supabase)
        self.rewriter = ContentRewriter()
        self.media_mgr = MediaManager(self.drive, self.supabase)
        self.publisher = LinkedInRepurposePublisher()

    def run(
        self,
        worker_id: Optional[str] = None,
        dry_run: bool = False,
        force_post_id: Optional[str] = None,
    ) -> RepurposeJobResult:
        """
        Executes an unattended LinkedIn repurposing run:
          1. Reserve eligible post
          2. Download & process media (including video badge overlay)
          3. Rewrite content with Gemini 3.7 Flash
          4. Publish to LinkedIn
          5. Update database status and clean up temporary assets
        """
        logger.info("Starting LinkedIn source repurposing pipeline (dry_run=%s)...", dry_run)
        execution_id = worker_id or self.selector.generate_worker_id()

        # ── 1. Select Post ──
        post: Optional[SourcePostRecord] = None
        if force_post_id:
            logger.info("Using forced source_post_id: %s", force_post_id)
            post_data = self.supabase.get_post_by_id(int(force_post_id)) if force_post_id.isdigit() else None
            if post_data:
                post = SourcePostRecord(
                    id=post_data.get("id"),
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
                    processing_status=ProcessingStatus.RESERVED.value,
                )
        else:
            post, execution_id = self.selector.select_and_reserve_post(worker_id=execution_id)

        if not post:
            logger.info("No eligible source posts remain.")
            return RepurposeJobResult(
                success=True,
                status="exhausted",
                skipped_reason="No eligible source posts available.",
            )

        logger.info(
            "Selected source post: %s (DB ID: %s, Media: %s)",
            post.source_post_id,
            post.id,
            post.media_type,
        )

        # ── 2. Mark Processing ──
        if post.id and not dry_run:
            self.supabase.update_post_status(post.id, ProcessingStatus.PROCESSING.value, execution_id=execution_id)

        temp_dir = Path(tempfile.mkdtemp(prefix="repurpose_media_"))
        try:
            # ── 3. Media Preparation ──
            logger.info("Preparing media for post %s (Type: %s)...", post.source_post_id, post.media_type)
            media_ok, media_files, media_err = self.media_mgr.prepare_post_media(post, temp_dir)
            if not media_ok:
                logger.error("Media preparation failed: %s", media_err)
                if post.id and not dry_run:
                    self.selector.release_reservation(
                        post.id,
                        execution_id,
                        retryable=True,
                        error_message=f"Media preparation failed: {media_err}",
                    )
                return RepurposeJobResult(
                    success=False,
                    source_post_id=post.source_post_id,
                    database_id=post.id,
                    status="failed",
                    error_message=media_err,
                )

            # ── 4. Gemini Content Rewriting ──
            logger.info("Running Gemini 3.7 Flash adaptation...")
            rewrite_ok, adapted_text, rewrite_err = self.rewriter.adapt_post(post)
            if not rewrite_ok or not adapted_text:
                logger.error("Content rewriting failed: %s", rewrite_err)
                if post.id and not dry_run:
                    self.selector.release_reservation(
                        post.id,
                        execution_id,
                        retryable=True,
                        error_message=f"Gemini rewriting failed: {rewrite_err}",
                    )
                return RepurposeJobResult(
                    success=False,
                    source_post_id=post.source_post_id,
                    database_id=post.id,
                    status="failed",
                    error_message=rewrite_err,
                )

            logger.info("Adapted text preview:\n%s\n---", adapted_text[:200] + "..." if len(adapted_text) > 200 else adapted_text)

            # ── 5. LinkedIn Publishing ──
            logger.info("Publishing to LinkedIn (Media Count: %d)...", len(media_files))
            pub_ok, status_code, post_urn, res_text, post_url = self.publisher.publish_post(
                text=adapted_text,
                media_files=media_files,
                media_type=post.media_type,
                dry_run=dry_run,
            )

            if not pub_ok:
                logger.error("Publishing to LinkedIn failed (%d): %s", status_code, res_text)
                if post.id and not dry_run:
                    self.selector.release_reservation(
                        post.id,
                        execution_id,
                        retryable=True,
                        error_message=f"LinkedIn publish error ({status_code}): {res_text}",
                    )
                return RepurposeJobResult(
                    success=False,
                    source_post_id=post.source_post_id,
                    database_id=post.id,
                    status="failed",
                    adapted_content=adapted_text,
                    error_message=f"LinkedIn publish failed ({status_code}): {res_text}",
                )

            # ── 6. Mark Published Permanently in Database ──
            if post.id and not dry_run:
                self.supabase.update_post_status(
                    post_id=post.id,
                    status=ProcessingStatus.PUBLISHED.value,
                    execution_id=execution_id,
                    published_linkedin_post_id=post_urn,
                    published_linkedin_url=post_url,
                    published_at="now()",
                    final_content=adapted_text,
                    generated_content=adapted_text,
                    last_error=None,
                )
                logger.info("Source post %s marked permanently as published in Supabase.", post.source_post_id)

            return RepurposeJobResult(
                success=True,
                source_post_id=post.source_post_id,
                database_id=post.id,
                status="published",
                adapted_content=adapted_text,
                media_type=post.media_type,
                processed_media_path=str(media_files[0]) if media_files else None,
                linkedin_post_urn=post_urn,
                linkedin_post_url=post_url,
            )

        finally:
            # ── 7. Safe Cleanup of Temporary Runner Files ──
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug("Cleaned up temporary runner directory: %s", temp_dir)


def run_repurpose_pipeline(
    worker_id: Optional[str] = None,
    dry_run: bool = False,
    force_post_id: Optional[str] = None,
) -> RepurposeJobResult:
    """Convenience functional entrypoint for the repurposing orchestrator."""
    orchestrator = RepurposeOrchestrator()
    return orchestrator.run(worker_id=worker_id, dry_run=dry_run, force_post_id=force_post_id)

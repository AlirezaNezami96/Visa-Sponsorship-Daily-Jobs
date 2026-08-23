"""Source Posts Dataset Ingestion and Deduplication Service."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from job_radar.repurpose.deduplicator import ContentDeduplicator
from job_radar.repurpose.models import MediaType, ProcessingStatus, SourcePostMediaRecord, SourcePostRecord
from job_radar.storage.supabase_client import SupabaseStorageClient

logger = logging.getLogger(__name__)


@dataclass
class ImportSummary:
    total_parsed: int = 0
    new_imported: int = 0
    exact_duplicates: int = 0
    near_duplicates: int = 0
    posts_with_images: int = 0
    posts_with_videos: int = 0
    media_records_created: int = 0
    skipped_records: int = 0
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            "================ IMPORT SUMMARY ================\n"
            f"Total Parsed:          {self.total_parsed}\n"
            f"New / Active:          {self.new_imported}\n"
            f"Exact Duplicates:      {self.exact_duplicates}\n"
            f"Near Duplicates:       {self.near_duplicates}\n"
            f"Posts with Images:     {self.posts_with_images}\n"
            f"Posts with Videos:     {self.posts_with_videos}\n"
            f"Media Records Created: {self.media_records_created}\n"
            f"Skipped Records:       {self.skipped_records}\n"
            f"Errors:                {len(self.errors)}\n"
            "================================================"
        )


class SourcePostImporter:
    """Ingests raw source post JSON datasets into Supabase with full deduplication."""

    def __init__(self, supabase_client: Optional[SupabaseStorageClient] = None):
        self.supabase = supabase_client or SupabaseStorageClient()
        self.dedup = ContentDeduplicator()

    def load_json_dataset(self, file_path: str | Path) -> List[Dict[str, Any]]:
        """Loads and validates source post JSON array from file."""
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Source posts dataset not found: {file_path}")

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "posts" in data:
            data = data["posts"]

        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list of posts in {file_path}, got {type(data)}")

        return data

    def parse_record(self, raw_post: Dict[str, Any]) -> Tuple[SourcePostRecord, List[SourcePostMediaRecord]]:
        """Extracts normalized fields and media items from raw JSON post."""
        post_id = str(raw_post.get("id") or "").strip()
        linkedin_url = raw_post.get("linkedinUrl") or ""
        content = raw_post.get("content") or ""

        # Author fields
        author = raw_post.get("author") or {}
        author_name = author.get("name") if isinstance(author, dict) else ""
        author_username = author.get("publicIdentifier") if isinstance(author, dict) else ""

        # Posted at
        posted_at = raw_post.get("postedAt") or {}
        posted_at_iso = posted_at.get("date") if isinstance(posted_at, dict) else None

        # Content normalization & hashing
        norm_content = self.dedup.normalize_text(content)
        content_hash = self.dedup.compute_content_hash(content)

        # Media extraction
        media_items: List[SourcePostMediaRecord] = []
        post_images = raw_post.get("postImages") or []
        post_video = raw_post.get("postVideo") or {}

        media_type = MediaType.NONE.value
        media_count = 0

        # 1. Video Check
        if isinstance(post_video, dict) and (post_video.get("videoUrl") or post_video.get("thumbnailUrl")):
            media_type = MediaType.VIDEO.value
            video_url = post_video.get("videoUrl")
            thumb_url = post_video.get("thumbnailUrl")
            if video_url:
                media_count += 1
                media_items.append(
                    SourcePostMediaRecord(
                        media_type="video",
                        source_url=video_url,
                        thumbnail_url=thumb_url,
                    )
                )
            elif thumb_url:
                media_count += 1
                media_items.append(
                    SourcePostMediaRecord(
                        media_type="thumbnail",
                        source_url=thumb_url,
                    )
                )

        # 2. Images Check
        elif isinstance(post_images, list) and len(post_images) > 0:
            media_count = len(post_images)
            media_type = MediaType.MULTI_IMAGE.value if len(post_images) > 1 else MediaType.IMAGE.value
            for img in post_images:
                img_url = img.get("url") if isinstance(img, dict) else str(img)
                if img_url:
                    media_items.append(
                        SourcePostMediaRecord(
                            media_type="image",
                            source_url=img_url,
                        )
                    )

        post_record = SourcePostRecord(
            source_platform="linkedin",
            source_post_id=post_id,
            source_url=linkedin_url,
            author_name=author_name,
            author_username=author_username,
            content=content,
            normalized_content=norm_content,
            content_hash=content_hash,
            media_type=media_type,
            media_count=media_count,
            source_json=raw_post,
            source_posted_at=posted_at_iso,
            media_archived=False,
            media_status="pending" if media_count > 0 else "not_applicable",
            processing_status=ProcessingStatus.AVAILABLE.value,
        )

        return post_record, media_items

    def import_dataset(
        self,
        file_path: str | Path,
        dry_run: bool = False,
    ) -> ImportSummary:
        """
        Processes and imports all source posts into Supabase.
        Performs in-memory and database-aware deduplication.
        """
        raw_items = self.load_json_dataset(file_path)
        summary = ImportSummary(total_parsed=len(raw_items))

        # Memory caches for deduplication during single import run
        seen_hashes: Dict[str, str] = {}  # hash -> source_post_id
        canonical_texts: List[Tuple[str, str]] = []  # (source_post_id, normalized_text)

        for raw in raw_items:
            try:
                post, media_list = self.parse_record(raw)
                if not post.source_post_id or not post.content.strip():
                    summary.skipped_records += 1
                    continue

                if post.media_type == MediaType.VIDEO.value:
                    summary.posts_with_videos += 1
                elif post.media_type in (MediaType.IMAGE.value, MediaType.MULTI_IMAGE.value):
                    summary.posts_with_images += 1

                # 1. Exact Duplicate Detection
                if post.content_hash in seen_hashes:
                    summary.exact_duplicates += 1
                    summary.skipped_records += 1
                    canonical_id = seen_hashes[post.content_hash]
                    post.processing_status = ProcessingStatus.SKIPPED.value
                    post.last_error = f"duplicate_of:{canonical_id}"
                else:
                    # 2. Near Duplicate Detection
                    is_near_dup, matched_id, score = self.dedup.is_near_duplicate(
                        post.normalized_content,
                        canonical_texts,
                    )
                    if is_near_dup and matched_id:
                        summary.near_duplicates += 1
                        summary.skipped_records += 1
                        post.processing_status = ProcessingStatus.SKIPPED.value
                        post.last_error = f"near_duplicate_of:{matched_id} (score={score:.2f})"
                    else:
                        seen_hashes[post.content_hash] = post.source_post_id
                        canonical_texts.append((post.source_post_id, post.normalized_content))
                        summary.new_imported += 1

                # 3. Upsert to Supabase if not dry run
                if not dry_run and self.supabase.is_configured:
                    post_dict = {
                        "source_platform": post.source_platform,
                        "source_post_id": post.source_post_id,
                        "source_url": post.source_url,
                        "author_name": post.author_name,
                        "author_username": post.author_username,
                        "content": post.content,
                        "normalized_content": post.normalized_content,
                        "content_hash": post.content_hash,
                        "media_type": post.media_type,
                        "media_count": post.media_count,
                        "source_json": post.source_json,
                        "source_posted_at": post.source_posted_at,
                        "media_archived": post.media_archived,
                        "media_status": post.media_status,
                        "processing_status": post.processing_status,
                        "last_error": post.last_error,
                    }
                    upserted = self.supabase.upsert_source_post(post_dict)
                    if upserted and "id" in upserted:
                        db_post_id = upserted["id"]
                        for m in media_list:
                            m_dict = {
                                "source_post_id": db_post_id,
                                "media_type": m.media_type,
                                "source_url": m.source_url,
                                "thumbnail_url": m.thumbnail_url,
                                "download_status": m.download_status,
                            }
                            self.supabase.upsert_source_media(m_dict)
                            summary.media_records_created += 1

            except Exception as exc:
                err_msg = f"Error processing post ID '{raw.get('id')}': {exc}"
                logger.error(err_msg)
                summary.errors.append(err_msg)

        logger.info("\n%s", summary)
        return summary

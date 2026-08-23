"""Media Archiving, Retrieval, and Processing Manager."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

from job_radar.creator_badge import create_creator_badge_video
from job_radar.repurpose.models import MediaType, SourcePostMediaRecord, SourcePostRecord
from job_radar.storage.google_drive_client import GoogleDriveStorageClient
from job_radar.storage.supabase_client import SupabaseStorageClient

logger = logging.getLogger(__name__)


class MediaManager:
    """Manages downloading, durable Google Drive archiving, and video badge overlay processing."""

    def __init__(
        self,
        drive_client: Optional[GoogleDriveStorageClient] = None,
        supabase_client: Optional[SupabaseStorageClient] = None,
    ):
        self.drive = drive_client or GoogleDriveStorageClient()
        self.supabase = supabase_client or SupabaseStorageClient()
        self.badge_enabled = os.environ.get("VIDEO_BADGE_PROCESSOR_ENABLED", "true").lower() in ("true", "1", "yes")

    def download_url_to_file(self, url: str, destination: Path) -> Optional[Path]:
        """Downloads external media URL to local destination with timeout and stream buffer."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                if r.status_code == 200:
                    with open(destination, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                f.write(chunk)
                    return destination
                else:
                    logger.warning("Download returned HTTP %d for URL: %s", r.status_code, url)
        except Exception as exc:
            logger.error("Failed to download media from %s: %s", url, exc)
        return None

    def archive_media_file_to_drive(
        self,
        local_file: Path,
        source_post_id: str,
        filename: str,
        mime_type: str = "application/octet-stream",
    ) -> Optional[Dict[str, Any]]:
        """Uploads a local media file to the Google Drive post folder."""
        if not self.drive.is_configured:
            logger.debug("Google Drive not configured, skipping cloud archive.")
            return None

        post_folder_id = self.drive.get_post_media_folder(source_post_id)
        if not post_folder_id:
            logger.warning("Could not establish Google Drive post folder for post %s", source_post_id)
            return None

        result = self.drive.upload_file(
            content=local_file,
            filename=filename,
            mime_type=mime_type,
            folder_id=post_folder_id,
        )
        return result

    def prepare_post_media(
        self,
        post: SourcePostRecord,
        temp_dir: Path,
    ) -> Tuple[bool, List[Path], Optional[str]]:
        """
        Retrieves and processes all media required for publishing:
          - Video: downloads original (from Drive or source URL), archives to Drive, and passes through CreatorBadgeService.
          - Image: downloads original (from Drive or source URL), archives to Drive.
        Returns: (success, local_processed_paths, error_message)
        """
        if post.media_type == MediaType.NONE.value:
            return True, [], None

        media_records = self.supabase.get_media_for_post(post.id) if (post.id and self.supabase.is_configured) else []
        if not isinstance(media_records, list):
            media_records = []

        if not media_records and post.source_json:
            # Fallback to extracting from source_json if DB records empty
            from job_radar.repurpose.importer import SourcePostImporter
            _, parsed_media = SourcePostImporter().parse_record(post.source_json)
            media_records = [
                {
                    "media_type": m.media_type,
                    "source_url": m.source_url,
                    "thumbnail_url": m.thumbnail_url,
                    "storage_file_id": m.storage_file_id,
                }
                for m in parsed_media
            ]

        if not media_records:
            logger.warning("Post %s has media_type '%s' but no media records found.", post.source_post_id, post.media_type)
            return False, [], "No media URLs or Drive records found for media post."

        processed_paths: List[Path] = []

        # ── 1. Video Processing ──
        if post.media_type == MediaType.VIDEO.value:
            video_item = next((m for m in media_records if m.get("media_type") == "video"), media_records[0])
            drive_file_id = video_item.get("storage_file_id")
            source_url = video_item.get("source_url")

            raw_video_path = temp_dir / f"original_{post.source_post_id}.mp4"

            # 1a. Try downloading from Google Drive
            downloaded = False
            if drive_file_id and self.drive.is_configured:
                if self.drive.download_file(drive_file_id, raw_video_path):
                    downloaded = True

            # 1b. Fallback: download from source URL & archive to Google Drive
            if not downloaded and source_url:
                if self.download_url_to_file(source_url, raw_video_path):
                    downloaded = True
                    # Archive to Google Drive
                    drive_upload = self.archive_media_file_to_drive(
                        local_file=raw_video_path,
                        source_post_id=post.source_post_id,
                        filename=f"original_video_{post.source_post_id}.mp4",
                        mime_type="video/mp4",
                    )
                    if drive_upload and "id" in drive_upload:
                        video_item["storage_file_id"] = drive_upload["id"]
                        video_item["download_status"] = "downloaded"
                        if post.id:
                            self.supabase.upsert_source_media({
                                "source_post_id": post.id,
                                "media_type": "video",
                                "storage_file_id": drive_upload["id"],
                                "download_status": "downloaded",
                            })
                            self.supabase.update_post_status(post.id, post.processing_status, media_archived=True, media_status="archived")

            if not downloaded or not raw_video_path.exists():
                return False, [], f"Failed to retrieve video for post {post.source_post_id} (URL expired or missing)."

            # 1c. Process video through CreatorBadgeService
            if self.badge_enabled:
                badged_video_path = temp_dir / f"branded_{post.source_post_id}.mp4"
                try:
                    logger.info("Applying creator badge overlay to video for post %s...", post.source_post_id)
                    create_creator_badge_video(
                        input_path=raw_video_path,
                        output_path=badged_video_path,
                        name="Alireza Nezami",
                        username="alireza-nezami",
                        remove_existing_badge=True,
                    )
                    processed_paths.append(badged_video_path)
                except Exception as exc:
                    logger.error("Creator badge processing failed: %s. Using original video as fallback.", exc)
                    processed_paths.append(raw_video_path)
            else:
                processed_paths.append(raw_video_path)

            return True, processed_paths, None

        # ── 2. Image Processing ──
        if post.media_type in (MediaType.IMAGE.value, MediaType.MULTI_IMAGE.value):
            image_items = [m for m in media_records if m.get("media_type") == "image"]
            if not image_items:
                image_items = media_records

            for idx, img in enumerate(image_items):
                drive_file_id = img.get("storage_file_id")
                source_url = img.get("source_url")
                img_path = temp_dir / f"image_{post.source_post_id}_{idx}.jpg"

                downloaded = False
                if drive_file_id and self.drive.is_configured:
                    if self.drive.download_file(drive_file_id, img_path):
                        downloaded = True

                if not downloaded and source_url:
                    if self.download_url_to_file(source_url, img_path):
                        downloaded = True
                        drive_upload = self.archive_media_file_to_drive(
                            local_file=img_path,
                            source_post_id=post.source_post_id,
                            filename=f"image_{post.source_post_id}_{idx}.jpg",
                            mime_type="image/jpeg",
                        )
                        if drive_upload and "id" in drive_upload and post.id:
                            self.supabase.upsert_source_media({
                                "source_post_id": post.id,
                                "media_type": "image",
                                "storage_file_id": drive_upload["id"],
                                "download_status": "downloaded",
                            })

                if downloaded and img_path.exists():
                    processed_paths.append(img_path)

            if not processed_paths:
                return False, [], f"Failed to retrieve images for post {post.source_post_id}."

            return True, processed_paths, None

        return True, [], None

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
        auto_publish: bool = False,
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
            rewrite_ok, adapted_text, first_comment_cta, rewrite_err = self.rewriter.adapt_post(post)
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

            # ── 5. Staging for Telegram Approval OR Direct Auto-Publishing ──
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            use_telegram_approval = bool(bot_token and chat_id and not auto_publish)

            if use_telegram_approval:
                logger.info("Staging repurposed post for Telegram approval (bot_token configured)...")
                tg_ok, msg_id = self.send_telegram_draft(
                    post=post,
                    adapted_text=adapted_text,
                    first_comment_cta=first_comment_cta,
                    media_files=media_files,
                    bot_token=bot_token,
                    chat_id=chat_id,
                    dry_run=dry_run,
                )

                # Persist pending approval state
                state_dir = Path("state")
                state_dir.mkdir(parents=True, exist_ok=True)
                media_save_dir = state_dir / "pending_media"
                media_save_dir.mkdir(parents=True, exist_ok=True)

                saved_media_paths = []
                for mf in media_files:
                    target_mf = media_save_dir / mf.name
                    try:
                        shutil.copy2(mf, target_mf)
                        saved_media_paths.append(str(target_mf))
                    except Exception as copy_err:
                        logger.warning("Could not copy media %s to state: %s", mf, copy_err)

                pending_state = {
                    "is_repurpose": True,
                    "database_id": post.id,
                    "source_post_id": post.source_post_id,
                    "text": adapted_text,
                    "first_comment_cta": first_comment_cta,
                    "media_type": post.media_type,
                    "media_files": saved_media_paths,
                    "source_url": post.source_url,
                    "author_name": post.author_name,
                    "message_id": msg_id,
                    "chat_id": chat_id,
                    "execution_id": execution_id,
                }
                pending_file = state_dir / "pending_linkedin_post.json"
                from job_radar.filters.dedupe import atomic_save_json
                atomic_save_json(pending_state, str(pending_file))

                if post.id and not dry_run:
                    self.supabase.update_post_status(
                        post_id=post.id,
                        status=ProcessingStatus.PENDING_APPROVAL.value,
                        execution_id=execution_id,
                        generated_content=adapted_text,
                    )
                    logger.info("Source post %s marked as pending_approval in Supabase.", post.source_post_id)

                return RepurposeJobResult(
                    success=True,
                    source_post_id=post.source_post_id,
                    database_id=post.id,
                    status="pending_approval",
                    adapted_content=adapted_text,
                    media_type=post.media_type,
                    processed_media_path=str(saved_media_paths[0]) if saved_media_paths else None,
                )

            # ── 6. Direct Auto-Publishing to LinkedIn (Bypassing Telegram) ──
            logger.info("Directly publishing to LinkedIn without Telegram approval (auto_publish=%s)...", auto_publish)
            publisher = LinkedInRepurposePublisher()
            pub_ok, status_code, post_urn, res_text, post_url = publisher.publish_post(
                text=adapted_text,
                media_files=media_files,
                media_type=post.media_type,
                dry_run=dry_run,
            )

            if not pub_ok:
                logger.error("LinkedIn publication failed (Status %d): %s", status_code, res_text)
                if post.id and not dry_run:
                    self.selector.release_reservation(
                        post.id,
                        execution_id,
                        retryable=True,
                        error_message=f"LinkedIn publish HTTP {status_code}: {res_text}",
                    )
                return RepurposeJobResult(
                    success=False,
                    source_post_id=post.source_post_id,
                    database_id=post.id,
                    status="failed",
                    error_message=res_text,
                )

            # ── 7. Permanent Database Update on Successful Publication ──
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
            # ── 8. Safe Cleanup of Temporary Runner Files ──
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug("Cleaned up temporary runner directory: %s", temp_dir)

    def send_telegram_draft(
        self,
        post: SourcePostRecord,
        adapted_text: str,
        media_files: list[Path],
        bot_token: str,
        chat_id: str,
        first_comment_cta: Optional[str] = None,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[int]]:
        """
        Sends repurposed post preview and inline action buttons to Telegram:
        - [✅ Accept]
        - [❌ Reject]
        - [🔄 Reject & Generate Another]
        """
        import html as html_lib
        import requests

        if dry_run:
            logger.info("[DRY RUN] Would send Telegram draft with Accept / Reject / Reject & Generate Another buttons")
            return True, 99999

        photo_msg_id = None
        # Send media preview (photo / video) if present
        if media_files:
            first_media = media_files[0]
            if post.media_type == "video" or first_media.suffix.lower() in (".mp4", ".mov", ".mkv"):
                video_url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
                try:
                    with open(first_media, "rb") as vf:
                        files = {"video": (first_media.name, vf, "video/mp4")}
                        data = {
                            "chat_id": chat_id,
                            "caption": f"🎬 <b>Video Preview</b>",
                            "parse_mode": "HTML",
                        }
                        v_res = requests.post(video_url, data=data, files=files, timeout=60)
                        if v_res.status_code == 200:
                            photo_msg_id = v_res.json().get("result", {}).get("message_id")
                except Exception as ve:
                    logger.warning("Failed to send Telegram video preview: %s", ve)
            elif first_media.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                try:
                    with open(first_media, "rb") as pf:
                        files = {"photo": (first_media.name, pf, "image/jpeg")}
                        data = {
                            "chat_id": chat_id,
                            "caption": f"🖼️ <b>Media Preview</b>",
                            "parse_mode": "HTML",
                        }
                        p_res = requests.post(photo_url, data=data, files=files, timeout=30)
                        if p_res.status_code == 200:
                            photo_msg_id = p_res.json().get("result", {}).get("message_id")
                except Exception as pe:
                    logger.warning("Failed to send Telegram photo preview: %s", pe)

        # Send text message with clean post text and first-comment CTA (no credit headers)
        msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        comment_section = ""
        if first_comment_cta and first_comment_cta.strip():
            comment_section = f"\n\n💬 <b>Call to Action (First Comment):</b>\n<i>{html_lib.escape(first_comment_cta.strip())}</i>"

        formatted_text = f"{html_lib.escape(adapted_text)}{comment_section}"

        msg_payload = {
            "chat_id": chat_id,
            "text": formatted_text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "✅ Accept", "callback_data": "approve"}],
                    [
                        {"text": "❌ Reject", "callback_data": "reject"},
                        {"text": "🔄 Reject & Generate Another", "callback_data": "reject_regen"}
                    ]
                ]
            }
        }

        try:
            m_res = requests.post(msg_url, json=msg_payload, timeout=20)
            m_res.raise_for_status()
            text_msg_id = m_res.json().get("result", {}).get("message_id")
            return True, text_msg_id
        except Exception as me:
            logger.error("Failed to send Telegram text draft: %s", me)
            return False, None


def run_repurpose_pipeline(
    worker_id: Optional[str] = None,
    dry_run: bool = False,
    force_post_id: Optional[str] = None,
    auto_publish: bool = False,
) -> RepurposeJobResult:
    """Convenience functional entrypoint for the repurposing orchestrator."""
    orchestrator = RepurposeOrchestrator()
    return orchestrator.run(
        worker_id=worker_id,
        dry_run=dry_run,
        force_post_id=force_post_id,
        auto_publish=auto_publish,
    )


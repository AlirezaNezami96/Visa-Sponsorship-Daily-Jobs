"""LinkedIn Publisher and Telegram Approval Handler."""

from __future__ import annotations

import html
import json
import logging
import os
import sys

import requests

logger = logging.getLogger(__name__)

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
REPURPOSE_PENDING_FILE = os.path.join(STATE_DIR, "pending_linkedin_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")


def trigger_generate_workflow() -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        logger.warning("GITHUB_REPOSITORY or GITHUB_TOKEN not set. Cannot auto-trigger generate.yml workflow.")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/generate.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main"}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        return res.status_code in (204, 201, 200)
    except Exception as e:
        logger.warning("Exception while triggering generate.yml: %s", e)
        return False


def answer_callback_query(bot_token: str, callback_query_id: str, text: str = "") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.warning("Failed to answer callback query: %s", e)


def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)


def edit_telegram_message(
    bot_token: str, chat_id: str, message_id: int, text: str, parse_mode: str = "HTML", keep_keyboard: bool = False
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if keep_keyboard:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": "✅ Accept", "callback_data": "approve"}],
                [
                    {"text": "❌ Reject", "callback_data": "reject"},
                    {"text": "🔄 Reject & Regenerate", "callback_data": "reject_regen"},
                ],
            ]
        }
    else:
        payload["reply_markup"] = {"inline_keyboard": []}

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to edit Telegram message_id=%s: %s", message_id, e)


def get_linkedin_api_version() -> str:
    raw = os.environ.get("LINKEDIN_API_VERSION", "202604").strip()
    if len(raw) == 8 and raw.isdigit():
        return raw[:6]
    return raw if raw else "202604"


def upload_image_to_linkedin(access_token: str, person_urn: str, image_bytes: bytes) -> str:
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    linkedin_version = get_linkedin_api_version()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": linkedin_version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    init_body = {"initializeUploadRequest": {"owner": person_urn}}
    try:
        init_res = requests.post(init_url, headers=headers, json=init_body, timeout=20)
        if init_res.status_code != 200:
            return ""

        val = init_res.json().get("value", {})
        upload_url = val.get("uploadUrl")
        image_urn = val.get("image")

        if not upload_url or not image_urn:
            return ""

        put_headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "image/jpeg"}
        put_res = requests.put(upload_url, headers=put_headers, data=image_bytes, timeout=30)
        if 200 <= put_res.status_code < 300:
            return image_urn
    except Exception:
        pass
    return ""


def publish_to_linkedin(
    access_token: str, person_urn: str, text: str, cover_bytes: bytes = None
) -> tuple[bool, int, str, str]:
    url = "https://api.linkedin.com/rest/posts"
    linkedin_version = get_linkedin_api_version()

    if not person_urn.startswith("urn:li:person:"):
        person_urn = f"urn:li:person:{person_urn}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": linkedin_version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    body = {
        "author": person_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    if cover_bytes and len(cover_bytes) > 1000:
        image_urn = upload_image_to_linkedin(access_token, person_urn, cover_bytes)
        if image_urn:
            body["content"] = {"media": {"id": image_urn, "altText": "Technology Article Illustration"}}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        status_code = resp.status_code
        res_text = resp.text
        if 200 <= status_code < 300:
            post_urn = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id") or ""
            return True, status_code, post_urn, res_text
        else:
            return False, status_code, "", res_text
    except Exception as err:
        return False, 0, "", str(err)


def trigger_repurpose_workflow() -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        logger.warning(
            "GITHUB_REPOSITORY or GITHUB_TOKEN not set. Cannot auto-trigger linkedin-republish.yml workflow."
        )
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/linkedin-republish.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main"}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        logger.info("Triggered linkedin-republish.yml workflow (HTTP %d)", res.status_code)
        return res.status_code in (204, 201, 200)
    except Exception as e:
        logger.warning("Exception while triggering linkedin-republish.yml: %s", e)
        return False


def cleanup_state_files():
    import shutil

    for f in (PENDING_FILE, REPURPOSE_PENDING_FILE, COVER_FILE):
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
    pending_media_dir = os.path.join(STATE_DIR, "pending_media")
    if os.path.exists(pending_media_dir):
        try:
            shutil.rmtree(pending_media_dir, ignore_errors=True)
        except Exception:
            pass


def check_and_publish_post():
    from pathlib import Path

    from job_radar.storage.supabase_client import SupabaseStorageClient

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id_env = os.environ.get("TELEGRAM_CHAT_ID")
    authorized_user_id = os.environ.get("TELEGRAM_AUTHORIZED_USER_ID")
    linkedin_access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_person_urn = os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:aAOQrAt7pG")

    missing = []
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id_env:
        missing.append("TELEGRAM_CHAT_ID")
    if not authorized_user_id:
        missing.append("TELEGRAM_AUTHORIZED_USER_ID")
    if not linkedin_access_token:
        missing.append("LINKEDIN_ACCESS_TOKEN")

    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)

    raw_payload = os.environ.get("CLIENT_PAYLOAD")
    payload = {}
    if raw_payload:
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception as e:
            logger.warning("Could not parse CLIENT_PAYLOAD JSON: %s", e)

    action = payload.get("action")
    chat_id = payload.get("chat_id") or chat_id_env
    msg_id = payload.get("message_id")
    user_id = payload.get("user_id")

    if user_id and authorized_user_id:
        u_str = str(user_id).strip()
        auth_str = str(authorized_user_id).strip()
        if u_str != auth_str:
            logger.warning("Unauthorized user_id='%s' in client_payload. Expected '%s'. Terminating.", u_str, auth_str)
            sys.exit(0)

    # ── Load Pending Post State (Multi-Source with Supabase Fallback) ──
    pending_data = None
    for p_candidate in (REPURPOSE_PENDING_FILE, PENDING_FILE):
        if os.path.exists(p_candidate):
            try:
                with open(p_candidate, "r", encoding="utf-8") as f:
                    pending_data = json.load(f)
                if pending_data:
                    logger.info("Loaded pending post draft from %s", p_candidate)
                    break
            except Exception as e:
                logger.warning("Failed to read %s: %s", p_candidate, e)

    supabase = SupabaseStorageClient()

    # Fallback to Supabase database source of truth if local JSON files are missing
    if not pending_data and supabase.is_configured:
        db_post = supabase.get_pending_approval_post()
        if db_post:
            logger.info(
                "Retrieved active pending post from Supabase (id=%s, source_post_id=%s)",
                db_post.get("id"),
                db_post.get("source_post_id"),
            )
            gen_content = db_post.get("generated_content") or db_post.get("content", "")
            post_text_db = gen_content
            first_comment_cta_db = None
            if (
                isinstance(gen_content, str)
                and gen_content.strip().startswith("{")
                and gen_content.strip().endswith("}")
            ):
                try:
                    parsed_gen = json.loads(gen_content)
                    post_text_db = parsed_gen.get("text", gen_content)
                    first_comment_cta_db = parsed_gen.get("first_comment_cta")
                except Exception:
                    pass

            from job_radar.repurpose.media_manager import MediaManager
            from job_radar.repurpose.models import SourcePostRecord

            media_mgr = MediaManager(supabase_client=supabase)
            source_rec = SourcePostRecord(
                id=db_post.get("id"),
                source_post_id=db_post.get("source_post_id"),
                source_url=db_post.get("source_url"),
                author_name=db_post.get("author_name"),
                content=db_post.get("content", ""),
                media_type=db_post.get("media_type", "none"),
                source_json=db_post.get("source_json"),
            )
            media_save_dir = Path(STATE_DIR) / "pending_media"
            media_save_dir.mkdir(parents=True, exist_ok=True)
            ok_m, media_files_db, _ = media_mgr.prepare_post_media(source_rec, media_save_dir)

            pending_data = {
                "is_repurpose": True,
                "database_id": db_post.get("id"),
                "source_post_id": db_post.get("source_post_id"),
                "text": post_text_db,
                "first_comment_cta": first_comment_cta_db,
                "media_type": db_post.get("media_type", "none"),
                "media_files": [str(p) for p in media_files_db] if ok_m else [],
                "source_url": db_post.get("source_url"),
                "author_name": db_post.get("author_name"),
                "execution_id": db_post.get("reserved_by"),
            }

    if not action:
        if not pending_data:
            logger.info("No pending post. Exiting.")
            sys.exit(0)
        else:
            logger.info("Pending post draft exists. Waiting for user decision via Cloudflare Worker relay.")
            sys.exit(0)

    if not pending_data:
        if action in ("reject_regen", "reject_all", "regen_text"):
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(bot_token, chat_id, msg_id, "🔄 <b>Draft Rejected — Generating Next Post...</b>")
            send_telegram_message(bot_token, chat_id, "🔄 <b>Generating a brand new post draft now...</b>")
            trigger_repurpose_workflow()
            sys.exit(0)
        elif action in ("reject", "reject_only"):
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(bot_token, chat_id, msg_id, "❌ <b>Draft Rejected & Discarded</b>")
            send_telegram_message(bot_token, chat_id, "🗑️ <b>Draft Rejected.</b> No new post will be generated.")
            sys.exit(0)
        else:
            if msg_id:
                edit_telegram_message(
                    bot_token,
                    chat_id,
                    msg_id,
                    "⚠️ <i>This post draft was already processed or is no longer pending.</i>",
                )
            sys.exit(0)

    is_repurpose = bool(pending_data.get("is_repurpose"))
    post_text = pending_data.get("text", "")
    if not msg_id:
        msg_id = pending_data.get("message_id")

    # ── Handling Repurposed Source Post Drafts ──
    if is_repurpose:
        from pathlib import Path

        from job_radar.repurpose.models import ProcessingStatus
        from job_radar.repurpose.publisher import LinkedInRepurposePublisher
        from job_radar.storage.supabase_client import SupabaseStorageClient

        db_id = pending_data.get("database_id")
        source_post_id = pending_data.get("source_post_id")
        media_type = pending_data.get("media_type", "none")
        media_file_paths = [Path(p) for p in pending_data.get("media_files", []) if os.path.exists(p)]
        execution_id = pending_data.get("execution_id")

        supabase = SupabaseStorageClient()

        if action in ("approve", "approve_all", "accept"):
            logger.info("Publishing repurposed post %s to LinkedIn...", source_post_id)
            first_comment = pending_data.get("first_comment_cta")
            publisher = LinkedInRepurposePublisher()
            pub_ok, status_code, post_urn, res_text, post_url = publisher.publish_post(
                text=post_text,
                media_files=media_file_paths,
                media_type=media_type,
                first_comment=first_comment,
                dry_run=False,
            )

            if pub_ok:
                cleanup_state_files()
                if db_id:
                    supabase.update_post_status(
                        post_id=db_id,
                        status=ProcessingStatus.PUBLISHED.value,
                        execution_id=execution_id,
                        published_linkedin_post_id=post_urn,
                        published_linkedin_url=post_url,
                        published_at="now()",
                        final_content=post_text,
                    )
                if msg_id:
                    edit_telegram_message(
                        bot_token, chat_id, msg_id, f"✅ <b>Posted to LinkedIn</b>\n\n{html.escape(post_text)}"
                    )
                followup_text = f"🎉 <b>Repurposed Post Published Successfully!</b>\n\n<b>Source ID:</b> <code>{html.escape(str(source_post_id))}</code>\n<b>Post URN:</b> <code>{html.escape(str(post_urn))}</code>"
                if post_url:
                    followup_text += f"\n<b>Link:</b> {post_url}"
                send_telegram_message(bot_token, chat_id, followup_text)
            else:
                cleanup_state_files()
                if db_id:
                    supabase.update_post_status(
                        post_id=db_id,
                        status=ProcessingStatus.FAILED.value,
                        execution_id=execution_id,
                        last_error=f"LinkedIn publish error ({status_code}): {res_text}",
                    )
                if msg_id:
                    edit_telegram_message(
                        bot_token,
                        chat_id,
                        msg_id,
                        f"⚠️ <b>LinkedIn Publication Failed (HTTP {status_code})</b>\n\nDraft discarded.",
                    )
                alert_text = (
                    f"⚠️ <b>LinkedIn Posting Failed (HTTP {status_code})</b>\n\n<code>{html.escape(res_text)}</code>"
                )
                send_telegram_message(bot_token, chat_id, alert_text)

        elif action in ("reject", "reject_only"):
            cleanup_state_files()
            if db_id:
                supabase.update_post_status(
                    post_id=db_id,
                    status=ProcessingStatus.REJECTED.value,
                    execution_id=execution_id,
                    skipped_reason="Rejected by user via Telegram",
                )
            if msg_id:
                edit_telegram_message(
                    bot_token,
                    chat_id,
                    msg_id,
                    f"❌ <b>Draft Rejected & Discarded</b>\n\n<s>{html.escape(post_text)}</s>",
                )
            send_telegram_message(
                bot_token,
                chat_id,
                "🗑️ <b>Draft Rejected.</b> This post has been marked as rejected and will not be suggested again.",
            )

        elif action in ("reject_regen", "reject_all"):
            cleanup_state_files()
            if db_id:
                # Reset back to available so it is NOT flagged as rejected
                supabase.update_post_status(
                    post_id=db_id,
                    status=ProcessingStatus.AVAILABLE.value,
                    execution_id=None,
                    reserved_by=None,
                    reserved_at=None,
                    skipped_reason=None,
                )
            if msg_id:
                edit_telegram_message(
                    bot_token,
                    chat_id,
                    msg_id,
                    f"🔄 <b>Draft Rejected — Generating Next Post...</b>\n\n<s>{html.escape(post_text)}</s>",
                )
            send_telegram_message(bot_token, chat_id, "🗑️ <b>Selecting and preparing the next source post now...</b>")
            trigger_repurpose_workflow()

        return

    # ── Handling Legacy Generated Post Drafts ──
    cover_bytes = None
    if os.path.exists(COVER_FILE):
        try:
            with open(COVER_FILE, "rb") as f:
                cover_bytes = f.read()
        except Exception:
            pass

    if action in ("approve", "approve_all", "accept"):
        success, status_code, post_urn, res_text = publish_to_linkedin(
            linkedin_access_token, linkedin_person_urn, post_text, cover_bytes
        )
        if success:
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id, f"✅ <b>Posted to LinkedIn</b>\n\n{html.escape(post_text)}"
                )
            post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
            followup_text = f"🎉 <b>LinkedIn Post Published Successfully!</b>\n\n<b>Post URN:</b> <code>{html.escape(post_urn)}</code>"
            if post_url:
                followup_text += f"\n<b>Link:</b> {post_url}"
            send_telegram_message(bot_token, chat_id, followup_text)
        else:
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(
                    bot_token,
                    chat_id,
                    msg_id,
                    f"⚠️ <b>LinkedIn Publication Failed (HTTP {status_code})</b>\n\nDraft discarded. Re-triggering new post generation...",
                )
            alert_text = (
                f"⚠️ <b>LinkedIn Posting Failed (HTTP {status_code})</b>\n\n"
                f"<b>Response:</b> <code>{html.escape(res_text)}</code>\n\n"
                f"<i>The failed draft has been discarded and a new post generation workflow has been triggered automatically.</i>"
            )
            send_telegram_message(bot_token, chat_id, alert_text)
            trigger_generate_workflow()

    elif action in ("reject", "reject_only"):
        cleanup_state_files()
        if msg_id:
            edit_telegram_message(
                bot_token, chat_id, msg_id, f"❌ <b>Draft Rejected & Discarded</b>\n\n<s>{html.escape(post_text)}</s>"
            )
        send_telegram_message(bot_token, chat_id, "🗑️ <b>Draft Rejected.</b> No new post will be generated.")

    elif action in ("reject_regen", "reject_all"):
        cleanup_state_files()
        if msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🔄 <b>Draft Rejected — Generating New Draft...</b>\n\n<s>{html.escape(post_text)}</s>",
            )
        send_telegram_message(
            bot_token, chat_id, "🗑️ <b>Draft Rejected & Discarded.</b> Generating a brand new post draft now..."
        )
        trigger_generate_workflow()

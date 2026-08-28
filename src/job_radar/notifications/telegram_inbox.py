"""
src/job_radar/notifications/telegram_inbox.py

Sends interactive Job OS opportunity cards to Telegram with inline action buttons
(Tailor, Mark Applying, Skip) and handles interactive callback query updates to the CRM.
"""
from __future__ import annotations

import html
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
import requests

from job_radar.crm.db import get_job_by_id, update_job_status, upsert_crm_job
from job_radar.crm.models import JobStatus

logger = logging.getLogger(__name__)


def send_telegram_job_card(
    job: Dict[str, Any],
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """Send an interactive job card to Telegram with inline callback buttons."""
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        logger.debug("Telegram credentials not configured. Skipping Telegram notification.")
        return False

    # Ensure job is stored in CRM to obtain an ID
    crm_job = upsert_crm_job(job)
    job_id = crm_job.id or 0

    company = html.escape(str(job.get("company", "Unknown Company")))
    title = html.escape(str(job.get("title", "Software Engineer")))
    location = html.escape(str(job.get("location", "Remote")))
    v_conf = html.escape(str(job.get("visa_confidence", "unknown")).upper())
    score = f"{job.get('composite', 0.0):.1f}"
    ats = str(job.get("ats_score", "—"))
    url = job.get("url", "#")
    snippet = html.escape(str(job.get("snippet", ""))[:200])

    text = (
        f"🎯 <b>{company}</b> — <b>{title}</b>\n\n"
        f"📍 <b>Location:</b> {location}\n"
        f"🛡️ <b>Visa Confidence:</b> <code>{v_conf}</code>\n"
        f"📊 <b>Composite Score:</b> <b>{score}/100</b> (ATS: {ats})\n\n"
        f"<i>{snippet}...</i>\n\n"
        f"🔗 <a href=\"{url}\">Open Job Posting</a>"
    )

    inline_keyboard = [
        [
            {"text": "📝 Tailor Resume", "callback_data": f"job:tailor:{job_id}"},
            {"text": "🚀 Mark Applying", "callback_data": f"job:apply:{job_id}"},
            {"text": "❌ Skip", "callback_data": f"job:skip:{job_id}"},
        ]
    ]

    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error("Failed to send Telegram job card: %s", e)
        return False


def handle_telegram_job_callback(
    callback_data: str,
    callback_query_id: str,
    bot_token: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Handles callbacks from Telegram:
      - job:tailor:<id> -> moves to 'applying', prompts tailor
      - job:apply:<id> -> moves to 'applied'
      - job:skip:<id> -> moves to 'skipped'
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != "job":
        return False, "Unknown callback format"

    action = parts[1]
    job_id_str = parts[2]
    if not job_id_str.isdigit():
        return False, "Invalid job ID"

    job_id = int(job_id_str)

    msg = ""
    if action == "tailor":
        update_job_status(job_id, JobStatus.APPLYING, notes="Tailor requested via Telegram")
        msg = f"✅ Job #{job_id} set to APPLYING. Resume generation queued."
    elif action == "apply":
        update_job_status(job_id, JobStatus.APPLIED, notes="Applied via Telegram")
        msg = f"🚀 Job #{job_id} marked as APPLIED. Follow-up reminder scheduled in 3 days."
    elif action == "skip":
        update_job_status(job_id, JobStatus.SKIPPED, notes="Skipped via Telegram")
        msg = f"❌ Job #{job_id} SKIPPED."
    else:
        msg = "Unrecognized action."

    if token and callback_query_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": msg},
                timeout=10,
            )
        except Exception:
            pass

    return True, msg

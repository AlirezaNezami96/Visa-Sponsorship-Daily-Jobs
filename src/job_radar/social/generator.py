"""LinkedIn Post Generator powered by Gemini 3.6 Flash and Telegram drafts."""
from __future__ import annotations

import html
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from typing import Tuple
import requests

from job_radar.social.images import create_professional_cover_image

logger = logging.getLogger(__name__)

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")


def ensure_telegram_webhook(bot_token: str) -> None:
    worker_url = os.environ.get("WORKER_URL", "https://telegram-relay.linkedindailyposts.workers.dev")
    secret_token = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "my_webhook_secret_99")
    try:
        info_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        res = requests.get(info_url, timeout=10)
        if res.status_code == 200:
            current_url = res.json().get("result", {}).get("url", "")
            if current_url == worker_url:
                return

        set_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        payload = {
            "url": worker_url,
            "secret_token": secret_token,
            "allowed_updates": ["callback_query"]
        }
        requests.post(set_url, json=payload, timeout=10)
    except Exception as e:
        logger.warning("Error ensuring Telegram webhook: %s", e)


def send_telegram_alert(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        res.raise_for_status()
    except Exception as e:
        logger.error("Failed to send Telegram alert: %s", e)


def call_gemini_text_api(api_key: str) -> Tuple[str, str, str, str]:
    system_prompt = """# SYSTEM ROLE: Viral AI & Productivity Creator

You are a top LinkedIn creator who shares dead-simple, practical AI tips, tools, and news. 
Your audience consists of everyday professionals, marketers, founders, and knowledge workers—NOT hard-core engineers.

Your writing is:
- **Ultra-simple:** 6th-grade reading level. Zero jargon.
- **Practical:** Focuses 100% on "How this saves you time/money today" or "How to use this right now".
- **Short & Viral:** Built for fast mobile reading with strong hooks (70 to 110 words total).

# OUTPUT FORMAT
Return your response in exact JSON format:
{
  "post_text": "<The complete finished LinkedIn post text>",
  "image_title": "<SHORT BOLD TITLE (2-4 WORDS MAXIMUM)>",
  "category": "<AI TOOLS / PRODUCTIVITY>",
  "bg_prompt": "<1-sentence visual description for a minimalist background image>"
}"""

    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    random_seed = random.randint(1000, 999999)

    user_prompt = (
        f"Current UTC Timestamp: {date_str} (Random Seed: {random_seed})\n\n"
        "Pick ONE random topic from the TOPIC SELECTION pool (Free Tool, 2-Minute Hack, Everyday App AI Update, Time-Saver Workflow, AI News Made Simple, or Common Mistake & Fix).\n"
        "Write a super practical, ultra-simple, viral LinkedIn post.\n\n"
        "Return ONLY valid JSON."
    )

    last_error = ""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        full_input = f"{system_prompt}\n\n---\n\n{user_prompt}"
        interaction = client.interactions.create(
            model="gemini-3.6-flash",
            input=full_input,
            response_mime_type="application/json"
        )
        raw_content = (interaction.output_text or "").strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        elif raw_content.startswith("```"):
            raw_content = raw_content.split("```", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw_content)
        p_text = parsed.get("post_text", "").strip()
        img_title = parsed.get("image_title", "AI PRODUCTIVITY").strip()
        cat = parsed.get("category", "AI TOOLS").strip()
        bg_p = parsed.get("bg_prompt", "minimalist productivity workplace illustration").strip()

        if p_text:
            return p_text, img_title, cat, bg_p
    except Exception as exc:
        last_error = str(exc)

    models = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 1.0
        }
    }

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    raw_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if raw_content.startswith("```json"):
                        raw_content = raw_content.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                    elif raw_content.startswith("```"):
                        raw_content = raw_content.split("```", 1)[1].rsplit("```", 1)[0].strip()

                    parsed = json.loads(raw_content)
                    p_text = parsed.get("post_text", "").strip()
                    img_title = parsed.get("image_title", "AI PRODUCTIVITY").strip()
                    cat = parsed.get("category", "AI TOOLS").strip()
                    bg_p = parsed.get("bg_prompt", "modern technology").strip()

                    if p_text:
                        return p_text, img_title, cat, bg_p
        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(f"All Gemini API text call attempts failed. Last error: {last_error}")


def send_telegram_draft(bot_token: str, chat_id: str, post_text: str, cover_bytes: bytes, img_source: str = "gemini") -> Tuple[Optional[int], int]:
    photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    photo_msg_id = None
    caption = "🖼️ <b>AI Generated LinkedIn Cover Illustration</b>"

    if cover_bytes and img_source != "disabled":
        try:
            files = {"photo": ("cover.jpg", cover_bytes, "image/jpeg")}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }
            p_res = requests.post(photo_url, data=data, files=files, timeout=25)
            if p_res.status_code == 200:
                photo_msg_id = p_res.json().get("result", {}).get("message_id")
        except Exception as e:
            logger.warning("Failed to send Telegram photo preview: %s", e)

    msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    formatted_text = (
        f"📝 <b>New LinkedIn Post Draft Pending Approval:</b>\n\n"
        f"{html.escape(post_text)}\n\n"
        f"<i>Please choose an action below:</i>"
    )
    msg_payload = {
        "chat_id": chat_id,
        "text": formatted_text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "✅ Accept", "callback_data": "approve"}],
                [
                    {"text": "❌ Reject", "callback_data": "reject"},
                    {"text": "🔄 Reject & Regenerate", "callback_data": "reject_regen"}
                ]
            ]
        }
    }
    m_res = requests.post(msg_url, json=msg_payload, timeout=20)
    m_res.raise_for_status()
    text_msg_id = m_res.json().get("result", {}).get("message_id")

    return photo_msg_id, text_msg_id


def generate_and_dispatch_post() -> None:
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    missing = []
    if not gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logger.error("Missing required environment variables: %s", ', '.join(missing))
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)
    ensure_telegram_webhook(bot_token)

    force_gen = os.environ.get("FORCE_GENERATE", "false").lower() in ("true", "1")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    is_manual_or_dispatch = event_name in ("workflow_dispatch", "repository_dispatch") or force_gen

    if os.path.exists(PENDING_FILE) and not is_manual_or_dispatch:
        logger.info("%s exists. Previous draft is still awaiting decision.", PENDING_FILE)
        send_telegram_alert(
            bot_token,
            chat_id,
            "⚠️ <b>LinkedIn Post Generation Skipped</b>\n\nA previous post draft is still awaiting your decision in Telegram!"
        )
        sys.exit(0)

    try:
        post_text, image_title, category, bg_prompt = call_gemini_text_api(gemini_api_key)

        if not post_text:
            raise ValueError("Gemini returned empty post content.")

        if len(post_text) > 3000:
            post_text = post_text[:2990] + "..."

        cover_bytes, img_source = create_professional_cover_image(image_title, category, bg_prompt)

        with open(COVER_FILE, "wb") as f:
            f.write(cover_bytes)

        now_iso = datetime.now(timezone.utc).isoformat()
        pending_data = {
            "text": post_text,
            "image_title": image_title,
            "category": category,
            "bg_prompt": bg_prompt,
            "cover_file": COVER_FILE,
            "image_source": img_source,
            "generated_at": now_iso
        }

        photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, post_text, cover_bytes, img_source=img_source)
        pending_data["photo_message_id"] = photo_msg_id
        pending_data["message_id"] = text_msg_id

        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        logger.info("Draft saved to %s (photo_msg_id=%s, text_msg_id=%s).", PENDING_FILE, photo_msg_id, text_msg_id)

    except Exception as err:
        error_msg = f"❌ <b>LinkedIn Post Generation Failed:</b>\n<code>{html.escape(str(err))}</code>"
        logger.error("Error generating post: %s", err)
        send_telegram_alert(bot_token, chat_id, error_msg)
        sys.exit(1)

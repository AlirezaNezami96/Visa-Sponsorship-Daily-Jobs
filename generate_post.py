import os
import sys
import json
import html
import requests
from datetime import datetime, timezone
import random
from image_utils import create_professional_cover_image

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")

def ensure_telegram_webhook(bot_token: str) -> None:
    """Ensures Telegram bot webhook is registered to point to the Cloudflare Worker relay."""
    worker_url = os.environ.get("WORKER_URL", "https://telegram-relay.linkedindailyposts.workers.dev")
    secret_token = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "my_webhook_secret_99")
    try:
        info_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        res = requests.get(info_url, timeout=10)
        if res.status_code == 200:
            current_url = res.json().get("result", {}).get("url", "")
            if current_url == worker_url:
                print(f"[INFO] Telegram webhook is already active: {current_url}")
                return

        set_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        payload = {
            "url": worker_url,
            "secret_token": secret_token,
            "allowed_updates": ["callback_query"]
        }
        set_res = requests.post(set_url, json=payload, timeout=10)
        if set_res.status_code == 200 and set_res.json().get("ok"):
            print(f"[SUCCESS] Registered Telegram webhook: {worker_url}")
        else:
            print(f"[WARN] Failed to set Telegram webhook: {set_res.text}")
    except Exception as e:
        print(f"[WARN] Error ensuring Telegram webhook: {e}")

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
        print(f"[ERROR] Failed to send Telegram alert: {e}")

def call_gemini_text_api(api_key: str) -> tuple[str, str, str, str]:
    """Generates (post_text, image_title, category, bg_prompt) using Gemini API."""
    models = ["gemini-flash-latest", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-pro-latest", "gemini-2.0-flash"]

    system_prompt = """# SYSTEM ROLE: Elite LinkedIn Tech Ghostwriter & Developer Brand Strategist
You are a world-class social media strategist and technical ghostwriter specializing in organic LinkedIn reach for senior engineers and AI builders. Your sole mission is to transform raw technical news, developer logs, and project notes into natural, high-signal LinkedIn posts that drive high dwell time, profile views, and inbound opportunities from top tech recruiters and founders.

# CORE OBJECTIVE & POST DYNAMICS
- Author Persona: Alireza Nezami — Senior Mobile Application Engineer (Android Native / Flutter) and On-Device AI Specialist.
- Target Audience: Tech recruiters, CTOs, engineering managers, and fellow senior developers.
- Post Goal: Position the author as an authentic Top Voice in Mobile Engineering and AI by delivering immediate value, sharp insights, and genuine enthusiasm.
- Target Length: 130 to 190 words (Medium length. Never overly long; never shallow).
- Algorithm Alignment: Prioritize readability, mobile-first formatting, high dwell time, and "Save" potential. Never insert external URLs in the post body.

# WEEKLY CONTENT CALENDAR MATRIX
Automatically apply the designated theme based on the current day of the week:
- SATURDAY [Mobile Engineering Expert]: High-level mobile architecture, state management, UI performance, native OS internals, or system-level trade-offs (Android/Flutter/iOS).
- SUNDAY [Trending AI Tool Showcase]: Quick, enthusiastic highlight of a newly discovered AI utility, framework, or developer tool and why it’s useful.
- MONDAY [Hands-on AI Experiment]: Relatable, practical recap of a personal experiment with an AI tool or model (e.g., "I tested X to solve Y, here’s what happened").
- TUESDAY [Latest AI Tech News]: Energetic reaction and architectural breakdown of a major AI release, research paper, or open-source weights drop.
- WEDNESDAY [On-Device AI & Edge ML]: The intersection of mobile and AI (ExecuTorch, CoreML, Gemini Nano, local LLMs, quantization, offline inference).
- THURSDAY [AI Developer Workflow]: Practical ways AI coding assistants (Cursor, Copilot, Claude) are changing daily development workflows and code quality.
- FRIDAY [Hot Take & Engineering Trade-offs]: Pragmatic, slightly provocative opinion or counter-intuitive lesson learned on software craftsmanship, tooling, or tech hype.

# VOICE, TONE & ANTI-AI GUARDRAILS
- Tone Persona: An energetic, practical engineer sharing something cool with peers over coffee. Curious, direct, enthusiastic, and grounded.
- Formatting Integrity: 
  - Short, breathable blocks (1–3 lines per paragraph max).
  - Maximum 0 to 1 emoji for the entire post. 
  - STRICTLY NO emoji bullet lists (never use ⚡, 🛠️, 📌, 💡, 🚀 as structural points).
- STRICT BANNED AI SLOP WORDS:
  Never use: "In today's fast-paced digital landscape", "In today's digital landscape", "Game-changer", "Game-changing", "Delve", "Supercharge", "Revolutionary", "Unlocking potential", "Mastering", "Let's dive in", "I am thrilled to announce", "Paradigm shift", "Beacon", "Testament", "Humbled", "Crucial", "Fascinating", "it's not just X, it's Y", "the future of X is here".

# POST ARCHITECTURE SPECIFICATION
Every draft must follow this 4-step structural flow:
1. THE HOOK (Line 1–2): A natural, intriguing observation, discovery, or energetic reaction. No aggressive clickbait ("99% of devs fail"), no boring announcements.
2. THE CONTEXT (Line 3–5): Plain-language explanation of what changed, what was discovered, or how the tool/concept works.
3. THE VALUE / INSIGHT (Line 6–8): Why this matters to real-world software engineering or product architecture.
4. THE ENGAGEMENT CLOSER (Final Line): A simple, authentic open-ended question that invites genuine discussion in the comment section.

# ALGORITHM SAFEGUARDS
- Never put external URLs inside the main post body. Add a placeholder line: "(Link in the first comment)".
- Keep line lengths short for mobile readability.
- Frame content so it is worth *saving* for reference.
- No code, ever. No snippets, no pseudocode, no config blocks. Describe mechanisms in plain language.
- Never fabricate specifics (no fake stats, benchmark numbers, or fake star counts).

# OUTPUT FORMAT
Return your response in exact JSON format with four fields:
{
  "post_text": "<The complete finished LinkedIn post text following all instructions above>",
  "image_title": "<SHORT BOLD TITLE (2-5 WORDS MAXIMUM)>",
  "category": "<SOFTWARE ENGINEERING>",
  "bg_prompt": "<Main post topic sentence describing the core concept>"
}"""

    now_utc = datetime.now(timezone.utc)
    day_name = now_utc.strftime("%A")
    date_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    random_seed = random.randint(1000, 999999)

    user_prompt = (
        f"Current UTC Timestamp: {date_str} (Random Seed: {random_seed})\n"
        f"Today is {day_name}.\n\n"
        f"You must strictly generate today's post matching the {day_name.upper()} theme from the Weekly Content Calendar Matrix.\n"
        f"Pick a fresh, unique, highly specific technical topic for {day_name}. "
        f"Do NOT repeat past generic topics. Focus purely on the {day_name.upper()} matrix theme.\n\n"
        "Return ONLY valid JSON."
    )

    last_error = None
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.85
        }
    }

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            print(f"[INFO] Calling Gemini Text API model={model}...")
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
                    img_title = parsed.get("image_title", "MOBILE AI UPDATE").strip()
                    cat = parsed.get("category", "SOFTWARE ENGINEERING").strip()
                    bg_p = parsed.get("bg_prompt", "modern mobile technology").strip()

                    if p_text:
                        return p_text, img_title, cat, bg_p
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                print(f"[WARN] Model {model} returned {last_error}")
        except Exception as exc:
            last_error = str(exc)
            print(f"[WARN] Error calling {model}: {exc}")

    raise RuntimeError(f"All Gemini API text call attempts failed. Last error: {last_error}")

def send_telegram_draft(bot_token: str, chat_id: str, post_text: str, cover_bytes: bytes, img_source: str = "gemini") -> tuple[int, int]:
    # 1. Send Photo preview
    photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    photo_msg_id = None
    if img_source == "gemini":
        caption = "🖼️ <b>AI Generated LinkedIn Cover Illustration (Gemini 2.5)</b>"
    elif img_source in ("pollinations", "pollinations_flux"):
        caption = "🖼️ <b>AI Generated LinkedIn Cover Illustration (Pollinations.ai)</b>"
    else:
        caption = "⚠️ <b>AI image generation failed — showing fallback design</b>"
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
            print(f"[WARN] Failed to send Telegram photo preview: {e}")

    # 2. Send Text message with 4 buttons
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
                [
                    {"text": "✅ Accept", "callback_data": "approve"}
                ],
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

def main():
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
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)
    ensure_telegram_webhook(bot_token)

    force_gen = os.environ.get("FORCE_GENERATE", "false").lower() in ("true", "1")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    is_manual_or_dispatch = event_name in ("workflow_dispatch", "repository_dispatch") or force_gen

    if os.path.exists(PENDING_FILE) and not is_manual_or_dispatch:
        print(f"[INFO] {PENDING_FILE} exists. Previous draft is still awaiting decision.")
        send_telegram_alert(
            bot_token,
            chat_id,
            "⚠️ <b>LinkedIn Post Generation Skipped</b>\n\nA previous post draft is still awaiting your decision in Telegram!"
        )
        sys.exit(0)

    try:
        print("[INFO] Generating post text and cover headlines via Gemini API...")
        post_text, image_title, category, bg_prompt = call_gemini_text_api(gemini_api_key)

        if not post_text:
            raise ValueError("Gemini returned empty post content.")

        if len(post_text) > 3000:
            print(f"[WARN] Post text length ({len(post_text)}) exceeds 3000 chars limit. Truncating...")
            post_text = post_text[:2990] + "..."

        print(f"[INFO] Rendering professional cover image title='{image_title}' category='{category}'...")
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
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, post_text, cover_bytes, img_source=img_source)
        pending_data["photo_message_id"] = photo_msg_id
        pending_data["message_id"] = text_msg_id

        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        print(f"[SUCCESS] Draft saved to {PENDING_FILE}. Telegram photo_msg_id={photo_msg_id}, text_msg_id={text_msg_id}.")

    except Exception as err:
        error_msg = f"❌ <b>LinkedIn Post Generation Failed:</b>\n<code>{html.escape(str(err))}</code>"
        print(f"[ERROR] {err}")
        send_telegram_alert(bot_token, chat_id, error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()

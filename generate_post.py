import os
import sys
import json
import html
import requests
from datetime import datetime, timezone
from image_utils import create_professional_cover_image

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")

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

    system_prompt = """# PERSONA & OBJECTIVE
You are ghostwriting the personal LinkedIn presence of Alireza Nezami — a Senior Mobile Application Engineer (Android Native / Flutter) and On-Device AI Specialist. Your goal is to draft daily high-signal LinkedIn posts that position him as a Top Voice in Mobile & On-Device AI, driving profile views from tech recruiters and engineering leaders.

# TARGET TOPIC PILLARS (ROTATE DAILY)
1. On-Device AI & Edge ML: Gemini Nano, ExecuTorch, CoreML, local LLMs, quantization, offline AI UI/UX.
2. Mobile Engineering & Performance: Jetpack Compose / Flutter optimization, memory management, IPC/Binder, state architecture (MVI/MVVM).
3. AI-Assisted Developer Workflows: How AI tools (Cursor, Claude, Copilot) are changing mobile software architecture and productivity.
4. Tech News & Hot Takes: Architectural breakdowns of recent announcements from Google I/O, Apple WWDC, OpenAI, or mobile-AI framework releases.
5. Real Engineering Trade-offs: Hard lessons, bug post-mortems, or counter-intuitive findings from mobile app development.

# TONE & VOICE RULES
- Speak like a pragmatist, senior staff engineer—not a marketing manager or influencer.
- High signal-to-noise ratio. Clear, sharp, zero fluff.
- BANNED WORDS & PHRASE LIST: "In today's digital landscape", "Game-changer", "Delve", "Thrilled to announce", "Humbled", "Revolutionary", "Mastering", "Supercharge", "Crucial", "Fascinating", "in today's fast-paced world", "let's dive in", "unlock the power of", "it's not just X, it's Y", "the future of X is here".
- Short sentences and punchy paragraphs (1-2 lines maximum per block).
- Plain text only. No markdown symbols (**, #, -, etc.) in the actual post text — LinkedIn doesn't render them and they'll show up as literal characters.

# FORMAT & EMOJI STRUCTURE (DESIGNED FOR DWELL TIME & SAVES)
- Hook (Lines 1-3): Must trigger curiosity or challenge a common assumption. Do NOT reveal everything before the "see more" line break. Must stand alone as a complete thought.
- Body: 
  - Use whitespace liberally.
  - Emojis MUST be used strictly as functional bullet points or structural anchors (Max 3-5 per post). Never use random inline emoji spam or stacked emojis.
  - Preferred functional emojis: 💡 (Key insight), ⚡ (Performance/Tech stack), 🛠️ (Tool/Architecture), ❌ vs ✅ (Comparison), 📌 (Takeaway).
- Structure Layout:
  [HOOK - Bold statement or counter-intuitive stat/insight]
  [LINE BREAK]
  [CONTEXT - The engineering problem or news background]
  [LINE BREAK]
  [TECHNICAL BREAKDOWN OR MEAT OF THE POST - 3 to 4 functional bullet points using functional emojis]
  [LINE BREAK]
  [PRACTICAL TAKEAWAY / SAVEABLE CHEAT SHEET]
  [LINE BREAK]
  [HIGH-ENGAGEMENT QUESTION - Ask a technical/opinion-based question to prompt developer discussion]
  [LINE BREAK]
  [3-4 NICHE HASHTAGS on their own line at the very end e.g. #OnDeviceAI #AndroidDev #MobileAI]

# ALGORITHM SAFEGUARDS
- Never put external URLs inside the main post body. Add a placeholder line: "(Link in the first comment)".
- Keep line lengths short for mobile readability.
- Frame content so it is worth *saving* for reference.
- Target roughly 1,300–1,900 characters total (about 200–300 words).
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

    user_prompt = (
        "Write a fresh, high-signal, engaging, and authentic LinkedIn post following all instructions in your system prompt. "
        "Also craft a short bold image_title (2 to 5 words MAXIMUM), a category name, and a one-sentence bg_prompt describing the post topic concept. "
        "Return ONLY valid JSON."
    )

    last_error = None
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7
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
                    {"text": "✅ Accept Both", "callback_data": "approve_all"},
                    {"text": "❌ Reject Both", "callback_data": "reject_all"}
                ],
                [
                    {"text": "📝 Accept Text & New Image", "callback_data": "regen_image"},
                    {"text": "🖼️ Accept Image & New Text", "callback_data": "regen_text"}
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

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

def call_zai_api(api_key: str) -> tuple[str, str, str, str]:
    """Generates (post_text, image_title, category, bg_prompt) from Z.ai API."""
    endpoints = [
        "https://api.z.ai/api/paas/v4/chat/completions",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    ]
    models = ["glm-4-flash", "glm-4.7-flash", "glm-4"]

    system_prompt = """You are a LinkedIn content strategist who covers AI in mobile development — specifically new AI capabilities, features, and industry news in Android and iOS. You write for developers and tech professionals who scroll LinkedIn during work hours.

TOPIC SCOPE
Write about one specific, recent, concrete thing: a new AI feature Google or Apple shipped, an AI-powered SDK/API update for Android or iOS, an industry trend (on-device AI, AI-assisted development tools, AI in app stores), or a notable announcement. Pick ONE angle per post — don't try to cover everything.

HARD RULES
- No code. No code blocks, no function names, no syntax.
- No mention of image or video attachments — text only.
- Never invent facts, statistics, or company statements.
- Maximum 2,200 characters.

OUTPUT FORMAT:
Return your response in exact JSON format with four fields:
{
  "post_text": "...",
  "image_title": "SHORT BOLD HEADLINE (3 TO 6 WORDS)",
  "category": "MOBILE AI NEWS",
  "bg_prompt": "simple modern smartphone on clean desk"
}"""

    user_prompt = (
        "Write a fresh, engaging, and high-impact LinkedIn post about a recent AI feature, capability, SDK update, "
        "or industry trend in Android or iOS mobile development following all instructions in your system prompt. "
        "Also craft an eye-catching 3-6 word image_title for the cover card, a short category name, and a simple minimal bg_prompt. "
        "Return ONLY valid JSON."
    )

    last_error = None

    for endpoint in endpoints:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        for model in models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7
            }
            try:
                print(f"[INFO] Calling Z.ai API endpoint={endpoint} model={model}...")
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        raw_content = choices[0].get("message", {}).get("content", "").strip()
                        if raw_content.startswith("```json"):
                            raw_content = raw_content.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                        elif raw_content.startswith("```"):
                            raw_content = raw_content.split("```", 1)[1].rsplit("```", 1)[0].strip()

                        parsed = json.loads(raw_content)
                        p_text = parsed.get("post_text", "").strip()
                        img_title = parsed.get("image_title", "MOBILE AI UPDATE").strip()
                        cat = parsed.get("category", "MOBILE AI TRENDS").strip()
                        bg_p = parsed.get("bg_prompt", "modern mobile technology").strip()

                        if p_text:
                            return p_text, img_title, cat, bg_p
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    print(f"[WARN] Model {model} on {endpoint} returned {last_error}")
            except Exception as exc:
                last_error = str(exc)
                print(f"[WARN] Error calling {model} on {endpoint}: {exc}")

    raise RuntimeError(f"All Z.ai API call attempts failed. Last error: {last_error}")

def send_telegram_draft(bot_token: str, chat_id: str, post_text: str, cover_bytes: bytes) -> tuple[int, int]:
    # 1. Send Photo preview
    photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    photo_msg_id = None
    try:
        files = {"photo": ("cover.jpg", cover_bytes, "image/jpeg")}
        data = {
            "chat_id": chat_id,
            "caption": "🖼️ <b>AI Generated Cover Image (Headline Overlay)</b>",
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
    zai_api_key = os.environ.get("ZAI_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    missing = []
    if not zai_api_key:
        missing.append("ZAI_API_KEY")
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)

    if os.path.exists(PENDING_FILE):
        print(f"[INFO] {PENDING_FILE} exists. Previous draft is still awaiting decision.")
        send_telegram_alert(
            bot_token,
            chat_id,
            "⚠️ <b>LinkedIn Post Generation Skipped</b>\n\nA previous post draft is still awaiting your decision in Telegram!"
        )
        sys.exit(0)

    try:
        print("[INFO] Generating post text and cover headlines via Z.ai...")
        post_text, image_title, category, bg_prompt = call_zai_api(zai_api_key)

        if not post_text:
            raise ValueError("LLM returned empty post content.")

        if len(post_text) > 3000:
            print(f"[WARN] Post text length ({len(post_text)}) exceeds 3000 chars limit. Truncating...")
            post_text = post_text[:2990] + "..."

        print(f"[INFO] Rendering professional cover image title='{image_title}' category='{category}'...")
        cover_bytes = create_professional_cover_image(image_title, category, bg_prompt)

        with open(COVER_FILE, "wb") as f:
            f.write(cover_bytes)

        now_iso = datetime.now(timezone.utc).isoformat()
        pending_data = {
            "text": post_text,
            "image_title": image_title,
            "category": category,
            "bg_prompt": bg_prompt,
            "cover_file": COVER_FILE,
            "generated_at": now_iso
        }
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, post_text, cover_bytes)
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

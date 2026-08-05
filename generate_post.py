import os
import sys
import json
import html
import requests
from datetime import datetime, timezone

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")

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

def call_zai_api(api_key: str) -> str:
    endpoints = [
        "https://api.z.ai/api/paas/v4/chat/completions",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    ]
    models = ["glm-4-flash", "glm-4.7-flash", "glm-4"]

    system_prompt = """You are a LinkedIn content strategist who covers AI in mobile development — specifically new AI capabilities, features, and industry news in Android and iOS. You write for developers and tech professionals who scroll LinkedIn during work hours.

TOPIC SCOPE
Write about one specific, recent, concrete thing: a new AI feature Google or Apple shipped, an AI-powered SDK/API update for Android or iOS, an industry trend (on-device AI, AI-assisted development tools, AI in app stores), or a notable announcement. Pick ONE angle per post — don't try to cover everything.

HARD RULES
- No code. No code blocks, no function names, no syntax, no "here's how to implement it." This is a news/trends post, not a tutorial.
- No mention of image or video attachments — text only.
- Never invent facts, statistics, or company statements. If you're not certain something is real and recent, write about the trend/theme in general terms instead of citing a specific fake event.
- Output ONLY the post text, ready to publish. No preamble, no "Here's your post:", no explanation.
- Maximum 2,200 characters (LinkedIn's hard cap is 3,000 — stay well under it).

STRUCTURE
1. Hook — first line must work standalone, since LinkedIn truncates to ~210 characters before "see more." Lead with a bold claim, a surprising number, or a direct question. No throat-clearing.
2. Body — 3-6 short paragraphs or a scannable list, one idea per line, generous line breaks (LinkedIn has no real formatting, so whitespace does the work). Write like you're texting a smart colleague, not writing a press release.
3. Close with one question or opinion prompt to invite comments — engagement bait that's actually relevant, not generic ("Thoughts?" alone is weak — ask something specific).
4. End with 3-5 relevant, specific hashtags (e.g. #AndroidDev #AI #MobileAI #iOSDev — not generic ones like #tech #innovation).

STYLE
- Emojis: use them purposefully as visual anchors (start of key lines, section breaks) — not one per sentence. 5-10 total is plenty. Never use emojis to replace words.
- Confident, opinionated, slightly informal — this is a person's voice, not corporate marketing copy.
- Short sentences. Fragments are fine. Avoid jargon walls — assume a smart but time-pressed reader.
- No hashtag stuffing, no "like and share," no engagement-pod language."""

    user_prompt = (
        "Write a fresh, engaging, and high-impact LinkedIn post about a recent AI feature, capability, SDK update, "
        "or industry trend in Android or iOS mobile development following all instructions in your system prompt. "
        "Output ONLY the final raw LinkedIn post text ready to publish."
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
                        content = choices[0].get("message", {}).get("content", "").strip()
                        if content:
                            return content
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    print(f"[WARN] Model {model} on {endpoint} returned {last_error}")
            except Exception as exc:
                last_error = str(exc)
                print(f"[WARN] Error calling {model} on {endpoint}: {exc}")

    raise RuntimeError(f"All Z.ai API call attempts failed. Last error: {last_error}")

def send_telegram_approval_prompt(bot_token: str, chat_id: str, post_text: str) -> int:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    formatted_text = f"📝 <b>New LinkedIn Post Draft Pending Approval:</b>\n\n{html.escape(post_text)}\n\n<i>Please approve or reject below:</i>"
    payload = {
        "chat_id": chat_id,
        "text": formatted_text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Approve & Post", "callback_data": "approve"},
                    {"text": "Reject", "callback_data": "reject"}
                ]
            ]
        }
    }
    resp = requests.post(url, json=payload, timeout=20)
    resp.raise_for_status()
    res_data = resp.json()
    msg_id = res_data.get("result", {}).get("message_id")
    if not msg_id:
        raise ValueError(f"No message_id in Telegram response: {res_data}")
    return msg_id

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

    # 1. Check if pending post already exists
    if os.path.exists(PENDING_FILE):
        print(f"[INFO] {PENDING_FILE} exists. Previous draft is still awaiting decision.")
        send_telegram_alert(
            bot_token,
            chat_id,
            "⚠️ <b>LinkedIn Post Generation Skipped</b>\n\nA previous post draft is still awaiting your approval in Telegram! Please approve or reject it before generating a new post."
        )
        sys.exit(0)

    try:
        # 2. Call Z.ai chat completions API
        post_text = call_zai_api(zai_api_key)

        # 3. Validate result (non-empty & <= 3000 chars)
        if not post_text:
            raise ValueError("LLM returned empty post content.")

        if len(post_text) > 3000:
            print(f"[WARN] Post text length ({len(post_text)}) exceeds 3000 chars limit. Truncating...")
            post_text = post_text[:2990] + "..."

        # 4. Write initial state/pending_post.json
        now_iso = datetime.now(timezone.utc).isoformat()
        pending_data = {
            "text": post_text,
            "generated_at": now_iso
        }
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        # 5 & 6. Send to Telegram & obtain message_id
        msg_id = send_telegram_approval_prompt(bot_token, chat_id, post_text)
        pending_data["message_id"] = msg_id

        # Update state/pending_post.json with message_id
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        print(f"[SUCCESS] Draft post saved to {PENDING_FILE} and Telegram message_id={msg_id} sent.")

    except Exception as err:
        error_msg = f"❌ <b>LinkedIn Post Generation Failed:</b>\n<code>{html.escape(str(err))}</code>"
        print(f"[ERROR] {err}")
        send_telegram_alert(bot_token, chat_id, error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()

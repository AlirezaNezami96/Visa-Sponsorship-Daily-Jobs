import os
import sys
import json
import html
import requests
from datetime import datetime, timezone

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
LAST_UPDATE_FILE = os.path.join(STATE_DIR, "last_update_id.txt")

def answer_callback_query(bot_token: str, callback_query_id: str, text: str = "") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "text": text
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[WARN] Failed to answer callback query: {e}")

def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")

def edit_telegram_message(bot_token: str, chat_id: str, message_id: int, text: str, parse_mode: str = "HTML") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "reply_markup": {"inline_keyboard": []}
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Failed to edit Telegram message message_id={message_id}: {e}")

def publish_to_linkedin(access_token: str, person_urn: str, text: str) -> tuple[bool, int, str, str]:
    url = "https://api.linkedin.com/rest/posts"
    linkedin_version = datetime.now(timezone.utc).strftime("%Y%m")

    if not person_urn.startswith("urn:li:person:"):
        person_urn = f"urn:li:person:{person_urn}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": linkedin_version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }

    body = {
        "author": person_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED"
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

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

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    authorized_user_id = os.environ.get("TELEGRAM_AUTHORIZED_USER_ID")
    linkedin_access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_person_urn = os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:aAOQrAt7pG")

    missing = []
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")
    if not authorized_user_id:
        missing.append("TELEGRAM_AUTHORIZED_USER_ID")
    if not linkedin_access_token:
        missing.append("LINKEDIN_ACCESS_TOKEN")

    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)

    # 1. Determine offset from state/last_update_id.txt
    offset = 0
    if os.path.exists(LAST_UPDATE_FILE):
        try:
            with open(LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    offset = int(content) + 1
        except Exception as e:
            print(f"[WARN] Could not read {LAST_UPDATE_FILE}, defaulting offset to 0: {e}")

    # 2. Call getUpdates
    get_updates_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        res = requests.get(get_updates_url, params={"offset": offset, "timeout": 5}, timeout=15)
        res.raise_for_status()
        res_data = res.json()
    except Exception as e:
        print(f"[ERROR] Failed to fetch Telegram updates: {e}")
        send_telegram_message(bot_token, chat_id, f"❌ <b>LinkedIn Poll Failure:</b> Could not fetch Telegram updates.\n<code>{html.escape(str(e))}</code>")
        sys.exit(1)

    updates = res_data.get("result", [])
    if not updates:
        print("[INFO] No new Telegram updates found.")
        sys.exit(0)

    max_update_id = offset - 1 if offset > 0 else 0
    state_modified = False

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None and update_id > max_update_id:
            max_update_id = update_id

        if "callback_query" not in update:
            continue

        callback = update["callback_query"]
        callback_id = callback.get("id")
        from_user = callback.get("from", {})
        from_id = from_user.get("id")
        msg = callback.get("message", {})
        msg_id = msg.get("message_id")
        action = callback.get("data")

        # 3. Confirm callback_query.from.id matches authorized user ID
        if str(from_id) != str(authorized_user_id):
            print(f"[WARN] Received callback from unauthorized user_id={from_id}. Expected {authorized_user_id}. Ignoring.")
            continue

        # 4. Answer callback query immediately
        if callback_id:
            answer_callback_query(bot_token, callback_id)

        # 5. Check if state/pending_post.json exists
        if not os.path.exists(PENDING_FILE):
            print("[INFO] Stale callback received. pending_post.json does not exist.")
            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    "⚠️ <i>This post draft was already processed or is no longer pending.</i>"
                )
            state_modified = True
            continue

        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                pending_data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to read {PENDING_FILE}: {e}")
            continue

        post_text = pending_data.get("text", "")

        # 6. On Approve
        if action == "approve":
            print("[INFO] Approval received. Publishing post to LinkedIn...")
            success, status_code, post_urn, res_text = publish_to_linkedin(
                linkedin_access_token, linkedin_person_urn, post_text
            )

            if success:
                print(f"[SUCCESS] Post published to LinkedIn. URN: {post_urn}")
                # Delete state/pending_post.json
                if os.path.exists(PENDING_FILE):
                    os.remove(PENDING_FILE)
                state_modified = True

                # Edit Telegram message
                if msg_id:
                    edit_telegram_message(
                        bot_token, chat_id, msg_id,
                        f"✅ <b>Posted to LinkedIn</b>\n\n{html.escape(post_text)}"
                    )

                # Send follow-up
                post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
                followup_text = f"🎉 <b>LinkedIn Post Published Successfully!</b>\n\n<b>Post URN:</b> <code>{html.escape(post_urn)}</code>"
                if post_url:
                    followup_text += f"\n<b>Link:</b> {post_url}"
                send_telegram_message(bot_token, chat_id, followup_text)

            else:
                # On non-2xx: leave pending_post.json in place!
                print(f"[ERROR] LinkedIn publication failed with status {status_code}: {res_text}")
                if status_code == 401:
                    alert_text = (
                        "🚨 <b>LinkedIn Posting Failed (401 Unauthorized)</b>\n\n"
                        "Your <code>LINKEDIN_ACCESS_TOKEN</code> has expired or is invalid. "
                        "Tokens expire every 60 days. Please re-authenticate and update repository secrets.\n\n"
                        f"<b>Response:</b> <code>{html.escape(res_text)}</code>"
                    )
                else:
                    alert_text = (
                        f"⚠️ <b>LinkedIn Posting Failed (HTTP {status_code})</b>\n\n"
                        f"<b>Response:</b> <code>{html.escape(res_text)}</code>"
                    )
                send_telegram_message(bot_token, chat_id, alert_text)

        # 7. On Reject
        elif action == "reject":
            print("[INFO] Rejection received. Discarding draft...")
            if os.path.exists(PENDING_FILE):
                os.remove(PENDING_FILE)
            state_modified = True

            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    f"❌ <b>Discarded</b>\n\n<s>{html.escape(post_text)}</s>"
                )
            send_telegram_message(
                bot_token, chat_id,
                "🗑️ <b>Draft Rejected & Discarded.</b> A new post will be generated on the next daily schedule."
            )

    # 8. Update state/last_update_id.txt if updates were processed
    if max_update_id >= offset:
        with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
            f.write(str(max_update_id))
        state_modified = True

    if state_modified:
        print(f"[INFO] Pipeline state modified. Last update ID: {max_update_id}")
    else:
        print("[INFO] No state changes.")

if __name__ == "__main__":
    main()

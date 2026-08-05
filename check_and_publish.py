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
LAST_UPDATE_FILE = os.path.join(STATE_DIR, "last_update_id.txt")

def trigger_generate_workflow() -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("[WARN] GITHUB_REPOSITORY or GITHUB_TOKEN not set. Cannot auto-trigger generate.yml workflow.")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/generate.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {"ref": "main"}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code in (204, 201, 200):
            print(f"[INFO] Successfully triggered 'Generate LinkedIn Post' workflow on repo {repo}.")
            return True
        else:
            print(f"[WARN] Failed to trigger generate.yml (HTTP {res.status_code}): {res.text}")
            return False
    except Exception as e:
        print(f"[WARN] Exception while triggering generate.yml: {e}")
        return False

def answer_callback_query(bot_token: str, callback_query_id: str, text: str = "") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[WARN] Failed to answer callback query: {e}")

def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")

def edit_telegram_message(bot_token: str, chat_id: str, message_id: int, text: str, parse_mode: str = "HTML", keep_keyboard: bool = False) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if keep_keyboard:
        payload["reply_markup"] = {
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
    else:
        payload["reply_markup"] = {"inline_keyboard": []}

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Failed to edit Telegram message_id={message_id}: {e}")

def edit_telegram_photo(bot_token: str, chat_id: str, photo_message_id: int, cover_bytes: bytes) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/editMessageMedia"
    files = {"photo": ("cover.jpg", cover_bytes, "image/jpeg")}
    media_json = json.dumps({
        "type": "photo",
        "media": "attach://photo",
        "caption": "🖼️ <b>AI Generated Cover Image (Regenerated Headline)</b>",
        "parse_mode": "HTML"
    })
    data = {
        "chat_id": chat_id,
        "message_id": photo_message_id,
        "media": media_json
    }
    try:
        resp = requests.post(url, data=data, files=files, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Failed to edit Telegram photo message_id={photo_message_id}: {e}")

def upload_image_to_linkedin(access_token: str, person_urn: str, image_bytes: bytes) -> str:
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    linkedin_version = os.environ.get("LINKEDIN_API_VERSION", "202501")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": linkedin_version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }
    init_body = {"initializeUploadRequest": {"owner": person_urn}}
    try:
        init_res = requests.post(init_url, headers=headers, json=init_body, timeout=20)
        if init_res.status_code != 200:
            print(f"[WARN] Failed to initialize LinkedIn image upload (HTTP {init_res.status_code}): {init_res.text}")
            return ""

        val = init_res.json().get("value", {})
        upload_url = val.get("uploadUrl")
        image_urn = val.get("image")

        if not upload_url or not image_urn:
            print(f"[WARN] Missing uploadUrl or image URN in response: {init_res.json()}")
            return ""

        put_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/jpeg"
        }
        put_res = requests.put(upload_url, headers=put_headers, data=image_bytes, timeout=30)
        if 200 <= put_res.status_code < 300:
            print(f"[INFO] LinkedIn image binary upload successful. URN: {image_urn}")
            return image_urn
        else:
            print(f"[WARN] LinkedIn image PUT upload failed (HTTP {put_res.status_code}): {put_res.text}")
            return ""
    except Exception as e:
        print(f"[WARN] Exception during LinkedIn image upload: {e}")
        return ""

def publish_to_linkedin(access_token: str, person_urn: str, text: str, cover_bytes: bytes = None) -> tuple[bool, int, str, str]:
    url = "https://api.linkedin.com/rest/posts"
    linkedin_version = os.environ.get("LINKEDIN_API_VERSION", "202501")

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
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if cover_bytes and len(cover_bytes) > 1000:
        print("[INFO] Uploading cover image binary to LinkedIn...")
        image_urn = upload_image_to_linkedin(access_token, person_urn, cover_bytes)
        if image_urn:
            body["content"] = {
                "media": {
                    "id": image_urn,
                    "altText": "Mobile Development News Cover"
                }
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

def cleanup_state_files():
    for f in (PENDING_FILE, COVER_FILE):
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception as e:
                print(f"[WARN] Could not remove {f}: {e}")

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    authorized_user_id = os.environ.get("TELEGRAM_AUTHORIZED_USER_ID")
    linkedin_access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_person_urn = os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:aAOQrAt7pG")
    zai_api_key = os.environ.get("ZAI_API_KEY")

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

    offset = 0
    if os.path.exists(LAST_UPDATE_FILE):
        try:
            with open(LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    offset = int(content) + 1
        except Exception as e:
            print(f"[WARN] Could not read {LAST_UPDATE_FILE}, defaulting offset to 0: {e}")

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

        if str(from_id) != str(authorized_user_id):
            print(f"[WARN] Received callback from unauthorized user_id={from_id}. Expected {authorized_user_id}. Ignoring.")
            continue

        if not os.path.exists(PENDING_FILE):
            if callback_id:
                answer_callback_query(bot_token, callback_id, "Draft no longer pending.")
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
        image_title = pending_data.get("image_title", "MOBILE AI UPDATE")
        category = pending_data.get("category", "MOBILE AI NEWS")
        bg_prompt = pending_data.get("bg_prompt", "")
        photo_msg_id = pending_data.get("photo_message_id")

        cover_bytes = None
        if os.path.exists(COVER_FILE):
            try:
                with open(COVER_FILE, "rb") as f:
                    cover_bytes = f.read()
            except Exception as e:
                print(f"[WARN] Could not read {COVER_FILE}: {e}")

        # 1. Accept Both
        if action in ("approve_all", "approve"):
            if callback_id:
                answer_callback_query(bot_token, callback_id, "Publishing to LinkedIn...")
            print("[INFO] Approve All received. Publishing text and cover image to LinkedIn...")

            success, status_code, post_urn, res_text = publish_to_linkedin(
                linkedin_access_token, linkedin_person_urn, post_text, cover_bytes
            )

            if success:
                print(f"[SUCCESS] Post published to LinkedIn. URN: {post_urn}")
                cleanup_state_files()
                state_modified = True

                if msg_id:
                    edit_telegram_message(
                        bot_token, chat_id, msg_id,
                        f"✅ <b>Posted to LinkedIn (Text + Cover Image Card)</b>\n\n{html.escape(post_text)}"
                    )

                post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
                followup_text = f"🎉 <b>LinkedIn Post Published Successfully!</b>\n\n<b>Post URN:</b> <code>{html.escape(post_urn)}</code>"
                if post_url:
                    followup_text += f"\n<b>Link:</b> {post_url}"
                send_telegram_message(bot_token, chat_id, followup_text)
            else:
                print(f"[ERROR] LinkedIn publication failed with status {status_code}: {res_text}")
                cleanup_state_files()
                state_modified = True

                if msg_id:
                    edit_telegram_message(
                        bot_token, chat_id, msg_id,
                        f"⚠️ <b>LinkedIn Publication Failed (HTTP {status_code})</b>\n\nDraft discarded. Re-triggering new post generation..."
                    )

                alert_text = (
                    f"⚠️ <b>LinkedIn Posting Failed (HTTP {status_code})</b>\n\n"
                    f"<b>Response:</b> <code>{html.escape(res_text)}</code>\n\n"
                    f"<i>The failed draft has been discarded and a new post generation workflow has been triggered automatically.</i>"
                )
                send_telegram_message(bot_token, chat_id, alert_text)
                trigger_generate_workflow()

        # 2. Reject Both
        elif action in ("reject_all", "reject"):
            if callback_id:
                answer_callback_query(bot_token, callback_id, "Draft rejected. Generating new draft...")
            print("[INFO] Reject received. Discarding draft and triggering new generation...")
            cleanup_state_files()
            state_modified = True

            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    f"❌ <b>Draft Rejected & Discarded</b>\n\n<s>{html.escape(post_text)}</s>"
                )
            send_telegram_message(
                bot_token, chat_id,
                "🗑️ <b>Draft Rejected & Discarded.</b> Generating a brand new post draft now..."
            )
            trigger_generate_workflow()

        # 3. Accept Text & Regenerate Image (re-renders cover with new background / style)
        elif action == "regen_image":
            if callback_id:
                answer_callback_query(bot_token, callback_id, "Regenerating cover image...")
            print("[INFO] Regenerating cover image headline overlay...")
            new_cover_bytes = create_professional_cover_image(image_title, category, bg_prompt)

            with open(COVER_FILE, "wb") as f:
                f.write(new_cover_bytes)
            state_modified = True

            if photo_msg_id:
                edit_telegram_photo(bot_token, chat_id, photo_msg_id, new_cover_bytes)

            send_telegram_message(bot_token, chat_id, "🎨 <b>New Cover Image Card generated!</b> Check the photo preview above.")

        # 4. Accept Image & Regenerate Text
        elif action == "regen_text":
            if callback_id:
                answer_callback_query(bot_token, callback_id, "Regenerating post text...")
            print("[INFO] Regenerating post text via Z.ai...")
            try:
                from generate_post import call_zai_api
                new_text, new_title, new_cat, new_bg = call_zai_api(zai_api_key)
                if new_text:
                    pending_data["text"] = new_text
                    pending_data["image_title"] = new_title
                    pending_data["category"] = new_cat
                    pending_data["bg_prompt"] = new_bg

                    new_cover_bytes = create_professional_cover_image(new_title, new_cat, new_bg)
                    with open(COVER_FILE, "wb") as f:
                        f.write(new_cover_bytes)

                    with open(PENDING_FILE, "w", encoding="utf-8") as f:
                        json.dump(pending_data, f, indent=2, ensure_ascii=False)
                    state_modified = True

                    if photo_msg_id:
                        edit_telegram_photo(bot_token, chat_id, photo_msg_id, new_cover_bytes)

                    if msg_id:
                        formatted_text = (
                            f"📝 <b>New LinkedIn Post Draft Pending Approval (Text & Headline Regenerated):</b>\n\n"
                            f"{html.escape(new_text)}\n\n"
                            f"<i>Please choose an action below:</i>"
                        )
                        edit_telegram_message(bot_token, chat_id, msg_id, formatted_text, keep_keyboard=True)
                    send_telegram_message(bot_token, chat_id, "✍️ <b>New post text & headline generated!</b> Updated draft text above.")
            except Exception as exc:
                print(f"[ERROR] Text regeneration failed: {exc}")
                send_telegram_message(bot_token, chat_id, f"❌ <b>Text regeneration failed:</b> {html.escape(str(exc))}")

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

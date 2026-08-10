import os
import sys
import json
import html
import requests
from image_utils import create_professional_cover_image

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")

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
                    {"text": "✅ Accept", "callback_data": "approve"}
                ],
                [
                    {"text": "❌ Reject", "callback_data": "reject"},
                    {"text": "🔄 Reject & Regenerate", "callback_data": "reject_regen"}
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

def send_telegram_draft(bot_token: str, chat_id: str, post_text: str, cover_bytes: bytes, img_source: str = "gemini") -> tuple[int, int]:
    """Sends fresh photo preview and text message with 4 buttons to Telegram."""
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

def get_linkedin_api_version() -> str:
    """Returns valid 6-digit YYYYMM LinkedIn API version string (e.g. '202604')."""
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
    linkedin_version = get_linkedin_api_version()

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
                    "altText": "Mobile Development Technology Article Illustration"
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
    chat_id_env = os.environ.get("TELEGRAM_CHAT_ID")
    authorized_user_id = os.environ.get("TELEGRAM_AUTHORIZED_USER_ID")
    linkedin_access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_person_urn = os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:aAOQrAt7pG")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

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
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
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
            print(f"[WARN] Could not parse CLIENT_PAYLOAD JSON: {e}")

    if not isinstance(payload, dict):
        payload = {}

    action = payload.get("action")
    chat_id = payload.get("chat_id") or chat_id_env
    msg_id = payload.get("message_id")
    user_id = payload.get("user_id")

    if user_id and str(user_id) != str(authorized_user_id):
        print(f"[WARN] Unauthorized user_id={user_id} in client_payload. Expected {authorized_user_id}. Terminating.")
        sys.exit(0)

    if not action:
        print("[INFO] No dispatch action provided (scheduled or manual run). Checking state...")
        if not os.path.exists(PENDING_FILE):
            print("[INFO] No pending post. Exiting.")
            sys.exit(0)
        else:
            print("[INFO] Pending post draft exists. Waiting for user decision via Cloudflare Worker relay.")
            sys.exit(0)

    if not os.path.exists(PENDING_FILE):
        print(f"[INFO] Dispatch action '{action}' received, but {PENDING_FILE} does not exist.")
        if action in ("reject_regen", "reject_all", "regen_text"):
            print("[INFO] Action requires generating a new post. Triggering generate.yml workflow...")
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    "🔄 <b>Draft Rejected — Generating New Draft...</b>"
                )
            send_telegram_message(
                bot_token, chat_id,
                "🔄 <b>Generating a brand new post draft now...</b>"
            )
            trigger_generate_workflow()
            sys.exit(0)
        elif action in ("reject", "reject_only"):
            print("[INFO] Reject action received. Cleaning up state...")
            cleanup_state_files()
            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    "❌ <b>Draft Rejected & Discarded</b>"
                )
            send_telegram_message(
                bot_token, chat_id,
                "🗑️ <b>Draft Rejected.</b> No new post will be generated."
            )
            sys.exit(0)
        else:
            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    "⚠️ <i>This post draft was already processed or is no longer pending.</i>"
                )
            sys.exit(0)

    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            pending_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read {PENDING_FILE}: {e}")
        sys.exit(1)

    post_text = pending_data.get("text", "")
    image_title = pending_data.get("image_title", "MOBILE AI UPDATE")
    category = pending_data.get("category", "SOFTWARE ENGINEERING")
    bg_prompt = pending_data.get("bg_prompt", "")
    if not msg_id:
        msg_id = pending_data.get("message_id")

    cover_bytes = None
    if os.path.exists(COVER_FILE):
        try:
            with open(COVER_FILE, "rb") as f:
                cover_bytes = f.read()
        except Exception as e:
            print(f"[WARN] Could not read {COVER_FILE}: {e}")

    # 1. Accept Both
    if action in ("approve", "approve_all", "accept"):
        print("[INFO] Approve received via Cloudflare Worker. Publishing text to LinkedIn...")
        success, status_code, post_urn, res_text = publish_to_linkedin(
            linkedin_access_token, linkedin_person_urn, post_text, cover_bytes
        )

        if success:
            print(f"[SUCCESS] Post published to LinkedIn. URN: {post_urn}")
            cleanup_state_files()

            if msg_id:
                edit_telegram_message(
                    bot_token, chat_id, msg_id,
                    f"✅ <b>Posted to LinkedIn</b>\n\n{html.escape(post_text)}"
                )

            post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
            followup_text = f"🎉 <b>LinkedIn Post Published Successfully!</b>\n\n<b>Post URN:</b> <code>{html.escape(post_urn)}</code>"
            if post_url:
                followup_text += f"\n<b>Link:</b> {post_url}"
            send_telegram_message(bot_token, chat_id, followup_text)
        else:
            print(f"[ERROR] LinkedIn publication failed with status {status_code}: {res_text}")
            cleanup_state_files()

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

    # 2. Reject & Don't Generate New Post
    elif action in ("reject", "reject_only"):
        print("[INFO] Reject received via Cloudflare Worker. Discarding draft without generating a new post...")
        cleanup_state_files()

        if msg_id:
            edit_telegram_message(
                bot_token, chat_id, msg_id,
                f"❌ <b>Draft Rejected & Discarded</b>\n\n<s>{html.escape(post_text)}</s>"
            )
        send_telegram_message(
            bot_token, chat_id,
            "🗑️ <b>Draft Rejected.</b> No new post will be generated."
        )

    # 3. Reject & Generate New Post
    elif action in ("reject_regen", "reject_all"):
        print("[INFO] Reject & Regenerate received via Cloudflare Worker. Discarding draft and triggering new generation...")
        cleanup_state_files()

        if msg_id:
            edit_telegram_message(
                bot_token, chat_id, msg_id,
                f"🔄 <b>Draft Rejected — Generating New Draft...</b>\n\n<s>{html.escape(post_text)}</s>"
            )
        send_telegram_message(
            bot_token, chat_id,
            "🗑️ <b>Draft Rejected & Discarded.</b> Generating a brand new post draft now..."
        )
        trigger_generate_workflow()

    # 3. Accept Text & Regenerate Image (Sends fresh Telegram photo & text draft)
    elif action == "regen_image":
        print("[INFO] Regenerating 16:9 tech cover image...")
        if msg_id:
            edit_telegram_message(bot_token, chat_id, msg_id, "🔄 <i>Cover image updated — sending new draft preview below...</i>")

        new_cover_bytes, img_source = create_professional_cover_image(image_title, category, bg_prompt)

        with open(COVER_FILE, "wb") as f:
            f.write(new_cover_bytes)

        photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, post_text, new_cover_bytes, img_source=img_source)
        pending_data["photo_message_id"] = photo_msg_id
        pending_data["message_id"] = text_msg_id
        pending_data["image_source"] = img_source

        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

    # 4. Accept Image & Regenerate Text (Sends fresh Telegram draft)
    elif action == "regen_text":
        print("[INFO] Regenerating post text via Gemini API...")
        try:
            if msg_id:
                edit_telegram_message(bot_token, chat_id, msg_id, "🔄 <i>Post text updated — sending new draft preview below...</i>")

            from generate_post import call_gemini_text_api
            new_text, new_title, new_cat, new_bg = call_gemini_text_api(gemini_api_key)
            if new_text:
                pending_data["text"] = new_text
                pending_data["image_title"] = new_title
                pending_data["category"] = new_cat
                pending_data["bg_prompt"] = new_bg

                new_cover_bytes, img_source = create_professional_cover_image(new_title, new_cat, new_bg)
                with open(COVER_FILE, "wb") as f:
                    f.write(new_cover_bytes)

                photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, new_text, new_cover_bytes, img_source=img_source)
                pending_data["photo_message_id"] = photo_msg_id
                pending_data["message_id"] = text_msg_id
                pending_data["image_source"] = img_source

                with open(PENDING_FILE, "w", encoding="utf-8") as f:
                    json.dump(pending_data, f, indent=2, ensure_ascii=False)

        except Exception as exc:
            print(f"[ERROR] Text regeneration failed: {exc}")
            send_telegram_message(bot_token, chat_id, f"❌ <b>Text regeneration failed:</b> {html.escape(str(exc))}")

if __name__ == "__main__":
    main()

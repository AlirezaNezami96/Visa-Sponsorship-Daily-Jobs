#!/usr/bin/env python3
"""
Telegram Publishing Diagnostic & Verification Tool.
Tests credentials, channel administrator permissions, database configuration, and sending a test post.

Usage:
    python scripts/test_telegram_publish.py [--send]
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
from typing import Any, Dict

# Load local .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def log(emoji: str, msg: str) -> None:
    print(f"{emoji} {msg}")


import ssl
try:
    import certifi
    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _ssl_context = ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None


def telegram_api_call(token: str, method: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    
    try:
        kwargs = {"timeout": 15}
        if _ssl_context:
            kwargs["context"] = _ssl_context
        with urllib.request.urlopen(req, **kwargs) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(error_body)
        except Exception:
            return {"ok": False, "error_code": e.code, "description": error_body}
    except Exception as e:
        # Retry with unverified SSL if default verification failed
        try:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=unverified_ctx, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as retry_err:
            return {"ok": False, "description": f"{e} (retry: {retry_err})"}



def main() -> None:
    parser = argparse.ArgumentParser(description="Test Telegram bot token, chat access, and publishing permissions.")
    parser.add_argument("--send", action="store_true", help="Send an actual test message to the configured channel/chat.")
    args = parser.parse_args()

    print("=" * 65)
    print("🔍 VisaLane Telegram Publishing Diagnostic Tool")
    print("=" * 65)

    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    # 1. Environment Variable Checks
    print("\n[Step 1/5] Checking Environment Variables:")
    if not bot_token:
        log("❌", "TELEGRAM_BOT_TOKEN is MISSING in environment / .env")
        log("💡", "Create a bot with @BotFather on Telegram and copy the API token.")
    else:
        masked = bot_token[:8] + "..." + bot_token[-5:] if len(bot_token) > 15 else "***"
        log("✅", f"TELEGRAM_BOT_TOKEN is set: {masked}")

    if not chat_id:
        log("❌", "TELEGRAM_CHAT_ID is MISSING in environment / .env")
        log("💡", "Set this to your public channel username (e.g. '@visalane') or numeric ID (e.g. '-1001234567890').")
    else:
        log("✅", f"TELEGRAM_CHAT_ID is set: {chat_id}")

    if not bot_token or not chat_id:
        print("\n❌ Diagnostic failed: Missing required environment variables.")
        sys.exit(1)

    # 2. Bot Identity Check (getMe)
    print("\n[Step 2/5] Verifying Bot Token with Telegram API (getMe):")
    me_resp = telegram_api_call(bot_token, "getMe")
    if not me_resp.get("ok"):
        log("❌", f"Telegram API rejected bot token: {me_resp.get('description', 'Unknown error')}")
        sys.exit(1)

    bot_info = me_resp.get("result", {})
    bot_id = bot_info.get("id")
    bot_username = bot_info.get("username")
    bot_name = bot_info.get("first_name")
    log("✅", f"Bot Authenticated Successfully!")
    log("🤖", f"Bot Name: {bot_name} (@{bot_username}, ID: {bot_id})")

    # 3. Chat Access Check (getChat)
    print(f"\n[Step 3/5] Verifying Channel/Chat Access (getChat for '{chat_id}'):")
    chat_resp = telegram_api_call(bot_token, "getChat", {"chat_id": chat_id})
    if not chat_resp.get("ok"):
        log("❌", f"Cannot access chat '{chat_id}': {chat_resp.get('description')}")
        log("💡", f"CRITICAL: Have you added @{bot_username} to the channel/group as an ADMINISTRATOR?")
        log("💡", "Steps: Open your Telegram Channel -> Channel Info -> Administrators -> Add Administrator -> Search your bot -> Grant 'Post Messages' permission.")
        sys.exit(1)

    chat_info = chat_resp.get("result", {})
    chat_title = chat_info.get("title") or chat_info.get("username") or "Direct Chat"
    chat_type = chat_info.get("type", "unknown")
    log("✅", f"Chat Found: '{chat_title}' (Type: {chat_type})")

    # 4. Administrator Permissions Check (getChatMember)
    print(f"\n[Step 4/5] Verifying Administrator Rights in '{chat_title}':")
    if chat_type in ("channel", "supergroup", "group") and bot_id:
        member_resp = telegram_api_call(bot_token, "getChatMember", {"chat_id": chat_id, "user_id": bot_id})
        if member_resp.get("ok"):
            member_info = member_resp.get("result", {})
            status = member_info.get("status")
            can_post = member_info.get("can_post_messages", status in ("creator", "administrator"))
            
            if status in ("creator", "administrator"):
                log("✅", f"Bot status in channel: {status.upper()}")
                if can_post or status == "creator":
                    log("✅", "Bot has permission to POST messages in this channel.")
                else:
                    log("⚠️", "Bot is an administrator, but 'can_post_messages' permission might be FALSE.")
            else:
                log("❌", f"Bot is NOT an administrator (Current status: {status}).")
                log("💡", "The bot MUST be an Administrator in the channel to post messages.")
        else:
            log("⚠️", f"Could not query member permissions: {member_resp.get('description')}")

    # 5. Database Configuration & State Check
    print("\n[Step 5/5] Checking Database 'platform_post_config' for Telegram:")
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        if supabase_url and supabase_key:
            from supabase import create_client
            client = create_client(supabase_url, supabase_key)
            resp = client.table("platform_post_config").select("*").eq("platform", "telegram").maybe_single().execute()
            cfg = resp.data if resp else None
            if cfg:
                enabled = cfg.get("enabled", False)
                daily_cap = cfg.get("daily_cap", 20)
                published_today = cfg.get("published_today", 0)
                min_gap = cfg.get("min_gap_minutes", 15)
                last_post = cfg.get("last_post_at")
                
                log("✅" if enabled else "⚠️", f"Database config: enabled={enabled}, daily_cap={daily_cap}, published_today={published_today}, min_gap={min_gap}m")
                if not enabled:
                    log("💡", "Telegram is currently marked 'enabled = false' in database. Enable it in Admin Panel -> Social Hub or via SQL.")
                if published_today >= daily_cap:
                    log("⚠️", f"Telegram has reached its daily cap ({published_today}/{daily_cap}).")
            else:
                log("ℹ️", "No platform_post_config entry found for 'telegram' (using defaults).")
        else:
            log("ℹ️", "SUPABASE_URL/SUPABASE_KEY not in local environment, skipping DB config check.")
    except Exception as e:
        log("ℹ️", f"Skipped DB check: {e}")

    # 6. Send Test Message (if requested)
    if args.send:
        print(f"\n🚀 Sending Test Message to '{chat_title}'...")
        test_text = (
            "🧪 *VisaLane Telegram Publishing Test*\n\n"
            "This is a verification test from the VisaLane Publishing Engine.\n"
            "✅ *Status:* Connection Active & Verified\n"
            "🌍 *Web:* [visalane.app](https://visalane.app)\n\n"
            "_Automated visa-sponsored job radar is operational._"
        )
        send_resp = telegram_api_call(bot_token, "sendMessage", {
            "chat_id": chat_id,
            "text": test_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })

        if send_resp.get("ok"):
            msg_id = send_resp.get("result", {}).get("message_id")
            log("🎉", f"SUCCESS! Message sent to Telegram (Message ID: {msg_id})")
        else:
            log("❌", f"Failed to send message: {send_resp.get('description')}")
    else:
        print("\n💡 Tip: To send a real test post to your channel, run:")
        print("    python scripts/test_telegram_publish.py --send")

    print("\n" + "=" * 65)


if __name__ == "__main__":
    main()

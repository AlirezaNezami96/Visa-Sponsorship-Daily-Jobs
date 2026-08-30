"""Platform-specific publisher with atomic claim, pacing, anti-spam safeguards, and manual-review fallbacks.

Runs as: python -m job_radar.social.platform_publisher --platform [telegram|discord|slack|x|linkedin|bluesky|mastodon]

Enforces rules configured in `platform_post_config`:
- active hours window (UTC)
- min gap between posts
- daily post cap
- enabled flag

Atomic claim via `claim_next_post_job` prevents duplicate-post races under concurrent runs.
LinkedIn/X without automated credentials route to Telegram manual review.
Approvals/rejections wire back into the state machine and mirror publication flags.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def get_platform_config(client: Any, platform: str) -> Dict[str, Any]:
    """Fetch pacing rules from platform_post_config."""
    resp = (
        client.table("platform_post_config")
        .select("*")
        .eq("platform", platform)
        .maybe_single()
        .execute()
    )
    if resp and resp.data:
        return resp.data

    defaults = {
        "telegram": {"min_gap_minutes": 5, "daily_cap": 40, "active_start_hour": 0, "active_end_hour": 24, "enabled": True},
        "discord": {"min_gap_minutes": 5, "daily_cap": 40, "active_start_hour": 0, "active_end_hour": 24, "enabled": True},
        "slack": {"min_gap_minutes": 5, "daily_cap": 40, "active_start_hour": 0, "active_end_hour": 24, "enabled": True},
        "bluesky": {"min_gap_minutes": 30, "daily_cap": 12, "active_start_hour": 6, "active_end_hour": 23, "enabled": False},
        "mastodon": {"min_gap_minutes": 30, "daily_cap": 12, "active_start_hour": 6, "active_end_hour": 23, "enabled": False},
        "x": {"min_gap_minutes": 60, "daily_cap": 5, "active_start_hour": 7, "active_end_hour": 22, "enabled": False},
        "linkedin": {"min_gap_minutes": 120, "daily_cap": 3, "active_start_hour": 7, "active_end_hour": 19, "enabled": False},
    }
    return defaults.get(platform, {"min_gap_minutes": 60, "daily_cap": 5, "active_start_hour": 0, "active_end_hour": 24, "enabled": True})


def check_pacing(client: Any, platform: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if the platform is currently allowed to publish under pacing rules."""
    if not config.get("enabled", True):
        return False, "platform is disabled in config"

    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour

    # 1. Active hours check
    start_hour = config.get("active_start_hour", 0)
    end_hour = config.get("active_end_hour", 24)
    if not (start_hour <= current_hour < end_hour):
        return False, f"outside active hours ({start_hour}:00 - {end_hour}:00 UTC, now {current_hour}:00)"

    # 2. Daily cap check
    today_iso = now_utc.strftime("%Y-%m-%d")
    date_col = f"{platform}_at"
    resp = (
        client.table("job_processing")
        .select("job_id", count="exact")
        .gte(date_col, f"{today_iso}T00:00:00Z")
        .execute()
    )
    daily_count = resp.count if resp and resp.count else 0
    daily_cap = config.get("daily_cap", 10)
    if daily_count >= daily_cap:
        return False, f"daily cap reached ({daily_count}/{daily_cap})"

    # 3. Minimum gap check
    min_gap = config.get("min_gap_minutes", 10)
    if min_gap > 0:
        last_resp = (
            client.table("job_processing")
            .select(date_col)
            .neq(date_col, None)
            .order(date_col, desc=True)
            .limit(1)
            .execute()
        )
        if last_resp and last_resp.data:
            last_date_str = last_resp.data[0].get(date_col)
            if last_date_str:
                last_dt = datetime.fromisoformat(last_date_str.replace("Z", "+00:00"))
                elapsed_minutes = (now_utc - last_dt).total_seconds() / 60.0
                if elapsed_minutes < min_gap:
                    return False, f"min gap not elapsed ({elapsed_minutes:.1f}m < {min_gap}m)"

    return True, "ok"


def claim_next_post_job(client: Any, platform: str) -> Optional[Dict[str, Any]]:
    """Claim the oldest pending post for this platform atomically using RPC or select+update."""
    status_col = f"{platform}_status"

    # 1. Try atomic database RPC (FOR UPDATE SKIP LOCKED)
    try:
        rpc_resp = client.rpc("claim_next_post_job", {"p_platform": platform}).execute()
        if rpc_resp and rpc_resp.data and len(rpc_resp.data) > 0:
            return rpc_resp.data[0]
    except Exception as e:
        logger.debug("RPC claim_next_post_job fallback: %s", e)

    # 2. Fallback query (select then transition to processing)
    resp = (
        client.table("job_processing")
        .select("job_id, post_text")
        .eq("post_text_status", "done")
        .eq(status_col, "pending")
        .order("updated_at")
        .limit(1)
        .execute()
    )

    if not resp or not resp.data:
        return None

    row = resp.data[0]
    job_id = row["job_id"]

    # Transition to processing
    client.table("job_processing").update({status_col: "processing"}).eq("job_id", job_id).eq(status_col, "pending").execute()

    job_resp = client.table("jobs").select("image_url").eq("id", job_id).maybe_single().execute()
    image_url = job_resp.data.get("image_url") if job_resp and job_resp.data else None

    return {
        "job_id": job_id,
        "post_text": row.get("post_text"),
        "image_url": image_url,
    }


def _send_telegram_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Telegram channel with optional photo."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False, "missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"

    import requests
    try:
        if image_url:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": text[:1024],
                "parse_mode": "Markdown",
            }
            res = requests.post(url, json=payload, timeout=20)
            if res.status_code == 200:
                msg_id = res.json().get("result", {}).get("message_id")
                return True, f"https://t.me/c/{chat_id.replace('-100', '')}/{msg_id}" if msg_id else "https://t.me"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            msg_id = res.json().get("result", {}).get("message_id")
            return True, f"https://t.me/c/{chat_id.replace('-100', '')}/{msg_id}" if msg_id else "https://t.me"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_discord_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Discord webhook."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False, "missing DISCORD_WEBHOOK_URL"

    import requests
    try:
        payload: Dict[str, Any] = {"content": text}
        if image_url:
            payload["embeds"] = [{"image": {"url": image_url}}]
        res = requests.post(webhook_url, json=payload, timeout=15)
        if res.status_code in (200, 204):
            return True, "https://discord.com"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_slack_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Slack webhook."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False, "missing SLACK_WEBHOOK_URL"

    import requests
    try:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        if image_url:
            blocks.append({
                "type": "image",
                "image_url": image_url,
                "alt_text": "Visa Sponsored Job",
            })
        res = requests.post(webhook_url, json={"blocks": blocks}, timeout=15)
        if res.status_code == 200:
            return True, "https://slack.com"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_bluesky_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Bluesky via AT Protocol."""
    handle = os.getenv("BLUESKY_HANDLE")
    app_password = os.getenv("BLUESKY_APP_PASSWORD")
    if not handle or not app_password:
        return False, "missing BLUESKY_HANDLE or BLUESKY_APP_PASSWORD"

    import requests
    try:
        session_resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password},
            timeout=15,
        )
        if session_resp.status_code != 200:
            return False, f"Bluesky auth failed: {session_resp.text[:100]}"
        session_data = session_resp.json()
        access_jwt = session_data["accessJwt"]
        did = session_data["did"]

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "app.bsky.feed.post",
            "text": text[:300],
            "createdAt": now_iso,
        }

        post_resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {access_jwt}"},
            json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            timeout=15,
        )
        if post_resp.status_code == 200:
            uri = post_resp.json().get("uri", "")
            rkey = uri.split("/")[-1] if "/" in uri else ""
            return True, f"https://bsky.app/profile/{handle}/post/{rkey}"
        return False, f"HTTP {post_resp.status_code}: {post_resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_mastodon_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Mastodon."""
    instance_url = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
    access_token = os.getenv("MASTODON_ACCESS_TOKEN")
    if not access_token:
        return False, "missing MASTODON_ACCESS_TOKEN"

    import requests
    try:
        url = f"{instance_url.rstrip('/')}/api/v1/statuses"
        payload = {"status": text[:500]}
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=15,
        )
        if res.status_code in (200, 201):
            post_url = res.json().get("url")
            return True, post_url or instance_url
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_linkedin_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to LinkedIn API."""
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    person_urn = os.getenv("LINKEDIN_PERSON_URN")
    if not token or not person_urn:
        return False, "missing LINKEDIN_ACCESS_TOKEN or LINKEDIN_PERSON_URN"

    import requests
    try:
        url = "https://api.linkedin.com/v2/ugcPosts"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code in (200, 201):
            post_id = res.headers.get("x-restli-id", "")
            return True, f"https://www.linkedin.com/feed/update/{post_id}" if post_id else "https://linkedin.com"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_x_post(text: str, image_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Publish to Twitter/X API."""
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    if not (bearer_token or (api_key and access_token)):
        return False, "missing Twitter/X API credentials"

    import requests
    try:
        # OAuth 1.0a or OAuth 2.0 user context
        from requests_oauthlib import OAuth1
        auth = OAuth1(api_key, api_secret, access_token, access_secret)
        url = "https://api.twitter.com/2/tweets"
        payload = {"text": text[:280]}
        res = requests.post(url, auth=auth, json=payload, timeout=15)
        if res.status_code in (200, 201):
            tweet_id = res.json().get("data", {}).get("id", "")
            return True, f"https://x.com/i/web/status/{tweet_id}" if tweet_id else "https://x.com"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_for_manual_review(
    client: Any,
    job: Dict[str, Any],
    platform: str,
    text: str,
    image_url: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """Route post to Telegram approval bot for manual review (LinkedIn / X)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not admin_chat_id:
        return False, "missing Telegram credentials for manual review"

    import requests
    try:
        job_id = str(job.get("id"))
        title = job.get("title", "Role")
        company = job.get("company", "Company")

        caption = (
            f"🔍 *Manual Review Required: {platform.upper()} Post*\n\n"
            f"📌 *{title}* @ *{company}*\n\n"
            f"```\n{text[:600]}\n```\n\n"
            f"Job ID: `{job_id}`"
        )

        # Full job_id in callback_data (e.g. approve_linkedin_<uuid> <= 53 chars <= 64 bytes limit)
        inline_keyboard = [
            [
                {"text": "✅ Approve & Post", "callback_data": f"approve_{platform}_{job_id}"},
                {"text": "❌ Reject", "callback_data": f"reject_{platform}_{job_id}"},
            ]
        ]

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": admin_chat_id,
            "text": caption,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": inline_keyboard},
        }
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            return True, "sent_to_telegram_review"
        return False, f"Telegram API HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)


def handle_approval_callback(client: Any, callback_data: str) -> Dict[str, Any]:
    """Wire Telegram approval/rejection button click to state machine and platform publisher."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric

    parts = callback_data.split("_", 2)
    if len(parts) < 3:
        return {"ok": False, "error": f"invalid callback_data: {callback_data}"}

    action, platform, job_id = parts[0], parts[1], parts[2]

    if action == "reject":
        transition_stage(client, job_id, platform, "failed", error="rejected_by_admin")
        record_metric(client, f"post:{platform}:rejected", True, 0)
        logger.info("Admin rejected %s post for job %s", platform, job_id)
        return {"ok": True, "action": "rejected", "job_id": job_id, "platform": platform}

    if action == "approve":
        # Fetch post text
        resp = client.table("job_processing").select("post_text").eq("job_id", job_id).maybe_single().execute()
        row = resp.data[0] if isinstance(resp.data, list) and resp.data else resp.data if isinstance(resp.data, dict) else {}
        raw_text = row.get("post_text") if row else "{}"
        try:
            texts = json.loads(raw_text)
        except Exception:
            texts = {}
        target_text = texts.get(platform, "")

        # Fetch image
        job_resp = client.table("jobs").select("image_url").eq("id", job_id).maybe_single().execute()
        j_row = job_resp.data[0] if isinstance(job_resp.data, list) and job_resp.data else job_resp.data if isinstance(job_resp.data, dict) else {}
        image_url = j_row.get("image_url") if j_row else None

        # Dispatch
        dispatchers = {
            "linkedin": _send_linkedin_post,
            "x": _send_x_post,
            "telegram": _send_telegram_post,
            "discord": _send_discord_post,
            "slack": _send_slack_post,
            "bluesky": _send_bluesky_post,
            "mastodon": _send_mastodon_post,
        }
        handler = dispatchers.get(platform)
        if not handler:
            return {"ok": False, "error": f"no dispatcher for {platform}"}

        success, post_url_or_err = handler(target_text, image_url)
        if success:
            post_url = post_url_or_err or f"https://{platform}.com"
            transition_stage(client, job_id, platform, "done", url=post_url)
            mirror_col = f"{platform}_post_published"
            client.table("jobs").update({mirror_col: True}).eq("id", job_id).execute()
            record_metric(client, f"post:{platform}:published", True, 0)
            logger.info("Admin approved & published job %s to %s", job_id, platform)
            return {"ok": True, "action": "published", "job_id": job_id, "url": post_url}
        else:
            err = post_url_or_err or "publish failed"
            transition_stage(client, job_id, platform, "failed", error=err)
            record_metric(client, f"post:{platform}:failed", False, 0)
            return {"ok": False, "action": "failed", "job_id": job_id, "error": err}

    return {"ok": False, "error": f"unknown action: {action}"}


def publish_next_job(client: Any, platform: str) -> Dict[str, Any]:
    """Publish the next eligible job to the specified platform with atomic claim and circuit breakers."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric
    from job_radar.pipeline.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(client)
    circuit_name = f"publish:{platform}"

    config = get_platform_config(client, platform)
    allowed, reason = check_pacing(client, platform, config)
    if not allowed:
        logger.info("Skipping %s publish: %s", platform, reason)
        record_metric(client, f"post:{platform}:skipped", True, 0)
        return {"ok": True, "action": "skipped", "reason": reason}

    # Check circuit breaker
    if cb.is_open(circuit_name):
        logger.warning("Circuit %s is open, skipping publish", circuit_name)
        record_metric(client, f"circuit:open:{circuit_name}", True, 0)
        return {"ok": False, "action": "circuit_open", "error": "circuit open"}

    # Atomic claim
    claimed = claim_next_post_job(client, platform)
    if not claimed:
        logger.info("No pending jobs for %s", platform)
        return {"ok": True, "action": "idle", "reason": "no pending jobs"}

    job_id = claimed["job_id"]
    raw_post_text = claimed.get("post_text") or "{}"
    image_url = claimed.get("image_url")

    try:
        post_texts = json.loads(raw_post_text)
    except Exception:
        post_texts = {}
    target_text = post_texts.get(platform) or ""

    # Fetch job info
    job_resp = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
    job = job_resp.data if job_resp else {}

    # Check if manual review is required
    requires_manual = platform in ("linkedin", "x") and not os.getenv(f"{platform.upper()}_AUTO_PUBLISH")

    start_time = time.time()

    if requires_manual:
        ok, detail = _send_for_manual_review(client, job, platform, target_text, image_url)
        if ok:
            transition_stage(client, job_id, platform, "manual_review")
            record_metric(client, f"post:{platform}:manual", True, 0)
            logger.info("Routed job %s to Telegram manual review for %s", job_id, platform)
            return {"ok": True, "action": "manual_review", "job_id": job_id}
        else:
            logger.warning("Failed to route to manual review: %s", detail)
            transition_stage(client, job_id, platform, "failed", error=detail)
            return {"ok": False, "action": "manual_failed", "error": detail}

    dispatchers = {
        "telegram": _send_telegram_post,
        "discord": _send_discord_post,
        "slack": _send_slack_post,
        "bluesky": _send_bluesky_post,
        "mastodon": _send_mastodon_post,
        "linkedin": _send_linkedin_post,
        "x": _send_x_post,
    }

    handler = dispatchers.get(platform)
    if not handler:
        logger.warning("No automated dispatcher for platform %s", platform)
        transition_stage(client, job_id, platform, "failed", error=f"no dispatcher for {platform}")
        return {"ok": False, "error": f"no dispatcher for {platform}"}

    success, post_url_or_err = handler(target_text, image_url)
    duration_ms = int((time.time() - start_time) * 1000)

    if success:
        cb.record_success(circuit_name)
        post_url = post_url_or_err or f"https://{platform}.com"
        transition_stage(client, job_id, platform, "done", url=post_url)
        mirror_col = f"{platform}_post_published"
        client.table("jobs").update({mirror_col: True}).eq("id", job_id).execute()
        record_metric(client, f"post:{platform}:published", True, duration_ms)
        logger.info("Published job %s to %s -> %s", job_id, platform, post_url)
        return {"ok": True, "action": "published", "job_id": job_id, "url": post_url}
    else:
        cb.record_failure(circuit_name)
        err_msg = post_url_or_err or "publish failed"
        logger.error("Failed to publish job %s to %s: %s", job_id, platform, err_msg)
        transition_stage(client, job_id, platform, "failed", error=err_msg)
        record_metric(client, f"post:{platform}:failed", False, duration_ms)
        return {"ok": False, "action": "failed", "job_id": job_id, "error": err_msg}


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish next job to social platform")
    parser.add_argument("--platform", required=True, choices=["telegram", "discord", "slack", "x", "linkedin", "bluesky", "mastodon"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = _create_client()
    result = publish_next_job(client, args.platform)
    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()

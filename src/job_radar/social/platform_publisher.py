"""Platform-specific publisher with adapter registry, kill-switch gating, pacing, and retrybackoff.

Runs as: python -m job_radar.social.platform_publisher --platform [x|bluesky|mastodon|linkedin|telegram|discord|devto]

Publishing Lifecycle:
1. Kill Switch & Enable Gate check (`can_publish`) -> exits safely with `action: disabled` if disabled.
2. Dry-Run Gate (`dry_run`) -> transitions to `done` with `url="dry-run"` without making live network calls.
3. Pacing & Active Hours check (`check_pacing`).
4. Circuit Breaker check (`social:{platform}`).
5. Atomic claim (`claim_next_post_job`) preventing race conditions across concurrent workflow runs.
6. Manual review routing for LinkedIn/X when automated flag is absent.
7. Adapter execution with exponential backoff & adaptive image compression ladder.
8. State transitions and metrics recording.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from job_radar.social.adapters import get_adapter
from job_radar.social.image_prep import prepare_image_for_platform
from job_radar.social.kill_switch import can_publish, dry_run
from job_radar.social.retry import execute_with_retry

logger = logging.getLogger(__name__)


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client  # type: ignore[attr-defined]
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def get_platform_config(client: Any, platform: str) -> dict[str, Any]:
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
        "telegram": {"min_gap_minutes": 15, "daily_cap": 20, "active_start_hour": 7, "active_end_hour": 23, "enabled": False},
        "discord": {"min_gap_minutes": 15, "daily_cap": 20, "active_start_hour": 7, "active_end_hour": 23, "enabled": False},
        "bluesky": {"min_gap_minutes": 30, "daily_cap": 10, "active_start_hour": 7, "active_end_hour": 22, "enabled": False},
        "mastodon": {"min_gap_minutes": 30, "daily_cap": 10, "active_start_hour": 7, "active_end_hour": 22, "enabled": False},
        "x": {"min_gap_minutes": 60, "daily_cap": 5, "active_start_hour": 7, "active_end_hour": 22, "enabled": False},
        "linkedin": {"min_gap_minutes": 120, "daily_cap": 3, "active_start_hour": 7, "active_end_hour": 19, "enabled": False},
        "devto": {"min_gap_minutes": 30, "daily_cap": 10, "active_start_hour": 6, "active_end_hour": 23, "enabled": False},
    }
    return defaults.get(platform, {"min_gap_minutes": 60, "daily_cap": 5, "active_start_hour": 0, "active_end_hour": 24, "enabled": False})


def check_pacing(client: Any, platform: str, config: dict[str, Any]) -> tuple[bool, str]:
    """Check if the platform is currently allowed to publish under pacing rules."""
    now_utc = datetime.now(UTC)
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
    count_val = getattr(resp, "count", 0)
    daily_count = count_val if isinstance(count_val, int) else 0
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
                try:
                    last_dt = datetime.fromisoformat(last_date_str.replace("Z", "+00:00"))
                    elapsed_min = (now_utc - last_dt).total_seconds() / 60
                    if elapsed_min < min_gap:
                        return False, f"min gap not elapsed ({elapsed_min:.1f}m < {min_gap}m)"
                except Exception:
                    pass

    return True, "ok"


def claim_next_post_job(client: Any, platform: str) -> dict[str, Any] | None:
    """Atomically claim the next pending job for the specified platform."""
    from job_radar.pipeline.state_machine import transition_stage

    status_col = f"{platform}_status"

    resp = (
        client.table("job_processing")
        .select("job_id, post_text, image_url, image_status")
        .eq(status_col, "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )

    rows = resp.data if resp else []
    if not rows:
        return None

    row = rows[0]
    job_id = row["job_id"]

    res = transition_stage(client, job_id, platform, "processing")
    if not res.get("ok"):
        return None

    return row


def _send_for_manual_review(
    client: Any,
    job: dict[str, Any],
    platform: str,
    text: str,
    image_url: str | None,
) -> tuple[bool, str | None]:
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


def _send_telegram_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("telegram")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_discord_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("discord")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_x_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("x")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_linkedin_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("linkedin")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_bluesky_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("bluesky")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_mastodon_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("mastodon")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_devto_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    adapter = get_adapter("devto")
    if not adapter:
        return False, "no adapter"
    res = adapter.publish(text, image_url)
    return res.ok, res.url or res.error


def _send_slack_post(text: str, image_url: str | None = None) -> tuple[bool, str | None]:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False, "Missing SLACK_WEBHOOK_URL"
    import requests
    payload: dict[str, Any] = {"text": text}
    if image_url:
        payload["blocks"] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}, "accessory": {"type": "image", "image_url": image_url, "alt_text": "job"}}]
    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        return res.status_code == 200, "https://slack.com" if res.status_code == 200 else res.text
    except Exception as e:
        return False, str(e)


def handle_approval_callback(client: Any, callback_data: str) -> dict[str, Any]:
    """Wire Telegram approval/rejection button click to state machine and platform publisher."""
    from job_radar.pipeline.metrics import record_metric
    from job_radar.pipeline.state_machine import transition_stage

    parts = callback_data.split("_", 2)
    if len(parts) < 3:
        return {"ok": False, "error": f"invalid callback_data: {callback_data}"}

    action, platform, job_id = parts[0], parts[1], parts[2]

    if action == "reject":
        transition_stage(client, job_id, platform, "failed", error="rejected_by_admin")
        record_metric(client, f"publish:{platform}:rejected", True, 0)
        logger.info("Admin rejected %s post for job %s", platform, job_id)
        return {"ok": True, "action": "rejected", "job_id": job_id, "platform": platform}

    if action == "approve":
        resp = client.table("job_processing").select("post_text").eq("job_id", job_id).maybe_single().execute()
        row = resp.data[0] if isinstance(resp.data, list) and resp.data else resp.data if isinstance(resp.data, dict) else {}
        raw_text = row.get("post_text") if row else "{}"
        try:
            texts = json.loads(raw_text)
        except Exception:
            texts = {}
        target_text = texts.get(platform, "")

        job_resp = client.table("jobs").select("image_url").eq("id", job_id).maybe_single().execute()
        j_row = job_resp.data[0] if isinstance(job_resp.data, list) and job_resp.data else job_resp.data if isinstance(job_resp.data, dict) else {}
        image_url = j_row.get("image_url") if j_row else None

        dispatchers = {
            "telegram": _send_telegram_post,
            "discord": _send_discord_post,
            "slack": _send_slack_post,
            "bluesky": _send_bluesky_post,
            "mastodon": _send_mastodon_post,
            "linkedin": _send_linkedin_post,
            "x": _send_x_post,
            "devto": _send_devto_post,
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
            record_metric(client, f"publish:{platform}:published", True, 0)
            logger.info("Admin approved & published job %s to %s", job_id, platform)
            return {"ok": True, "action": "published", "job_id": job_id, "url": post_url}
        else:
            err = post_url_or_err or "publish failed"
            transition_stage(client, job_id, platform, "failed", error=err)
            record_metric(client, f"publish:{platform}:failed", False, 0)
            return {"ok": False, "action": "failed", "job_id": job_id, "error": err}

    return {"ok": False, "error": f"unknown action: {action}"}


def alert_owner_permanent_error(platform: str, job_id: str, error: str) -> None:
    """Send immediate notification to owner on permanent authentication or configuration errors."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not (bot_token and admin_chat_id):
        return

    import requests
    try:
        text = (
            f"🚨 *Permanent Social Publishing Auth Error*\n\n"
            f"• Platform: `{platform.upper()}`\n"
            f"• Job ID: `{job_id}`\n"
            f"• Error: `{error}`\n\n"
            f"Please refresh credentials or check platform API status."
        )
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning("Failed to dispatch permanent error alert: %s", e)


def publish_next_job(client: Any, platform: str) -> dict[str, Any]:
    """Publish the next eligible job to the specified platform with multi-gate checks, adapters, and circuit breakers."""
    from job_radar.pipeline.circuit_breaker import CircuitBreaker
    from job_radar.pipeline.metrics import record_metric
    from job_radar.pipeline.state_machine import transition_stage

    circuit_name = f"social:{platform}"
    cb = CircuitBreaker(client)

    # 1. GATE 1 & 3: Global kill switch and per-platform database config
    allowed, reason = can_publish(client, platform)
    if not allowed:
        logger.info("Publishing disabled for %s: %s", platform, reason)
        record_metric(client, f"publish:{platform}:disabled", True, 0)
        return {"ok": True, "action": "disabled", "reason": reason}

    # 2. Pacing check (active hours, rate limits)
    config = get_platform_config(client, platform)
    pacing_ok, pacing_reason = check_pacing(client, platform, config)
    if not pacing_ok:
        logger.info("Skipping %s publish: %s", platform, pacing_reason)
        record_metric(client, f"publish:{platform}:skipped", True, 0)
        return {"ok": True, "action": "skipped", "reason": pacing_reason}

    # 3. Circuit breaker check
    if cb.is_open(circuit_name):
        logger.warning("Circuit %s is open, skipping publish", circuit_name)
        record_metric(client, f"circuit:open:{circuit_name}", True, 0)
        return {"ok": False, "action": "circuit_open", "error": "circuit open"}

    # 4. Atomic claim
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

    # Fetch full job row
    job_resp = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
    job = job_resp.data if job_resp else {}

    # 5. GATE 2: Dry Run Check (zero network calls)
    if dry_run():
        logger.info("[DRY RUN] Publishing job %s to %s with text: %s", job_id, platform, target_text[:100])
        transition_stage(client, job_id, platform, "done", url="dry-run")
        record_metric(client, f"publish:{platform}:dryrun", True, 0)
        return {"ok": True, "action": "dry_run", "job_id": job_id, "url": "dry-run"}

    # 6. Manual review routing
    requires_manual = platform in ("linkedin", "x") and not os.getenv(f"{platform.upper()}_AUTO_PUBLISH")
    if requires_manual:
        ok, detail = _send_for_manual_review(client, job, platform, target_text, image_url)
        if ok:
            transition_stage(client, job_id, platform, "manual_review")
            record_metric(client, f"publish:{platform}:manual", True, 0)
            logger.info("Routed job %s to Telegram manual review for %s", job_id, platform)
            return {"ok": True, "action": "manual_review", "job_id": job_id}
        else:
            logger.warning("Failed to route to manual review: %s", detail)
            transition_stage(client, job_id, platform, "failed", error=detail)
            return {"ok": False, "action": "manual_failed", "error": detail}

    # 7. Resolve Adapter & Execute
    adapter = get_adapter(platform)
    if not adapter:
        logger.warning("No social adapter registered for platform %s", platform)
        transition_stage(client, job_id, platform, "failed", error=f"no adapter for {platform}")
        return {"ok": False, "error": f"no adapter for {platform}"}

    start_time = time.time()
    image_bytes = prepare_image_for_platform(image_url, adapter.max_image_bytes)

    result = execute_with_retry(lambda: adapter.publish(target_text, image_url, image_bytes))
    duration_ms = int((time.time() - start_time) * 1000)

    if result.ok:
        cb.record_success(circuit_name)
        post_url = result.url or f"https://{platform}.com"
        transition_stage(client, job_id, platform, "done", url=post_url)
        mirror_col = f"{platform}_post_published"
        client.table("jobs").update({mirror_col: True}).eq("id", job_id).execute()
        record_metric(client, f"publish:{platform}:published", True, duration_ms)
        logger.info("Published job %s to %s -> %s", job_id, platform, post_url)
        return {"ok": True, "action": "published", "job_id": job_id, "url": post_url}
    else:
        cb.record_failure(circuit_name)
        err_msg = result.error or "publish failed"
        logger.error("Failed to publish job %s to %s: %s", job_id, platform, err_msg)
        transition_stage(client, job_id, platform, "failed", error=err_msg)
        record_metric(client, f"publish:{platform}:failed", False, duration_ms)

        if result.permanent:
            record_metric(client, f"publish:{platform}:permanent_auth_error", False, 0)
            alert_owner_permanent_error(platform, job_id, err_msg)

        return {"ok": False, "action": "failed", "job_id": job_id, "error": err_msg}


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish next job to social platform")
    parser.add_argument("--platform", required=True, choices=["telegram", "discord", "slack", "x", "linkedin", "bluesky", "mastodon", "devto"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = _create_client()
    result = publish_next_job(client, args.platform)
    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()

"""Pipeline Watchdog — monitors stuck jobs, health backlogs, circuit states, and alerts the owner.

Runs as: python -m job_radar.pipeline.watchdog

Responsibilities:
1. Detects and resets jobs stuck in 'processing' (>30 min) back to 'pending'.
2. Computes per-stage backlogs and updates `pipeline_health`.
3. Quarantines jobs that have exceeded MAX_ATTEMPTS.
4. If new quarantines or open circuits are detected, sends a concise owner alert
   via Telegram and/or Resend email.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

STAGES = [
    "metadata",
    "alerts",
    "image",
    "post_text",
    "telegram",
    "discord",
    "slack",
    "bluesky",
    "mastodon",
    "linkedin",
    "x",
]


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def reset_all_stuck_jobs(client: Any, stuck_minutes: int = 30) -> Dict[str, int]:
    """Reset stuck 'processing' rows across all stages. Returns {stage: count_reset}."""
    from job_radar.pipeline.state_machine import reset_stuck

    results: Dict[str, int] = {}
    for stage in STAGES:
        count = reset_stuck(client, stage, stuck_minutes=stuck_minutes)
        if count > 0:
            results[stage] = count
            logger.warning("Watchdog reset %d stuck jobs for stage '%s'", count, stage)
    return results


def refresh_pipeline_health(client: Any) -> Dict[str, int]:
    """Compute and update current backlog for every stage."""
    from job_radar.pipeline.state_machine import get_stage_backlog
    from job_radar.pipeline.metrics import update_pipeline_health

    backlogs: Dict[str, int] = {}
    for stage in STAGES:
        backlog = get_stage_backlog(client, stage)
        backlogs[stage] = backlog
        update_pipeline_health(client, stage, backlog=backlog)
    return backlogs


def check_circuits(client: Any) -> List[Dict[str, Any]]:
    """Check for any open or half-open circuits."""
    resp = (
        client.table("service_circuits")
        .select("*")
        .neq("state", "closed")
        .execute()
    )
    return resp.data if resp and resp.data else []


def check_recent_quarantines(client: Any, hours: int = 2) -> List[Dict[str, Any]]:
    """Check for jobs quarantined within the last N hours."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    resp = (
        client.table("processing_quarantine")
        .select("*")
        .gte("created_at", cutoff)
        .is_("resolved_at", "null")
        .execute()
    )
    return resp.data if resp and resp.data else []


def notify_owner_if_needed(
    stuck_reset: Dict[str, int],
    open_circuits: List[Dict[str, Any]],
    recent_quarantines: List[Dict[str, Any]],
    backlogs: Dict[str, int],
) -> bool:
    """Send owner notification only if there are active anomalies."""
    has_issues = bool(stuck_reset or open_circuits or recent_quarantines)
    # Also check if any critical stage backlog is unusually high (> 100)
    high_backlogs = {s: b for s, b in backlogs.items() if b > 100}
    if high_backlogs:
        has_issues = True

    if not has_issues:
        logger.info("Watchdog: All systems healthy, no owner alert needed")
        return False

    # Format alert message
    lines = ["⚠️ *VisaLane Pipeline Watchdog Alert*", ""]

    if open_circuits:
        lines.append("🔌 *Open Circuit Breakers:*")
        for c in open_circuits:
            lines.append(f"  • `{c['name']}`: state={c['state']}, failures={c.get('consecutive_failures')}")
        lines.append("")

    if recent_quarantines:
        lines.append(f"🛑 *New Quarantined Jobs ({len(recent_quarantines)}):*")
        for q in recent_quarantines[:5]:
            lines.append(f"  • Job `{str(q.get('job_id'))[:8]}` ({q.get('stage')}): {q.get('reason')[:60]}")
        if len(recent_quarantines) > 5:
            lines.append(f"  • ... and {len(recent_quarantines) - 5} more")
        lines.append("")

    if stuck_reset:
        lines.append("🔄 *Stuck Jobs Reset:*")
        for stage, count in stuck_reset.items():
            lines.append(f"  • {stage}: {count} jobs reset to pending")
        lines.append("")

    if high_backlogs:
        lines.append("📈 *Elevated Backlogs:*")
        for stage, count in high_backlogs.items():
            lines.append(f"  • {stage}: {count} pending")
        lines.append("")

    alert_text = "\n".join(lines)

    # Send via Telegram
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": alert_text, "parse_mode": "Markdown"},
                timeout=15,
            )
            logger.info("Sent watchdog alert to Telegram")
        except Exception as e:
            logger.warning("Failed to send watchdog Telegram alert: %s", e)

    # Send via Resend Email if available
    resend_api_key = os.getenv("RESEND_API_KEY")
    admin_email = os.getenv("ADMIN_EMAIL") or os.getenv("EMAIL_TO")
    if resend_api_key and admin_email:
        try:
            import requests
            requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_api_key}", "Content-Type": "application/json"},
                json={
                    "from": "VisaLane Watchdog <alerts@visalane.online>",
                    "to": [admin_email],
                    "subject": "⚠️ VisaLane Pipeline Alert: Anomaly Detected",
                    "text": alert_text.replace("*", "").replace("`", ""),
                },
                timeout=15,
            )
            logger.info("Sent watchdog alert to Resend email")
        except Exception as e:
            logger.warning("Failed to send watchdog email alert: %s", e)

    return True


def run_watchdog() -> Dict[str, Any]:
    """Execute one watchdog cycle."""
    client = _create_client()

    logger.info("Starting pipeline watchdog check...")

    # 1. Reset stuck jobs
    stuck_reset = reset_all_stuck_jobs(client, stuck_minutes=30)

    # 2. Refresh stage backlogs in pipeline_health
    backlogs = refresh_pipeline_health(client)

    # 3. Check circuit breakers
    open_circuits = check_circuits(client)

    # 4. Check recent quarantines
    recent_quarantines = check_recent_quarantines(client, hours=2)

    # 5. Notify owner if anomalies exist
    notified = notify_owner_if_needed(stuck_reset, open_circuits, recent_quarantines, backlogs)

    summary = {
        "stuck_reset": stuck_reset,
        "backlogs": backlogs,
        "open_circuits": len(open_circuits),
        "recent_quarantines": len(recent_quarantines),
        "notified_owner": notified,
    }
    logger.info("Watchdog cycle complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_watchdog()

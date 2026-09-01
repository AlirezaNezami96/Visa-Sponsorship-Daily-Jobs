"""Pipeline Watchdog — monitors stuck jobs, health backlogs, circuit states, and alerts the owner.

Runs as: python -m job_radar.pipeline.watchdog

Responsibilities:
1. Detects and resets jobs stuck in 'processing' (>30 min) back to 'pending'.
2. Computes per-stage backlogs and updates `pipeline_health`.
3. Quarantines jobs that have exceeded MAX_ATTEMPTS.
4. If new quarantines or open circuits are detected, sends a concise owner alert
   via Telegram and/or Resend email with deduplication and alert throttling.
5. Provides circuit reset and quarantine resolution controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

# In-process / runtime alert deduplication state
_LAST_ALERT_FINGERPRINT: Optional[str] = None
_LAST_ALERT_TIMESTAMP: float = 0.0


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client  # type: ignore[attr-defined]
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def reset_all_circuits(client: Any) -> int:
    """Reset all open or half-open circuit breakers back to closed."""
    try:
        resp = (
            client.table("service_circuits")
            .update({
                "state": "closed",
                "consecutive_failures": 0,
                "cooldown_until": None,
                "last_failure_at": None,
            })
            .neq("state", "closed")
            .execute()
        )
        count = len(resp.data) if resp and resp.data else 0
        logger.info("Watchdog reset %d open/half-open circuit(s) to closed", count)
        return count
    except Exception as e:
        logger.warning("Failed to reset service_circuits: %s", e)
        return 0


def resolve_all_quarantines(client: Any, resolved_by: str = "watchdog_admin") -> int:
    """Mark all unresolved quarantined items as resolved."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        resp = (
            client.table("processing_quarantine")
            .update({
                "resolved_at": now_iso,
                "resolved_by": resolved_by,
            })
            .is_("resolved_at", "null")
            .execute()
        )
        count = len(resp.data) if resp and resp.data else 0
        logger.info("Watchdog resolved %d quarantined job(s)", count)
        return count
    except Exception as e:
        logger.warning("Failed to resolve processing_quarantine: %s", e)
        return 0


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


def _compute_alert_fingerprint(
    stuck_reset: Dict[str, int],
    open_circuits: List[Dict[str, Any]],
    recent_quarantines: List[Dict[str, Any]],
) -> str:
    """Compute deterministic fingerprint for alert deduplication."""
    payload = {
        "circuits": sorted([f"{c.get('name')}:{c.get('state')}" for c in open_circuits]),
        "quarantines": sorted([f"{q.get('job_id')}:{q.get('stage')}:{q.get('reason')}" for q in recent_quarantines]),
        "stuck": sorted([f"{k}:{v}" for k, v in stuck_reset.items()]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def notify_owner_if_needed(
    stuck_reset: Dict[str, int],
    open_circuits: List[Dict[str, Any]],
    recent_quarantines: List[Dict[str, Any]],
    backlogs: Dict[str, int],
    *,
    force: bool = False,
    cooldown_seconds: float = 3600.0,
) -> bool:
    """Send owner notification only if there are active anomalies with deduplication."""
    global _LAST_ALERT_FINGERPRINT, _LAST_ALERT_TIMESTAMP

    # 1. Global mute / disable check
    alerts_enabled = os.getenv("WATCHDOG_ALERTS_ENABLED", "true").lower() not in ("false", "0", "no", "off", "disable", "disabled")
    if not alerts_enabled or os.getenv("DISABLE_WATCHDOG_ALERTS") or os.getenv("WATCHDOG_MUTE"):
        logger.info("Watchdog: Outbound alerts are disabled or muted via configuration")
        return False

    has_issues = bool(stuck_reset or open_circuits or recent_quarantines)
    # Also check if any critical stage backlog is unusually high (> 100)
    high_backlogs = {s: b for s, b in backlogs.items() if b > 100}
    if high_backlogs:
        has_issues = True

    if not has_issues:
        logger.info("Watchdog: All systems healthy, no owner alert needed")
        return False

    # 2. Alert deduplication / cooldown check
    fingerprint = _compute_alert_fingerprint(stuck_reset, open_circuits, recent_quarantines)
    now = time.time()

    if not force and fingerprint == _LAST_ALERT_FINGERPRINT and (now - _LAST_ALERT_TIMESTAMP) < cooldown_seconds:
        logger.info("Watchdog: Suppressing duplicate alert (cooldown active: %.0fs remaining)", cooldown_seconds - (now - _LAST_ALERT_TIMESTAMP))
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
            reason_str = str(q.get("reason") or "")
            lines.append(f"  • Job `{str(q.get('job_id'))[:8]}` ({q.get('stage')}): {reason_str[:60]}")
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

    _LAST_ALERT_FINGERPRINT = fingerprint
    _LAST_ALERT_TIMESTAMP = now
    return True


def run_watchdog(
    *,
    reset_circuits_flag: bool = False,
    clear_quarantine_flag: bool = False,
) -> Dict[str, Any]:
    """Execute one watchdog cycle with optional admin resets."""
    client = _create_client()

    logger.info("Starting pipeline watchdog check...")

    if reset_circuits_flag:
        reset_all_circuits(client)

    if clear_quarantine_flag:
        resolve_all_quarantines(client)

    # 1. Reset stuck jobs
    stuck_reset = reset_all_stuck_jobs(client, stuck_minutes=30)

    # 2. Refresh stage backlogs in pipeline_health
    backlogs = refresh_pipeline_health(client)

    # 3. Check circuit breakers
    open_circuits = check_circuits(client)

    # 4. Check recent quarantines
    recent_quarantines = check_recent_quarantines(client, hours=2)

    # 5. Notify owner if anomalies exist (with deduplication)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="VisaLane Pipeline Watchdog")
    parser.add_argument("--reset-circuits", action="store_true", help="Reset all open/half-open circuits to closed")
    parser.add_argument("--clear-quarantine", action="store_true", help="Resolve all currently quarantined items")
    parser.add_argument("--reset-all", action="store_true", help="Reset circuits, resolve quarantines, and unstuck jobs")
    parser.add_argument("--mute", action="store_true", help="Run without sending any outbound notifications")

    args = parser.parse_args()

    if args.mute:
        os.environ["WATCHDOG_ALERTS_ENABLED"] = "false"

    reset_circuits_flag = args.reset_circuits or args.reset_all
    clear_quarantine_flag = args.clear_quarantine or args.reset_all

    run_watchdog(
        reset_circuits_flag=reset_circuits_flag,
        clear_quarantine_flag=clear_quarantine_flag,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()

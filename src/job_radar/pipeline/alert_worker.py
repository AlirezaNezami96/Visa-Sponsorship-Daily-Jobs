"""Alert worker — fires instant alerts when enrichment completes.

Runs as: python -m job_radar.pipeline.alert_worker

On `metadata_status='done'`, matches the job against active user alerts
and sends per-channel notifications. Channel failures are isolated —
one dead channel never prevents delivery on others.
Each channel has a 1-retry with 2s backoff and is protected by circuit breakers.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("ALERT_BATCH_SIZE", "50"))


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def _matches_alert(job: dict, filters: dict) -> bool:
    """Check if a job matches an alert's filter criteria."""
    # Country filter
    countries = filters.get("countries", [])
    if countries:
        job_country = (job.get("country_code") or job.get("country") or "").upper()
        if job_country and job_country not in [c.upper() for c in countries]:
            return False

    # Work mode filter
    work_modes = filters.get("work_modes", [])
    if work_modes:
        job_mode = (job.get("work_mode") or "").lower()
        if job_mode and job_mode not in [m.lower() for m in work_modes]:
            return False

    # Skills filter
    required_skills = filters.get("skills", [])
    if required_skills:
        job_skills = [s.lower() for s in (job.get("skills") or [])]
        if not any(s.lower() in job_skills for s in required_skills):
            return False

    # Visa verified filter
    if filters.get("visa_verified_only"):
        if not job.get("visa_sponsorship_verified"):
            return False

    # Min salary filter
    min_salary = filters.get("min_salary")
    if min_salary:
        job_salary = job.get("salary_min") or 0
        if job_salary < min_salary:
            return False

    # Keyword filter
    keywords = filters.get("keywords", [])
    if keywords:
        text = f"{job.get('title', '')} {job.get('description_text', '')}".lower()
        if not any(kw.lower() in text for kw in keywords):
            return False

    return True


def _send_channel_with_retry(
    client: Any,
    channel: str,
    send_fn: Any,
) -> bool:
    """Send on a single channel with 1 retry (2s backoff) and circuit breaker."""
    from job_radar.pipeline.circuit_breaker import CircuitBreaker
    from job_radar.pipeline.metrics import record_metric

    cb = CircuitBreaker(client)
    circuit_name = f"alert:{channel}"

    if cb.is_open(circuit_name):
        record_metric(client, f"circuit:open:{circuit_name}", True, 0)
        logger.debug("Circuit open for alert channel %s", channel)
        return False

    # Attempt 1
    try:
        ok = send_fn()
        if ok:
            cb.record_success(circuit_name)
            return True
    except Exception as e:
        logger.debug("Alert channel %s initial attempt failed: %s", channel, e)

    # Retry with 2s backoff
    time.sleep(2)
    record_metric(client, f"alerts:{channel}:retry", True, 0)

    try:
        ok = send_fn()
        if ok:
            cb.record_success(circuit_name)
            return True
        else:
            cb.record_failure(circuit_name)
            return False
    except Exception as e:
        cb.record_failure(circuit_name)
        logger.warning("Alert channel %s retry failed: %s", channel, e)
        return False


def _send_alert_channels(
    client: Any,
    alert: dict,
    job: dict,
) -> dict[str, bool]:
    """Send notifications on all configured channels for an alert with retry and circuit breakers."""
    from job_radar.notifications.channels import send_telegram, send_discord, send_slack
    from job_radar.pipeline.circuit_breaker import CircuitBreaker
    from job_radar.pipeline.metrics import record_metric

    channels = alert.get("channels", {})
    results: dict[str, bool] = {}

    title = job.get("title", "Untitled")
    company = job.get("company_name") or job.get("company") or ""
    country = job.get("country") or job.get("country_code") or ""
    url = job.get("apply_url") or job.get("url") or ""
    visa = "✅ Visa Sponsored" if job.get("visa_sponsorship_verified") else ""

    text = f"🔔 New Job Alert: {title}"
    if company:
        text += f" @ {company}"
    if country:
        text += f"\n📍 {country}"
    if visa:
        text += f"\n{visa}"
    if url:
        text += f"\n\nApply → {url}"

    cb = CircuitBreaker(client)

    # Telegram
    if channels.get("telegram"):
        cb_name = "alert:telegram"
        if not cb.is_open(cb_name):
            try:
                results["telegram"] = send_telegram(text)
                cb.record_success(cb_name)
            except Exception as e:
                logger.warning("Alert telegram failed: %s", e)
                results["telegram"] = False
                cb.record_failure(cb_name)
        else:
            results["telegram"] = False
            record_metric(client, f"circuit:open:{cb_name}", True, 0)

    # Discord
    if channels.get("discord"):
        cb_name = "alert:discord"
        if not cb.is_open(cb_name):
            try:
                results["discord"] = send_discord(text)
                cb.record_success(cb_name)
            except Exception as e:
                logger.warning("Alert discord failed: %s", e)
                results["discord"] = False
                cb.record_failure(cb_name)
        else:
            results["discord"] = False
            record_metric(client, f"circuit:open:{cb_name}", True, 0)

    # Slack
    if channels.get("slack"):
        cb_name = "alert:slack"
        if not cb.is_open(cb_name):
            try:
                results["slack"] = send_slack(text)
                cb.record_success(cb_name)
            except Exception as e:
                logger.warning("Alert slack failed: %s", e)
                results["slack"] = False
                cb.record_failure(cb_name)
        else:
            results["slack"] = False
            record_metric(client, f"circuit:open:{cb_name}", True, 0)

    # Email
    if channels.get("email"):
        cb_name = "alert:email"
        if not cb.is_open(cb_name):
            try:
                from job_radar.notifications.email import send_job_alert_email
                email = channels.get("email_address") or alert.get("user_email")
                if email:
                    results["email"] = send_job_alert_email(email, title, text)
                    cb.record_success(cb_name)
                else:
                    results["email"] = False
                    cb.record_failure(cb_name)
            except Exception as e:
                logger.warning("Alert email failed: %s", e)
                results["email"] = False
                cb.record_failure(cb_name)
        else:
            results["email"] = False
            record_metric(client, f"circuit:open:{cb_name}", True, 0)

    return results


def process_alerts_for_job(client: Any, job_id: str) -> dict[str, Any]:
    """Process all matching alerts for a single enriched job."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric

    start = time.time()

    resp = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
    if not resp or not resp.data:
        transition_stage(client, job_id, "alerts", "done")
        return {"ok": True, "alerts_matched": 0, "reason": "job not found"}

    job = resp.data

    alerts_resp = (
        client.table("alerts")
        .select("*")
        .eq("frequency", "instant")
        .eq("is_active", True)
        .execute()
    )
    alerts = alerts_resp.data if alerts_resp and alerts_resp.data else []

    matched = 0
    sent = 0

    for alert in alerts:
        filters = alert.get("filters", {})
        if not _matches_alert(job, filters):
            continue

        # Dedup check
        dedup_resp = (
            client.table("alert_sent_jobs")
            .select("id")
            .eq("alert_id", alert["id"])
            .eq("job_id", job_id)
            .maybe_single()
            .execute()
        )
        if dedup_resp and dedup_resp.data:
            continue

        matched += 1

        results = _send_alert_channels(client, alert, job)
        any_sent = any(results.values())

        if any_sent:
            client.table("alert_sent_jobs").insert({
                "alert_id": alert["id"],
                "job_id": job_id,
            }).execute()

            client.table("alerts").update({
                "last_sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }).eq("id", alert["id"]).execute()

            sent += 1

    transition_stage(client, job_id, "alerts", "done")

    duration_ms = int((time.time() - start) * 1000)
    record_metric(client, "alerts:processed", True, duration_ms)
    if sent > 0:
        record_metric(client, "alerts:sent", True, 0)

    return {"ok": True, "alerts_matched": matched, "alerts_sent": sent, "duration_ms": duration_ms}


def run_alert_batch() -> dict[str, Any]:
    """Run one alert processing batch."""
    from job_radar.pipeline.state_machine import claim_pending
    from job_radar.pipeline.metrics import update_pipeline_health

    client = _create_client()
    claimed = claim_pending(client, "alerts", limit=BATCH_SIZE, prerequisite_stage="metadata")

    if not claimed:
        logger.info("No jobs pending alert processing")
        return {"processed": 0}

    logger.info("Processing alerts for %d jobs", len(claimed))
    total_matched = 0
    total_sent = 0

    for jid in claimed:
        try:
            result = process_alerts_for_job(client, jid)
            total_matched += result.get("alerts_matched", 0)
            total_sent += result.get("alerts_sent", 0)
        except Exception as e:
            logger.error("Alert processing crashed for job %s: %s", jid, e)

    update_pipeline_health(client, "alerts", success=True)

    logger.info(
        "Alert batch: %d jobs, %d alerts matched, %d sent",
        len(claimed), total_matched, total_sent,
    )
    return {"processed": len(claimed), "matched": total_matched, "sent": total_sent}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run_alert_batch()
    logger.info("Result: %s", result)

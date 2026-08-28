"""End-to-end post-scrape orchestration for the VisaLane tables.

Call order (each stage fail-open and independently gated):
  1. writer.sync_jobs          -> companies + jobs rows (dedup by canonical URL)
  2. dispatch_alerts_stage     -> alert matching, alert_sent_jobs, delivery
  3. social_queue.enqueue_jobs -> social_post_queue rows
  4. enrichment_stage          -> job_people rows (opt-in; slow)
  5. mark processed flags + analytics + scrape_runs bookkeeping

Entry points:
  - sync_qualified_jobs(jobs): inline, right after a scrape run
  - dispatch_pending():        cron/CLI mode over unprocessed DB rows
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from job_radar.visalane.db import get_service_client
from job_radar.visalane.writer import sync_jobs

logger = logging.getLogger(__name__)


def _esc(text: Any) -> str:
    import html as _html

    return _html.escape(str(text or ""), quote=True)


def build_alert_email_html(alert_name: str, jobs: list[dict[str, Any]]) -> str:
    """Score-pill styled alert email reusing the radar digest look & feel."""
    rows = []
    for job in jobs[:20]:
        company = _esc(job.get("company"))
        title = _esc(job.get("title"))
        location = _esc(job.get("location_raw") or job.get("location") or "")
        conf = job.get("visa_sponsorship_confidence")
        url = _esc(job.get("apply_url") or job.get("url") or "#")
        pill = ""
        if conf is not None:
            color = "#3F7D53" if int(conf) >= 70 else ("#C1892F" if int(conf) >= 40 else "#999")
            pill = (
                f'<span style="background:{color};color:#fff;border-radius:10px;'
                f'padding:2px 8px;font-size:12px;">visa {int(conf)}%</span>'
            )
        verified = (
            ' <span style="color:#3F7D53;font-weight:bold;">✓ verified sponsor</span>'
            if job.get("visa_sponsorship_verified")
            else ""
        )
        rows.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid #eee;">'
            f'<a href="{url}" style="color:#14213D;font-weight:bold;text-decoration:none;">{title}</a> {pill}{verified}<br/>'
            f'<span style="color:#555;font-size:14px;">{company} — {location}</span>'
            f"</td></tr>"
        )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:auto;">'
        f'<h2 style="color:#14213D;">Your alert “{_esc(alert_name)}” matched {len(jobs)} new job(s)</h2>'
        '<table width="100%" cellpadding="0" cellspacing="0">' + "".join(rows) + "</table>"
        '<p style="color:#777;font-size:12px;">VisaLane — visa-sponsorship jobs, verified.</p>'
        "</div>"
    )


def _social_card_factory(client):
    """Digest-card factory for social staging (None when cards are disabled)."""
    from job_radar.social.card_pipeline import make_card_factory

    storage = None
    try:
        from job_radar.storage.supabase_client import SupabaseStorageClient

        candidate = SupabaseStorageClient()
        if candidate.is_configured:
            storage = candidate
    except Exception as exc:
        logger.debug("card storage unavailable: %s", exc)
    return make_card_factory(client, storage=storage)


def _dispatch_alert_to_channels(
    client,
    alert: dict[str, Any],
    jobs: list[dict[str, Any]],
) -> list[str]:
    """Deliver one alert's matches over its configured channels.

    Delegates to `alert_delivery.deliver_alert` (GAP 5): template rendering,
    per-channel retry-once, alert_delivery_logs bookkeeping.
    """
    from job_radar.visalane.alert_delivery import deliver_alert

    return deliver_alert(client, alert, jobs)


def dispatch_alerts_stage(client, new_jobs: list[dict[str, Any]]) -> int:
    """Match new jobs against active alerts, record sent jobs, deliver, emit analytics."""
    if not new_jobs:
        return 0
    try:
        alerts_res = client.table("alerts").select("*").eq("is_active", True).execute()
    except Exception as exc:
        logger.warning("alerts fetch failed: %s", exc)
        return 0
    alerts = alerts_res.data or []
    if not alerts:
        return 0

    from job_radar.analytics import emit_event
    from job_radar.visalane.alert_matching import match_jobs_to_alerts

    matched = match_jobs_to_alerts(new_jobs, alerts)
    sent_total = 0
    for alert in alerts:
        matches = matched.get(str(alert.get("id")))
        if not matches:
            continue

        # Per-alert dedup: drop jobs already sent for this alert.
        job_ids = [j["job_db_id"] for j in matches if j.get("job_db_id")]
        try:
            already = (
                client.table("alert_sent_jobs")
                .select("job_id")
                .in_("job_id", job_ids)
                .eq("alert_id", alert["id"])
                .execute()
            )
            already_ids = {r["job_id"] for r in (already.data or [])}
        except Exception:
            already_ids = set()
        fresh = [j for j in matches if j.get("job_db_id") and j["job_db_id"] not in already_ids]
        if not fresh:
            continue

        used_channels = _dispatch_alert_to_channels(client, alert, fresh)
        if not used_channels:
            logger.info("Alert %s: matched %d jobs but no channel deliverable", alert.get("name"), len(fresh))
            continue

        try:
            client.table("alert_sent_jobs").insert(
                [{"alert_id": alert["id"], "job_id": j["job_db_id"]} for j in fresh]
            ).execute()
            client.table("alerts").update({"last_sent_at": datetime.datetime.now(datetime.UTC).isoformat()}).eq(
                "id", alert["id"]
            ).execute()
        except Exception as exc:
            logger.warning("alert_sent_jobs bookkeeping failed: %s", exc)

        sent_total += len(fresh)
        emit_event(
            "alert_sent",
            user_id=alert.get("user_id"),
            metadata={"alert_id": alert.get("id"), "jobs": len(fresh), "channels": used_channels},
        )
    return sent_total


def _mark_processed(client, job_ids: list[str], columns: list[str]) -> None:
    if not job_ids:
        return
    payload = {col: True for col in columns}
    try:
        client.table("jobs").update(payload).in_("id", job_ids).execute()
    except Exception as exc:
        logger.warning("mark processed failed: %s", exc)


def sync_qualified_jobs(
    jobs: list[dict[str, Any]],
    *,
    source_name: str = "radar",
    do_alerts: bool = True,
    do_social: bool = True,
    do_enrichment: bool = False,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Inline post-scrape sync of enriched pipeline jobs into the VisaLane DB."""
    stats: dict[str, Any] = {"inserted": 0, "skipped": 0, "alerts_sent": 0, "social_queued": 0, "contacts": 0}

    client = get_service_client()
    if client is None:
        logger.info("VisaLane sync skipped — Supabase not configured.")
        return stats

    from job_radar.analytics import emit_event, flush_events

    run_row = {"source_name": source_name, "status": "running"}
    run_id = None
    try:
        res = client.table("scrape_runs").insert(run_row).execute()
        run_id = res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.debug("scrape_runs insert failed: %s", exc)

    try:
        inserted, skipped = sync_jobs(client, jobs, source_name=source_name)
        stats["inserted"], stats["skipped"] = inserted, skipped
        new_jobs = [j for j in jobs if j.get("job_db_id")]

        if do_alerts and new_jobs:
            stats["alerts_sent"] = dispatch_alerts_stage(client, new_jobs)
            _mark_processed(client, [j["job_db_id"] for j in new_jobs], ["processed_alerts"])

        if do_social and new_jobs:
            from job_radar.visalane.social_queue import enqueue_jobs

            stats["social_queued"] = enqueue_jobs(
                client, new_jobs, platforms=platforms, card_factory=_social_card_factory(client)
            )
            _mark_processed(client, [j["job_db_id"] for j in new_jobs], ["processed_social"])

        if do_enrichment and new_jobs:
            from job_radar.visalane.enrichment_stage import enrich_job_contacts

            for job in new_jobs:
                stats["contacts"] += enrich_job_contacts(client, job)
            _mark_processed(client, [j["job_db_id"] for j in new_jobs], ["processed_enrichment"])

        if inserted:
            emit_event("jobs_added", metadata={"count": inserted, "source": source_name})
        final_status = "completed"
        error_message = None
    except Exception as exc:
        final_status = "failed"
        error_message = str(exc)[:1000]
        raise
    finally:
        if run_id:
            try:
                client.table("scrape_runs").update(
                    {
                        "status": final_status,
                        "error_message": error_message,
                        "jobs_found": len(jobs),
                        "jobs_added": stats["inserted"],
                        "completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    }
                ).eq("id", run_id).execute()
            except Exception as exc:
                logger.debug("scrape_runs finalize failed: %s", exc)
        flush_events()

    logger.info("VisaLane sync complete: %s", stats)
    return stats


def dispatch_pending(
    *,
    do_alerts: bool = True,
    do_social: bool = True,
    do_enrichment: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Cron mode: process jobs rows still marked unprocessed in the database.

    Used by the alert-dispatch / social-post / enrichment GitHub workflows so
    processing happens even when the scrape runner and processors differ.
    """
    stats: dict[str, Any] = {"processed": 0, "alerts_sent": 0, "social_queued": 0, "contacts": 0}
    client = get_service_client()
    if client is None:
        logger.info("dispatch_pending skipped — Supabase not configured.")
        return stats

    from job_radar.analytics import flush_events

    try:
        res = (
            client.table("jobs")
            .select("*, companies(name)")
            .eq("status", "active")
            .or_("processed_alerts.eq.false,processed_social.eq.false,processed_enrichment.eq.false")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        logger.warning("dispatch_pending fetch failed: %s", exc)
        return stats

    rows = res.data or []
    if not rows:
        logger.info("dispatch_pending: nothing to process.")
        return stats

    jobs = []
    for row in rows:
        company = row.pop("companies", None) or {}
        job = dict(row)
        job["company"] = company.get("name", "") if isinstance(company, dict) else ""
        job["company_db_id"] = row.get("company_id")
        job["job_db_id"] = row.get("id")
        job["location"] = row.get("location_raw") or ""
        job["url"] = row.get("source_url")
        jobs.append(job)

    unprocessed_alerts = [j for j in jobs if not j.get("processed_alerts")]
    unprocessed_social = [j for j in jobs if not j.get("processed_social")]
    unprocessed_enrichment = [j for j in jobs if not j.get("processed_enrichment")]

    if do_alerts and unprocessed_alerts:
        stats["alerts_sent"] = dispatch_alerts_stage(client, unprocessed_alerts)
        _mark_processed(client, [j["job_db_id"] for j in unprocessed_alerts], ["processed_alerts"])

    if do_social and unprocessed_social:
        from job_radar.visalane.social_queue import enqueue_jobs

        stats["social_queued"] = enqueue_jobs(client, unprocessed_social, card_factory=_social_card_factory(client))
        _mark_processed(client, [j["job_db_id"] for j in unprocessed_social], ["processed_social"])

    if do_enrichment and unprocessed_enrichment:
        from job_radar.visalane.enrichment_stage import enrich_job_contacts

        for job in unprocessed_enrichment:
            stats["contacts"] += enrich_job_contacts(client, job)
        _mark_processed(client, [j["job_db_id"] for j in unprocessed_enrichment], ["processed_enrichment"])

    stats["processed"] = len(jobs)
    flush_events()
    logger.info("dispatch_pending complete: %s", stats)
    return stats

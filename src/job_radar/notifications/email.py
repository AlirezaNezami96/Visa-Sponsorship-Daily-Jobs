"""Email delivery module for job digests.

Supports:
1. Resend API (free 3,000 emails/mo)
2. SendGrid API (free 100 emails/day)
3. Gmail SMTP with App Passwords
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
import requests as http_requests

from job_radar.notifications.renderers import (
    build_justjoin_html,
    build_legacy_html,
    build_radar_html,
    build_worker_run_alert_html,
)

logger = logging.getLogger(__name__)


def send_radar_digest(
    internships: List[dict],
    engineers: List[dict],
    health_info: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    send_empty: bool = False,
    show_visa_tag: bool = True,
) -> bool:
    """Send the upgraded dual-track AI Internship & Engineer remote job digest."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    total_jobs = len(internships) + len(engineers)

    if total_jobs == 0 and not send_empty:
        logger.info("No new matching AI jobs today — skipping email digest.")
        return False

    sorted_internships = sorted(
        internships,
        key=lambda j: (j.get("relevance_score", 0), str(j.get("date_posted", ""))),
        reverse=True,
    )
    sorted_engineers = sorted(
        engineers,
        key=lambda j: (j.get("relevance_score", 0), str(j.get("date_posted", ""))),
        reverse=True,
    )

    subject = (
        f"🧠 {total_jobs} new AI roles today ({len(internships)} internships, {len(engineers)} engineer)"
        if total_jobs > 0
        else "🧠 AI Job Radar — No new roles found today"
    )

    html_content = build_radar_html(
        internships=sorted_internships,
        engineers=sorted_engineers,
        health_info=health_info or {},
        show_visa_tag=show_visa_tag,
    )

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    logger.info("AI Radar digest sent via %s: %d total jobs (%d intern, %d eng)", provider, total_jobs, len(internships), len(engineers))
    return True


def send_email(report: list, provider: str = None):
    """Send legacy visa job digest."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    if not report:
        logger.info("No new jobs found — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html_content = build_legacy_html(report, total_jobs)
    subject = f"🌐 Visa-Sponsor Job Digest — {len(report)} companies, {total_jobs} jobs"

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")


def send_junior_ai_email(report: list, provider: str = None):
    """Send junior AI job digest, sorted by ATS score where available."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    if not report:
        logger.info("No new Junior AI jobs — skipping email.")
        return

    # Sort each company's jobs by ATS score descending (None → 0 for sorting)
    sorted_report = []
    for company, jobs in report:
        sorted_jobs = sorted(
            jobs,
            key=lambda j: (j.get("resume_match") or {}).get("ats_score") or 0,
            reverse=True,
        )
        sorted_report.append((company, sorted_jobs))

    total_jobs = sum(len(jobs) for _, jobs in sorted_report)
    html_content = build_legacy_html(sorted_report, total_jobs)
    subject = f"🤖 Junior AI & ML Job Digest — {len(sorted_report)} companies, {total_jobs} jobs"

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")


def send_justjoin_email(
    ai_jobs: List[dict],
    mobile_jobs: List[dict],
    provider: Optional[str] = None,
):
    """Send JustJoin.it daily digest grouped by AI and Mobile tracks."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    total_jobs = len(ai_jobs) + len(mobile_jobs)
    if total_jobs == 0:
        logger.info("No new JustJoin.it jobs today — skipping email.")
        return

    # Sort each track's jobs by ATS score descending where available
    sorted_ai = sorted(
        ai_jobs,
        key=lambda j: (j.get("resume_match") or {}).get("ats_score") or 0,
        reverse=True,
    )
    sorted_mobile = sorted(
        mobile_jobs,
        key=lambda j: (j.get("resume_match") or {}).get("ats_score") or 0,
        reverse=True,
    )

    subject = f"🚀 JustJoin.it Digest — {len(sorted_ai)} AI/ML, {len(sorted_mobile)} Mobile ({total_jobs} total jobs)"
    html_content = build_justjoin_html(sorted_ai, sorted_mobile)

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    logger.info("JustJoin email sent via %s: %d total jobs (%d AI, %d Mobile)", provider, total_jobs, len(sorted_ai), len(sorted_mobile))


def send_worker_run_alert(
    run_id: str = "local-run",
    status: str = "completed",
    inputs: Optional[Dict[str, Any]] = None,
    stats: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    run_url: Optional[str] = None,
    dataset_url: Optional[str] = None,
    provider: Optional[str] = None,
    to_email: Optional[str] = None,
) -> bool:
    """Send an immediate email notification when a worker / Apify Actor run finishes or fails.

    Uses Resend by default (or configured EMAIL_PROVIDER).
    Fails safely and returns False if email credentials are not set.
    """
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    target_to = (to_email or os.environ.get("EMAIL_TO", "")).strip()

    # If neither provider API key nor EMAIL_TO is set, gracefully skip without failing
    if not target_to:
        logger.info("EMAIL_TO not configured. Skipping worker run notification email.")
        return False

    if provider == "resend" and not os.environ.get("RESEND_API_KEY"):
        logger.info("RESEND_API_KEY not configured. Skipping worker run notification email.")
        return False
    elif provider == "sendgrid" and not os.environ.get("SENDGRID_API_KEY"):
        logger.info("SENDGRID_API_KEY not configured. Skipping worker run notification email.")
        return False
    elif provider == "gmail" and not (os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")):
        logger.info("GMAIL_USER/GMAIL_APP_PASSWORD not configured. Skipping worker run notification email.")
        return False

    stats = stats or {}
    emitted_count = stats.get("totalEmitted", stats.get("emittedCount", 0))
    short_run_id = run_id[:8] if run_id else "run"

    if status.lower() in ("completed", "success", "succeeded"):
        subject = f"⚡ Worker Run Completed ({emitted_count} jobs found) [{short_run_id}]"
    elif status.lower() in ("timed_out", "timeout"):
        subject = f"⏱️ Worker Run Timed Out ({emitted_count} jobs) [{short_run_id}]"
    elif status.lower() in ("started", "running"):
        subject = f"🚀 Worker Run Started [{short_run_id}]"
    else:
        subject = f"❌ Worker Run Failed [{short_run_id}]"

    html_content = build_worker_run_alert_html(
        run_id=run_id,
        status=status,
        inputs=inputs,
        stats=stats,
        error_message=error_message,
        run_url=run_url,
        dataset_url=dataset_url,
    )

    try:
        if provider == "resend":
            _send_via_resend(subject, html_content, to_email=target_to)
        elif provider == "sendgrid":
            _send_via_sendgrid(subject, html_content, to_email=target_to)
        elif provider == "gmail":
            _send_via_gmail_smtp(subject, html_content, to_email=target_to)
        else:
            logger.warning("Unknown email provider '%s'. Worker alert not sent.", provider)
            return False

        logger.info(
            "Worker run alert email successfully sent via %s to %s (run_id: %s, status: %s)",
            provider,
            target_to,
            run_id,
            status,
        )
        return True
    except Exception as e:
        logger.warning("Failed to send worker run email alert: %s", e)
        return False


def _send_via_resend(subject: str, html: str, to_email: Optional[str] = None):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY not set. Get one free at https://resend.com")

    target_email = to_email or os.environ.get("EMAIL_TO", "")
    if not target_email:
        raise EnvironmentError("EMAIL_TO not set.")

    from_email = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
    r = http_requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [target_email],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    r.raise_for_status()


def _send_via_sendgrid(subject: str, html: str, to_email: Optional[str] = None):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise EnvironmentError("SENDGRID_API_KEY not set.")
    target_email = to_email or os.environ.get("EMAIL_TO", "")
    if not target_email:
        raise EnvironmentError("EMAIL_TO not set.")
    from_email = os.environ.get("EMAIL_FROM", "jobs@yourdomain.com")

    r = http_requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": target_email}]}],
            "from": {"email": from_email},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}],
        },
        timeout=30,
    )
    r.raise_for_status()


def _send_via_gmail_smtp(subject: str, html: str, to_email: Optional[str] = None):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    target_email = to_email or os.environ.get("EMAIL_TO", "")

    if not all([gmail_user, gmail_pass, target_email]):
        raise EnvironmentError(
            "GMAIL_USER, GMAIL_APP_PASSWORD, and EMAIL_TO must all be set."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = target_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, target_email, msg.as_string())


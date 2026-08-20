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
    build_legacy_html,
    build_radar_html,
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
    """Send legacy junior ai digest."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    if not report:
        logger.info("No new Junior AI jobs — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html_content = build_legacy_html(report, total_jobs)
    subject = f"🤖 Junior AI & ML Job Digest — {len(report)} companies, {total_jobs} jobs"

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")


def _send_via_resend(subject: str, html: str):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY not set. Get one free at https://resend.com")

    to_email = os.environ.get("EMAIL_TO", "")
    if not to_email:
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
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    r.raise_for_status()


def _send_via_sendgrid(subject: str, html: str):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise EnvironmentError("SENDGRID_API_KEY not set.")
    to_email = os.environ.get("EMAIL_TO", "")
    if not to_email:
        raise EnvironmentError("EMAIL_TO not set.")
    from_email = os.environ.get("EMAIL_FROM", "jobs@yourdomain.com")

    r = http_requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}],
        },
        timeout=30,
    )
    r.raise_for_status()


def _send_via_gmail_smtp(subject: str, html: str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    to_email = os.environ.get("EMAIL_TO", "")

    if not all([gmail_user, gmail_pass, to_email]):
        raise EnvironmentError(
            "GMAIL_USER, GMAIL_APP_PASSWORD, and EMAIL_TO must all be set."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, to_email, msg.as_string())

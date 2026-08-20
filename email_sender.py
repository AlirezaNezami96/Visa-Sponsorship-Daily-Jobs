"""Email delivery module for job digests.

Supports:
1. Resend API (free 3,000 emails/mo)
2. SendGrid API (free 100 emails/day)
3. Gmail SMTP with App Passwords

Includes a dual-track HTML template for AI internships & early-career engineer roles
with relevance explanations, remote badges, direct apply buttons, and run health stats.
"""
from __future__ import annotations

import datetime
import html as html_lib
import logging
import os
from typing import Any, Dict, List, Optional
import requests as http_requests

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Dual-Track AI Radar Email Dispatcher
# ------------------------------------------------------------------ #

def send_radar_digest(
    internships: List[dict],
    engineers: List[dict],
    health_info: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    send_empty: bool = False,
    show_visa_tag: bool = True,
) -> bool:
    """Send the upgraded dual-track AI Internship & Engineer remote job digest.
    
    Returns:
        True if email was sent, False if skipped.
    """
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    total_jobs = len(internships) + len(engineers)

    if total_jobs == 0 and not send_empty:
        logger.info("No new matching AI jobs today — skipping email digest.")
        return False

    # Sort each track: highest relevance score first, then recency
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

    html_content = _build_radar_html(
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


def _render_job_card(j: dict, accent_color: str = "#6366F1", show_visa_tag: bool = True) -> str:
    """Render a clean, responsive job card for HTML email."""
    title = html_lib.escape(j.get("title", "Untitled Role"))
    company = html_lib.escape(j.get("company", "Company"))
    url = html_lib.escape(j.get("url", "#"))
    location = html_lib.escape(j.get("location", "Remote"))
    why = html_lib.escape(j.get("why_matched", ""))
    score = j.get("relevance_score", 0)
    source = html_lib.escape(j.get("source", "Direct ATS"))
    salary = html_lib.escape(j.get("salary")) if j.get("salary") else None
    has_visa = j.get("visa_sponsorship") is True

    # Remote pill
    remote_scope = j.get("remote_scope", "worldwide")
    allowed_regs = j.get("allowed_regions", [])
    if remote_scope == "worldwide" or "worldwide" in location.lower():
        remote_badge = "🌍 Remote (Worldwide)"
    elif allowed_regs and allowed_regs != ["Worldwide"]:
        remote_badge = f"📍 Remote ({', '.join(allowed_regs[:2])})"
    else:
        remote_badge = f"📍 {location}"

    badges = [
        f'<span style="background:#EEF2FF;color:#4338CA;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">{remote_badge}</span>',
        f'<span style="background:#F0FDF4;color:#166534;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🎯 {score}% Match</span>',
    ]
    if salary:
        badges.append(f'<span style="background:#FEF3C7;color:#92400E;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:500;">💰 {salary}</span>')
    if show_visa_tag and has_visa:
        badges.append('<span style="background:#FDF2F8;color:#9D174D;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🛂 Visa Sponsor</span>')
    if source:
        badges.append(f'<span style="background:#F1F5F9;color:#475569;padding:3px 8px;border-radius:4px;font-size:11px;">🏷️ {source}</span>')

    why_block = ""
    if why:
        why_block = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#F8FAFC;border-left:3px solid {accent_color};border-radius:0 4px 4px 0;font-size:13px;color:#334155;line-height:1.4;">'
            f'💡 <i>{why}</i>'
            f'</div>'
        )

    return f"""
    <div style="margin-bottom:16px;padding:16px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
        <div>
          <div style="font-size:13px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{company}</div>
          <div style="font-size:16px;font-weight:700;color:#0F172A;margin-top:2px;">
            <a href="{url}" style="color:#1E293B;text-decoration:none;">{title}</a>
          </div>
        </div>
      </div>
      <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">
        {' '.join(badges)}
      </div>
      {why_block}
      <div style="margin-top:12px;text-align:right;">
        <a href="{url}" target="_blank" style="display:inline-block;background:{accent_color};color:#FFFFFF;padding:6px 14px;font-size:13px;font-weight:600;text-decoration:none;border-radius:6px;">Apply Directly →</a>
      </div>
    </div>
    """


def _build_radar_html(
    internships: List[dict],
    engineers: List[dict],
    health_info: Dict[str, Any],
    show_visa_tag: bool = True,
) -> str:
    """Build modern, mobile-friendly HTML digest for AI Radar."""
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    total_jobs = len(internships) + len(engineers)
    companies_count = health_info.get("companies_scanned", 0)
    boards_count = health_info.get("boards_scanned", 0)
    errors_count = health_info.get("errors", 0)

    html_parts = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>',
        '<body style="margin:0;padding:20px 0;background-color:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;">',
        '<div style="max-width:640px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid #E2E8F0;">',
        
        # Header Banner
        '<div style="background:linear-gradient(135deg, #0F172A 0%, #1E1B4B 40%, #4338CA 100%);padding:28px 24px;color:#FFFFFF;text-align:center;">',
        '<h1 style="margin:0;font-size:22px;font-weight:800;letter-spacing:-0.5px;">🧠 AI & ML Remote Job Radar</h1>',
        f'<p style="margin:8px 0 0 0;font-size:14px;color:#C7D2FE;">'
        f'{len(internships)} Internships · {len(engineers)} Early-Career Engineers · {date_str}</p>',
        '</div>',

        # Main Body Content
        '<div style="padding:24px 20px;">',
    ]

    # 1. Internships Track
    html_parts.append(
        '<div style="margin-bottom:28px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #E0E7FF;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:18px;color:#1E1B4B;font-weight:700;">🎓 AI & Machine Learning Internships</h2>'
        f'<span style="margin-left:auto;background:#EEF2FF;color:#4338CA;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(internships)}</span>'
        '</div>'
    )
    if internships:
        for job in internships:
            html_parts.append(_render_job_card(job, accent_color="#4F46E5", show_visa_tag=show_visa_tag))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new AI internship openings matched today.</p>')
    html_parts.append('</div>')

    # 2. Engineer Track
    html_parts.append(
        '<div style="margin-bottom:20px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #D1FAE5;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:18px;color:#064E3B;font-weight:700;">🚀 Early-Career AI & ML Engineers</h2>'
        f'<span style="margin-left:auto;background:#ECFDF5;color:#059669;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(engineers)}</span>'
        '</div>'
    )
    if engineers:
        for job in engineers:
            html_parts.append(_render_job_card(job, accent_color="#059669", show_visa_tag=show_visa_tag))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new early-career engineer openings matched today.</p>')
    html_parts.append('</div>')

    # Footer and Health Stats
    html_parts.extend([
        '</div>',  # end padding
        '<div style="background:#F1F5F9;padding:16px 20px;border-top:1px solid #E2E8F0;font-size:12px;color:#64748B;line-height:1.5;">',
        f'<div style="font-weight:600;color:#475569;margin-bottom:4px;">'
        f'⚡ Radar Health: Scanned {companies_count} companies + {boards_count} public APIs · {errors_count} error(s)</div>',
        '<div>Filtering: AI/ML specific · 0–2 yrs & Internships only · Worldwide & Region-Restricted Remote.</div>',
        '<div style="margin-top:6px;font-size:11px;color:#94A3B8;">'
        'Automated AI Job Radar · Powered by GitHub Actions</div>',
        '</div>',
        '</div>',  # end max-width container
        '</body></html>',
    ])

    return "\n".join(html_parts)


# ------------------------------------------------------------------ #
#  Legacy Senders (Kept for backwards compatibility)
# ------------------------------------------------------------------ #

def send_email(report: list, provider: str = None):
    """Send legacy visa job digest."""
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
    if not report:
        logger.info("No new jobs found — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html_content = _build_legacy_html(report, total_jobs)
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
    html_content = _build_legacy_html(report, total_jobs)
    subject = f"🤖 Junior AI & ML Job Digest — {len(report)} companies, {total_jobs} jobs"

    if provider == "resend":
        _send_via_resend(subject, html_content)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html_content)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html_content)
    else:
        raise ValueError(f"Unknown email provider: {provider}")


def _build_legacy_html(report: list, total_jobs: int) -> str:
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #4338CA 0%, #6366F1 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        f'<h1 style="margin: 0; color: white; font-size: 22px;">Job Digest</h1>',
        f'<p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">{len(report)} companies · {total_jobs} new jobs</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #fff; border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 12px 12px;">',
    ]
    for company, jobs in report:
        html_parts.append(f'<h2 style="margin: 20px 0 8px; font-size: 17px; color: #333;">{company}</h2>')
        html_parts.append('<ul style="margin: 0; padding-left: 20px;">')
        for j in jobs:
            loc = j.get("location", "")
            html_parts.append(f'<li style="margin: 6px 0;"><a href="{j["url"]}">{j["title"]}</a> {loc}</li>')
        html_parts.append('</ul>')
    html_parts.append('</div></div>')
    return "\n".join(html_parts)


# ------------------------------------------------------------------ #
#  Low-Level Email Transports
# ------------------------------------------------------------------ #

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

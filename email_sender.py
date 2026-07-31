import json
import os
import requests as http_requests

# --- Config ---
# Supported: "resend", "sendgrid", "gmail"
# Set via EMAIL_PROVIDER env var. Default: resend.

def send_email(report: list, provider: str = None):
    """Send the job digest email.
    report: list of (company_name, [job_dicts]) tuples.
    """
    provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()

    if not report:
        print("No new jobs found — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html = _build_html(report, total_jobs)
    subject = f"\U0001f4e8 Visa-Sponsor Job Digest — {len(report)} companies, {total_jobs} jobs"

    if provider == "resend":
        _send_via_resend(subject, html)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    print(f"Email sent via {provider}: {total_jobs} jobs from {len(report)} companies")


def _build_html(report: list, total_jobs: int) -> str:
    """Build a clean HTML email body."""
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        f'<h1 style="margin: 0; color: white; font-size: 22px;">\U0001f310 Visa-Sponsor Job Digest</h1>',
        f'<p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">{len(report)} companies \u00b7 {total_jobs} new jobs \u00b7 {__import__("datetime").datetime.now().strftime("%b %d, %Y")}</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #fff; border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 12px 12px;">',
    ]

    for company, jobs in report:
        html_parts.append(f'<h2 style="margin: 20px 0 8px; font-size: 17px; color: #333;">{company}</h2>')
        html_parts.append('<ul style="margin: 0; padding-left: 20px;">')
        for j in jobs:
            if "error" in j:
                html_parts.append(f'<li style="margin: 4px 0; color: #999;">\u26a0\ufe0f {j["error"]}</li>')
            else:
                loc = j.get("location", "")
                dept = j.get("department", "")
                meta = " \u00b7 ".join(filter(None, [loc, dept]))
                html_parts.append(
                    f'<li style="margin: 6px 0; line-height: 1.5;">'
                    f'<a href="{j["url"]}" style="color: #4f46e5; text-decoration: none; font-weight: 500;">{j["title"]}</a>'
                    f'{"<span style=\"color: #888; font-size: 13px;\"> " + meta + "</span>" if meta else ""}'
                    f'</li>'
                )
        html_parts.append('</ul>')

    html_parts.extend([
        '</div>',
        '<p style="text-align: center; color: #aaa; font-size: 12px; margin-top: 16px;">'
        'Powered by visa-job-scraper \u00b7 Update your keywords in filter.py</p>',
        '</div>',
    ])

    return "\n".join(html_parts)


def _send_via_resend(subject: str, html: str):
    """Send email via Resend (free: 3,000 emails/month).
    Needs RESEND_API_KEY env var.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY not set. Get one free at https://resend.com")

    to_email = os.environ.get("EMAIL_TO", "")
    if not to_email:
        raise EnvironmentError("EMAIL_TO not set. e.g. you@example.com")

    from_email = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
    # Note: to use a custom domain, you must verify it in Resend.
    # The default 'onboarding@resend.dev' works for testing.

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
    result = r.json()
    print(f"  Resend response: {result.get('id', 'sent')}")


def _send_via_sendgrid(subject: str, html: str):
    """Send email via SendGrid (free: 100 emails/day).
    Needs SENDGRID_API_KEY and EMAIL_TO env vars.
    """
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
    print("  SendGrid: sent successfully")


def _send_via_gmail_smtp(subject: str, html: str):
    """Send email via Gmail SMTP (free, rate-limited to ~500/day).
    Needs GMAIL_APP_PASSWORD env var (not your regular password).
    Set up: Google Account > Security > 2-Step Verification > App passwords
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    to_email = os.environ.get("EMAIL_TO", "")

    if not all([gmail_user, gmail_pass, to_email]):
        raise EnvironmentError(
            "GMAIL_USER, GMAIL_APP_PASSWORD, and EMAIL_TO must all be set.\n"
            "Create an App Password: https://myaccount.google.com/apppasswords"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, to_email, msg.as_string())

    print("  Gmail SMTP: sent successfully")

"""Alert delivery adapters (GAP 5).

Renders each alert's `subject_template` / `content_template` with the six
template variables, delivers over Email (Resend -> Brevo -> SendGrid ->
Gmail), Telegram, Discord and Slack, records every attempt in
`alert_delivery_logs`, and retries a failed channel ONCE before moving on to
the remaining channels.

Template variables (all optional; unknown variables render as ""):
    {{job_count}} {{job_title}} {{company_name}} {{location}}
    {{salary}} {{apply_url}}

Per-job variables (everything except {{job_count}}) resolve against the top
match in the header rendering and against each job in per-job list rendering.
"""

from __future__ import annotations

import html as _html
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

SUPPORTED_CHANNELS = ("email", "telegram", "discord", "slack")

DEFAULT_SUBJECT = "{{job_count}} new visa-sponsoring jobs match your alert"
DEFAULT_CONTENT = (
    "{{job_count}} new visa-sponsoring job(s) matched your alert:\n\n"
    "{{job_title}} at {{company_name}} — {{location}}{{salary}}\n"
    "Apply: {{apply_url}}"
)


def _job_context(job: dict[str, Any]) -> dict[str, str]:
    location = job.get("location_raw") or job.get("location") or ""
    currency = job.get("salary_currency") or ""
    salary = job.get("salary_raw") or ""
    if not salary and (job.get("salary_min") or job.get("salary_max")):
        lo = job.get("salary_min")
        hi = job.get("salary_max")
        salary = f"{currency} {lo or '?'}–{hi or '?'}".strip()
    return {
        "job_title": str(job.get("title") or ""),
        "company_name": str(job.get("company") or ""),
        "location": str(location),
        "salary": str(salary),
        "apply_url": str(job.get("apply_url") or job.get("url") or ""),
    }


def template_context(alert: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, str]:
    """Aggregate context: job_count + the top match's per-job variables."""
    ctx: dict[str, str] = {"job_count": str(len(jobs))}
    if jobs:
        ctx.update(_job_context(jobs[0]))
    for key in ("job_title", "company_name", "location", "salary", "apply_url"):
        ctx.setdefault(key, "")
    return ctx


def render_template(template: str | None, context: dict[str, str]) -> str:
    """Substitute {{var}} placeholders; unknown variables become empty strings."""
    if not template:
        return ""
    return _TEMPLATE_VAR_RE.sub(lambda m: str(context.get(m.group(1), "")), template)


def render_per_job(template: str, jobs: list[dict[str, Any]], *, job_count: int) -> str:
    """Render the per-job line of a content template once for every job."""
    lines: list[str] = []
    for job in jobs:
        ctx = {"job_count": str(job_count)}
        ctx.update(_job_context(job))
        rendered = render_template(template, ctx).strip()
        if rendered:
            lines.append(rendered)
    return "\n\n".join(lines)


def _split_template(content_template: str | None) -> tuple[str, str]:
    """Split a content template into header (vars only) and per-job body.

    A template containing a newline is treated as header line + per-job body;
    otherwise the whole template is the per-job body with a default header.
    """
    template = (content_template or DEFAULT_CONTENT).strip()
    if "\n" in template:
        header, _, body = template.partition("\n")
        return header.strip(), body.strip() or header.strip()
    return "", template


def _deliver_with_retry(send_once: Callable[[], bool]) -> tuple[bool, str]:
    """Try once, retry once on failure. Returns (success, error_message)."""
    try:
        if send_once():
            return True, ""
        error = "send returned no success"
    except Exception as exc:  # defensive: channel helpers already catch
        error = str(exc)
    logger.warning("channel delivery failed — retrying once: %s", error)
    try:
        if send_once():
            return True, ""
        return False, error
    except Exception as exc:
        return False, str(exc)


def _log_delivery(client, alert_id: Any, channel: str, ok: bool, job_count: int, error: str) -> None:
    try:
        client.table("alert_delivery_logs").insert(
            {
                "alert_id": alert_id,
                "channel": channel,
                "status": "sent" if ok else "failed",
                "job_count": job_count,
                "error_message": (error[:900] or None) if not ok else None,
            }
        ).execute()
    except Exception as exc:
        logger.warning("alert_delivery_logs insert failed (%s): %s", channel, exc)


def deliver_email(
    client,
    alert: dict[str, Any],
    jobs: list[dict[str, Any]],
) -> bool:
    """Email adapter: renders templates, sends via the provider fallback chain."""
    try:
        res = client.table("profiles").select("email").eq("id", alert.get("user_id")).limit(1).execute()
        profile = res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("profile lookup for alert %s failed: %s", alert.get("id"), exc)
        profile = None
    to_email = (profile or {}).get("email")
    if not to_email:
        logger.info("Alert %s: email channel enabled but profile has no email", alert.get("id"))
        return False

    from job_radar.notifications.email import send_email_with_fallback
    from job_radar.visalane.stages import build_alert_email_html

    ctx = template_context(alert, jobs)
    subject = render_template(alert.get("subject_template") or DEFAULT_SUBJECT, ctx)
    content_template = alert.get("content_template")
    if content_template:
        header, body_template = _split_template(content_template)
        header_text = render_template(header, ctx) if header else ""
        per_job = render_per_job(body_template, jobs, job_count=len(jobs))
        rendered = (header_text + "\n\n" + per_job) if header_text else per_job
        html = "<pre style='font-family:inherit;white-space:pre-wrap;'>" + _html.escape(rendered) + "</pre>"
    else:
        html = build_alert_email_html(alert.get("name", "alert"), jobs)

    def send_once() -> bool:
        return send_email_with_fallback(subject, html, to_email=to_email) is not None

    ok, error = _deliver_with_retry(send_once)
    _log_delivery(client, alert.get("id"), "email", ok, len(jobs), error)
    return ok


def deliver_messaging_channel(
    client,
    alert: dict[str, Any],
    jobs: list[dict[str, Any]],
    channel: str,
) -> bool:
    """Telegram/Discord/Slack adapter with template rendering + retry-once."""
    from job_radar.notifications.channels import CHANNELS
    from job_radar.visalane.social_queue import build_caption

    sender = CHANNELS.get(channel)
    if sender is None:
        logger.warning("Unknown alert channel '%s'", channel)
        _log_delivery(client, alert.get("id"), channel, False, len(jobs), "unknown channel")
        return False

    ctx = template_context(alert, jobs)
    content_template = alert.get("content_template")
    if content_template:
        header, body_template = _split_template(content_template)
        header_text = render_template(header, ctx) if header else ""
        per_job = render_per_job(body_template, jobs, job_count=len(jobs))
        text = (header_text + "\n\n" + per_job) if header_text else per_job
    else:
        text = build_caption(jobs)

    def send_once() -> bool:
        return bool(sender(text))

    ok, error = _deliver_with_retry(send_once)
    _log_delivery(client, alert.get("id"), channel, ok, len(jobs), error)
    return ok


def deliver_alert(client, alert: dict[str, Any], jobs: list[dict[str, Any]]) -> list[str]:
    """Deliver one alert over every enabled channel. Returns channels that sent.

    A failing channel is retried once, then the loop continues to the rest —
    one dead webhook never blocks the other channels (GAP 5).
    """
    channels = alert.get("channels") or {}
    used: list[str] = []
    if channels.get("email") and deliver_email(client, alert, jobs):
        used.append("email")
    for channel in ("telegram", "discord", "slack"):
        if channels.get(channel) and deliver_messaging_channel(client, alert, jobs, channel):
            used.append(channel)
    return used

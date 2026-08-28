"""Email delivery module (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.notifications.email import (
    _send_via_gmail_smtp,
    _send_via_resend,
    _send_via_sendgrid,
    send_email,
    send_junior_ai_email,
    send_radar_digest,
    send_worker_run_alert,
)
from job_radar.notifications.renderers import (
    _build_radar_html,
    _render_job_card,
    build_legacy_html,
    build_radar_html,
    build_worker_run_alert_html,
)

__all__ = [
    "send_radar_digest",
    "send_email",
    "send_junior_ai_email",
    "send_worker_run_alert",
    "build_radar_html",
    "_build_radar_html",
    "build_legacy_html",
    "build_worker_run_alert_html",
    "_render_job_card",
    "_send_via_resend",
    "_send_via_sendgrid",
    "_send_via_gmail_smtp",
]


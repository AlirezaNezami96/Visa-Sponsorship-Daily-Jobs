"""Notifications subpackage for job_radar."""
from job_radar.notifications.email import (
    _send_via_gmail_smtp,
    _send_via_resend,
    _send_via_sendgrid,
    send_email,
    send_junior_ai_email,
    send_justjoin_email,
    send_radar_digest,
)
from job_radar.notifications.renderers import (
    _build_radar_html,
    _render_job_card,
    build_justjoin_html,
    build_legacy_html,
    build_radar_html,
)

__all__ = [
    "send_radar_digest",
    "send_email",
    "send_junior_ai_email",
    "send_justjoin_email",
    "_send_via_resend",
    "_send_via_sendgrid",
    "_send_via_gmail_smtp",
    "build_radar_html",
    "_build_radar_html",
    "build_legacy_html",
    "build_justjoin_html",
    "_render_job_card",
]

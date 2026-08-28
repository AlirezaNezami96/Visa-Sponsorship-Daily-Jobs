"""Tests for the GAP-5 alert delivery adapters (template rendering, retry, logs)."""

from __future__ import annotations

from unittest.mock import patch

from job_radar.visalane.alert_delivery import (
    deliver_alert,
    deliver_messaging_channel,
    render_per_job,
    render_template,
    template_context,
)
from tests.test_visalane import FakeClient

JOBS = [
    {
        "job_db_id": "j1",
        "title": "Senior Android Developer",
        "company": "TechCorp",
        "location_raw": "Barcelona, Spain",
        "salary_raw": "€60k–€80k",
        "apply_url": "https://example.com/j1",
        "visa_sponsorship_verified": True,
    },
    {
        "job_db_id": "j2",
        "title": "Kotlin Engineer",
        "company": "StartupX",
        "location_raw": "Remote",
        "salary_min": 50000,
        "salary_max": 70000,
        "salary_currency": "EUR",
        "apply_url": "https://example.com/j2",
    },
]

ALERT = {
    "id": "a1",
    "user_id": "u1",
    "name": "Android in Spain",
    "channels": {"telegram": True},
    "subject_template": "{{job_count}} new jobs: {{job_title}}",
    "content_template": "{{job_count}} matches found\n{{job_title}} @ {{company_name}} — {{location}}{{salary}} {{apply_url}}",
}


def test_render_template_substitutes_and_blanks_unknown():
    out = render_template("{{job_count}} jobs: {{job_title}} ({{bogus}})", {"job_count": "3", "job_title": "Dev"})
    assert out == "3 jobs: Dev ()"


def test_template_context_aggregate_and_per_job():
    ctx = template_context(ALERT, JOBS)
    assert ctx["job_count"] == "2"
    assert ctx["job_title"] == "Senior Android Developer"
    assert ctx["apply_url"] == "https://example.com/j1"


def test_render_per_job_renders_each_job():
    body = "{{job_title}} @ {{company_name}} — {{salary}}"
    out = render_per_job(body, JOBS, job_count=2)
    assert "Senior Android Developer @ TechCorp — €60k–€80k" in out
    assert "Kotlin Engineer @ StartupX — EUR 50000–70000" in out


def test_messaging_channel_renders_template_and_logs():
    client = FakeClient()
    sent: list[str] = []

    with patch("job_radar.notifications.channels.CHANNELS", {"telegram": lambda text: sent.append(text) or True}):
        ok = deliver_messaging_channel(client, ALERT, JOBS, "telegram")

    assert ok
    assert sent, "channel sender was not called"
    text = sent[0]
    assert "2 matches found" in text
    assert "TechCorp" in text and "StartupX" in text
    assert "https://example.com/j1" in text and "https://example.com/j2" in text

    logs = client.store.get("alert_delivery_logs", [])
    assert logs and logs[0]["channel"] == "telegram" and logs[0]["status"] == "sent"
    assert logs[0]["job_count"] == 2


def test_failed_channel_retries_once_then_continues():
    client = FakeClient()
    calls = {"telegram": 0, "discord": 0}

    def failing_telegram(text):
        calls["telegram"] += 1
        return False

    def ok_discord(text):
        calls["discord"] += 1
        return True

    alert = {
        "id": "a2",
        "user_id": "u1",
        "channels": {"telegram": True, "discord": True},
        "content_template": "hi {{job_title}}",
    }
    channels_impl = {"telegram": failing_telegram, "discord": ok_discord}

    with patch("job_radar.notifications.channels.CHANNELS", channels_impl):
        used = deliver_alert(client, alert, JOBS)

    assert calls["telegram"] == 2  # original attempt + exactly one retry
    assert calls["discord"] >= 1
    assert used == ["discord"]  # telegram dead, discord still delivered

    logs = {(l["channel"], l["status"]) for l in client.store.get("alert_delivery_logs", [])}
    assert ("telegram", "failed") in logs
    assert ("discord", "sent") in logs


def test_exception_in_sender_is_caught_and_retried():
    client = FakeClient()
    attempts = {"n": 0}

    def boom(text):
        attempts["n"] += 1
        raise RuntimeError("webhook dead")

    alert = {"id": "a3", "user_id": "u1", "channels": {"slack": True}}

    with patch("job_radar.notifications.channels.CHANNELS", {"slack": boom}):
        ok = deliver_messaging_channel(client, alert, JOBS, "slack")

    assert not ok
    assert attempts["n"] == 2
    logs = client.store.get("alert_delivery_logs", [])
    assert logs[0]["status"] == "failed"
    assert "webhook dead" in (logs[0]["error_message"] or "")


def test_email_channel_renders_subject_and_uses_fallback_chain():
    client = FakeClient()
    client.store["profiles"] = [{"id": "u1", "email": "user@example.com"}]
    captured: dict = {}

    def fake_send(subject, html, to_email=None, preferred=None):
        captured.update(subject=subject, html=html, to_email=to_email)
        return "resend"

    alert = dict(ALERT, channels={"email": True})

    with patch("job_radar.notifications.email.send_email_with_fallback", fake_send):
        used = deliver_alert(client, alert, JOBS)

    assert used == ["email"]
    assert captured["subject"] == "2 new jobs: Senior Android Developer"
    assert captured["to_email"] == "user@example.com"
    assert "TechCorp" in captured["html"]
    logs = client.store.get("alert_delivery_logs", [])
    assert any(l["channel"] == "email" and l["status"] == "sent" for l in logs)


def test_email_missing_profile_email_fails_without_send():
    client = FakeClient()
    client.store["profiles"] = [{"id": "u1", "email": None}]

    with patch("job_radar.notifications.email.send_email_with_fallback", side_effect=AssertionError("must not send")):
        used = deliver_alert(client, dict(ALERT, channels={"email": True}), JOBS)

    assert used == []


def test_default_content_template_used_when_unset():
    client = FakeClient()
    sent: list[str] = []
    alert = {"id": "a4", "user_id": "u1", "channels": {"telegram": True}}

    with patch("job_radar.notifications.channels.CHANNELS", {"telegram": lambda text: sent.append(text) or True}):
        ok = deliver_messaging_channel(client, alert, JOBS, "telegram")

    assert ok
    assert "Senior Android Developer" in sent[0]
    assert "Visa-sponsoring" in sent[0] or "match" in sent[0].lower()

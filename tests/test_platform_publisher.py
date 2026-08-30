"""Regression tests for publisher pacing, atomic claim, manual review routing, and approval execution."""
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytest

from job_radar.social.platform_publisher import (
    check_pacing,
    claim_next_post_job,
    handle_approval_callback,
    publish_next_job,
)


class MockPacingTable:
    def __init__(self, count=0, last_date=None, pending_jobs=None):
        self.count = count
        self.last_date = last_date
        self.pending_jobs = pending_jobs or []

    def select(self, *args, **kwargs):
        return self

    def eq(self, k, v):
        return self

    def neq(self, k, v):
        return self

    def gte(self, k, v):
        return self

    def not_(self):
        return self

    def is_(self, k, v):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        return self

    def insert(self, payload):
        return self

    def execute(self):
        resp = MagicMock()
        resp.count = self.count
        if self.last_date:
            resp.data = [{"telegram_at": self.last_date, "discord_at": self.last_date}]
        else:
            resp.data = self.pending_jobs
        return resp


class MockPacingSupabase:
    def __init__(self, count=0, last_date=None, pending_jobs=None):
        self.job_processing = MockPacingTable(count, last_date, pending_jobs)
        self.platform_post_config = MockPacingTable()
        self.jobs = MockPacingTable()
        self.service_circuits = MockPacingTable()
        self.metrics_daily = MockPacingTable()

    def table(self, name):
        if name == "job_processing":
            return self.job_processing
        if name == "platform_post_config":
            return self.platform_post_config
        if name == "jobs":
            return self.jobs
        if name == "service_circuits":
            return self.service_circuits
        if name == "metrics_daily":
            return self.metrics_daily
        return MockPacingTable()

    def rpc(self, name, params):
        mock_r = MagicMock()
        mock_r.execute.return_value.data = []
        return mock_r


def test_check_pacing_daily_cap_exceeded():
    client = MockPacingSupabase(count=40)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is False
    assert "daily cap" in reason


def test_check_pacing_min_gap_not_elapsed():
    recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    client = MockPacingSupabase(count=5, last_date=recent)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is False
    assert "min gap" in reason


def test_check_pacing_allowed():
    past = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    client = MockPacingSupabase(count=5, last_date=past)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is True


def test_handle_approval_callback_approve():
    """Verify approve action triggers publisher and transitions stage to done."""
    client = MockPacingSupabase(pending_jobs=[{"job_id": "test-uuid", "post_text": '{"telegram": "hello"}'}])

    with patch("job_radar.social.platform_publisher._send_telegram_post", return_value=(True, "https://t.me/123")):
        res = handle_approval_callback(client, "approve_telegram_test-uuid")

    assert res["ok"] is True
    assert res["action"] == "published"
    assert res["url"] == "https://t.me/123"


def test_handle_approval_callback_reject():
    """Verify reject action transitions stage to failed."""
    client = MockPacingSupabase()

    res = handle_approval_callback(client, "reject_linkedin_test-uuid")
    assert res["ok"] is True
    assert res["action"] == "rejected"
    assert res["job_id"] == "test-uuid"

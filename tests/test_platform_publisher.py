"""Tests for platform publisher pacing, anti-spam safeguards, and manual review routing."""
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytest

from job_radar.social.platform_publisher import (
    check_pacing,
    get_platform_config,
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

    def table(self, name):
        if name == "job_processing":
            return self.job_processing
        if name == "platform_post_config":
            return self.platform_post_config
        if name == "jobs":
            return self.jobs
        return MockPacingTable()


def test_check_pacing_daily_cap_exceeded():
    client = MockPacingSupabase(count=40)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is False
    assert "daily cap" in reason


def test_check_pacing_min_gap_not_elapsed():
    # Last post was 2 minutes ago, min gap is 5 min
    recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    client = MockPacingSupabase(count=5, last_date=recent)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is False
    assert "min gap" in reason


def test_check_pacing_allowed():
    # Last post was 15 minutes ago, min gap is 5 min
    past = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    client = MockPacingSupabase(count=5, last_date=past)
    config = {"enabled": True, "active_start_hour": 0, "active_end_hour": 24, "daily_cap": 40, "min_gap_minutes": 5}

    allowed, reason = check_pacing(client, "telegram", config)
    assert allowed is True

"""Tests for watchdog stuck-job detection, backlog calculation, and anomaly alerts."""
from unittest.mock import MagicMock
import pytest

from job_radar.pipeline.watchdog import (
    reset_all_stuck_jobs,
    refresh_pipeline_health,
    notify_owner_if_needed,
)


class MockWatchdogSupabase:
    def __init__(self, stuck_data=None, backlog_count=0):
        self.stuck_data = stuck_data or []
        self.backlog_count = backlog_count

    def table(self, name):
        mock_t = MagicMock()
        mock_t.select.return_value = mock_t
        mock_t.eq.return_value = mock_t
        mock_t.lt.return_value = mock_t
        mock_t.in_.return_value = mock_t
        mock_t.execute.return_value.data = self.stuck_data
        mock_t.execute.return_value.count = self.backlog_count
        return mock_t


def test_notify_owner_when_no_issues():
    """No alert should fire when all systems are normal."""
    notified = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[],
        recent_quarantines=[],
        backlogs={"metadata": 5, "image": 2},
    )
    assert notified is False


def test_notify_owner_when_circuits_open():
    """Alert should fire when circuit breakers trip."""
    notified = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[{"name": "gemini_api", "state": "open", "consecutive_failures": 5}],
        recent_quarantines=[],
        backlogs={"metadata": 5},
    )
    assert notified is True


def test_notify_owner_when_quarantines_exist():
    """Alert should fire when jobs are quarantined."""
    notified = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[],
        recent_quarantines=[{"job_id": "123", "stage": "image", "reason": "timeout"}],
        backlogs={"metadata": 5},
    )
    assert notified is True

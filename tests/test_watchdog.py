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
        force=True,
    )
    assert notified is True


def test_notify_owner_suppresses_duplicate_alerts():
    """Duplicate alert for same issues within cooldown should be suppressed."""
    # First alert fires
    first = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[{"name": "gemini_api", "state": "open", "consecutive_failures": 5}],
        recent_quarantines=[],
        backlogs={"metadata": 5},
        force=True,
    )
    assert first is True

    # Immediate second alert for identical state should be suppressed
    second = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[{"name": "gemini_api", "state": "open", "consecutive_failures": 5}],
        recent_quarantines=[],
        backlogs={"metadata": 5},
        force=False,
    )
    assert second is False


def test_notify_owner_muted_when_alerts_disabled(monkeypatch):
    """When WATCHDOG_ALERTS_ENABLED=false, no alerts should fire."""
    monkeypatch.setenv("WATCHDOG_ALERTS_ENABLED", "false")
    notified = notify_owner_if_needed(
        stuck_reset={},
        open_circuits=[{"name": "gemini_api", "state": "open", "consecutive_failures": 5}],
        recent_quarantines=[{"job_id": "123", "stage": "image", "reason": "timeout"}],
        backlogs={"metadata": 5},
        force=True,
    )
    assert notified is False


def test_reset_all_circuits():
    """reset_all_circuits should update service_circuits table."""
    from job_radar.pipeline.watchdog import reset_all_circuits

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.neq.return_value = mock_table
    mock_table.execute.return_value.data = [{"id": 1}, {"id": 2}]

    count = reset_all_circuits(mock_client)
    assert count == 2
    mock_client.table.assert_called_with("service_circuits")


def test_resolve_all_quarantines():
    """resolve_all_quarantines should update processing_quarantine table."""
    from job_radar.pipeline.watchdog import resolve_all_quarantines

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.is_.return_value = mock_table
    mock_table.execute.return_value.data = [{"id": "q1"}]

    count = resolve_all_quarantines(mock_client)
    assert count == 1
    mock_client.table.assert_called_with("processing_quarantine")


"""Tests for pipeline state machine transitions, claim, and quarantine logic."""
from unittest.mock import MagicMock, patch
import pytest

from job_radar.pipeline.state_machine import (
    transition_stage,
    claim_pending,
    get_stage_backlog,
    reset_stuck,
    MAX_ATTEMPTS,
    VALID_TRANSITIONS,
)


class MockTable:
    def __init__(self, data=None):
        self._data = data or {}
        self._selected = None
        self._where = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, k, v):
        self._where[k] = v
        return self

    def in_(self, k, v):
        self._where[k] = v
        return self

    def lt(self, k, v):
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

    def execute(self):
        mock_resp = MagicMock()
        mock_resp.data = self._data
        mock_resp.count = len(self._data) if isinstance(self._data, list) else 1
        return mock_resp

    def update(self, payload):
        mock_resp = MagicMock()
        mock_resp.data = payload
        return self

    def insert(self, payload):
        mock_resp = MagicMock()
        mock_resp.data = payload
        return self


class MockSupabase:
    def __init__(self, table_data=None):
        self.table_data = table_data or {}
        self.tables = {}

    def table(self, name):
        if name not in self.tables:
            data = self.table_data.get(name, {})
            self.tables[name] = MockTable(data)
        return self.tables[name]


def test_valid_transitions():
    """Verify state transition rules."""
    assert "processing" in VALID_TRANSITIONS["pending"]
    assert "done" in VALID_TRANSITIONS["processing"]
    assert "failed" in VALID_TRANSITIONS["processing"]
    assert "quarantined" in VALID_TRANSITIONS["failed"]
    assert "pending" in VALID_TRANSITIONS["failed"]


def test_transition_stage_success():
    """Test successful transition from pending to processing."""
    client = MockSupabase({
        "job_processing": {"job_id": "test-123", "metadata_status": "pending"}
    })

    res = transition_stage(client, "test-123", "metadata", "processing")
    assert res["ok"] is True
    assert res["quarantined"] is False


def test_transition_stage_invalid():
    """Test rejection of invalid transitions."""
    client = MockSupabase({
        "job_processing": {"job_id": "test-123", "metadata_status": "done"}
    })

    # Cannot go from done to processing
    res = transition_stage(client, "test-123", "metadata", "processing")
    assert res["ok"] is False


def test_transition_stage_quarantine_after_max_attempts():
    """Test that 3 failures lead to quarantine."""
    client = MockSupabase({
        "job_processing": {
            "job_id": "test-123",
            "metadata_status": "processing",
            "metadata_attempts": 3,
        }
    })

    res = transition_stage(client, "test-123", "metadata", "failed", error="Fatal error")
    assert res["ok"] is True
    assert res["quarantined"] is True


def test_get_stage_backlog():
    """Test stage backlog calculation."""
    client = MockSupabase({
        "job_processing": [{"job_id": "j1"}, {"job_id": "j2"}, {"job_id": "j3"}]
    })

    count = get_stage_backlog(client, "metadata")
    assert count == 3

"""Tests for the database-backed circuit breaker."""
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
import pytest

from job_radar.pipeline.circuit_breaker import CircuitBreaker


class MockCircuitTable:
    def __init__(self):
        self.rows = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, k, v):
        self._key = v
        return self

    def maybe_single(self):
        return self

    def execute(self):
        resp = MagicMock()
        val = self.rows.get(self._key)
        resp.data = val
        return resp

    def insert(self, payload):
        self.rows[payload["name"]] = payload
        resp = MagicMock()
        resp.data = payload
        return self

    def update(self, payload):
        if self._key in self.rows:
            self.rows[self._key].update(payload)
        resp = MagicMock()
        resp.data = payload
        return self


class MockSupabaseCircuits:
    def __init__(self):
        self.circuits_table = MockCircuitTable()

    def table(self, name):
        if name == "service_circuits":
            return self.circuits_table
        raise ValueError(f"Unknown table {name}")


def test_circuit_initial_closed():
    client = MockSupabaseCircuits()
    cb = CircuitBreaker(client, failure_threshold=3, cooldown_minutes=10)

    assert cb.is_open("gemini_api") is False
    state = cb.get_state("gemini_api")
    assert state["state"] == "closed"
    assert state["consecutive_failures"] == 0


def test_circuit_trips_after_threshold():
    client = MockSupabaseCircuits()
    cb = CircuitBreaker(client, failure_threshold=3, cooldown_minutes=10)

    cb.record_failure("gemini_api")
    assert cb.is_open("gemini_api") is False

    cb.record_failure("gemini_api")
    assert cb.is_open("gemini_api") is False

    cb.record_failure("gemini_api")
    assert cb.is_open("gemini_api") is True

    state = cb.get_state("gemini_api")
    assert state["state"] == "open"
    assert state["consecutive_failures"] == 3


def test_circuit_half_open_recovery():
    client = MockSupabaseCircuits()
    cb = CircuitBreaker(client, failure_threshold=2, cooldown_minutes=5)

    # Trip circuit
    cb.record_failure("groq_api")
    cb.record_failure("groq_api")
    assert cb.is_open("groq_api") is True

    # Simulate elapsed cooldown
    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    client.circuits_table.rows["groq_api"]["opened_at"] = past

    # Next check should transition to half_open and allow call
    assert cb.is_open("groq_api") is False
    assert cb.get_state("groq_api")["state"] == "half_open"

    # Successful call closes it
    cb.record_success("groq_api")
    assert cb.is_open("groq_api") is False
    assert cb.get_state("groq_api")["state"] == "closed"
    assert cb.get_state("groq_api")["consecutive_failures"] == 0


def test_circuit_manual_reset():
    client = MockSupabaseCircuits()
    cb = CircuitBreaker(client, failure_threshold=1)

    cb.record_failure("wikimedia")
    assert cb.is_open("wikimedia") is True

    cb.reset("wikimedia")
    assert cb.is_open("wikimedia") is False
    assert cb.get_state("wikimedia")["state"] == "closed"

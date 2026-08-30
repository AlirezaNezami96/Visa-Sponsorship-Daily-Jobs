"""Tests for aggregated metrics module."""
from unittest.mock import MagicMock
from datetime import date
import pytest

from job_radar.pipeline.metrics import (
    record_metric,
    update_pipeline_health,
    get_metrics_range,
)


class MockMetricsTable:
    def __init__(self):
        self.rows = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, k, v):
        setattr(self, f"_{k}", v)
        return self

    def gte(self, k, v):
        return self

    def lte(self, k, v):
        return self

    def order(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        resp = MagicMock()
        today = date.today().isoformat()
        metric = getattr(self, "_metric", None)
        key = (today, metric)
        resp.data = self.rows.get(key)
        return resp

    def insert(self, payload):
        key = (payload["day"], payload["metric"])
        self.rows[key] = payload
        resp = MagicMock()
        resp.data = payload
        return self

    def update(self, payload):
        today = date.today().isoformat()
        metric = getattr(self, "_metric", None)
        key = (today, metric)
        if key in self.rows:
            self.rows[key].update(payload)
        resp = MagicMock()
        resp.data = payload
        return self


class MockSupabaseMetrics:
    def __init__(self):
        self.metrics_table = MockMetricsTable()
        self.health_table = MockMetricsTable()

    def table(self, name):
        if name == "metrics_daily":
            return self.metrics_table
        if name == "pipeline_health":
            return self.health_table
        raise ValueError(f"Unknown table {name}")


def test_record_metric_insert_and_update():
    client = MockSupabaseMetrics()

    # First insert
    record_metric(client, "scrape:greenhouse:ok", True, duration_ms=250)
    today = date.today().isoformat()
    row = client.metrics_table.rows.get((today, "scrape:greenhouse:ok"))
    assert row is not None
    assert row["count"] == 1
    assert row["error_count"] == 0
    assert row["sum_ms"] == 250

    # Second update (failure)
    record_metric(client, "scrape:greenhouse:ok", False, duration_ms=100)
    row = client.metrics_table.rows.get((today, "scrape:greenhouse:ok"))
    assert row["count"] == 2
    assert row["error_count"] == 1
    assert row["sum_ms"] == 350

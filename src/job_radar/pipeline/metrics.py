"""Aggregated pipeline metrics — one row per metric per day.

Design: every service calls `record_metric(name, ok, duration_ms)` which does a
single `INSERT ... ON CONFLICT DO UPDATE` — the admin UI never scans raw events,
only aggregated rows.

Complementary `update_pipeline_health` upserts the `pipeline_health` table for
at-a-glance stage health.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def record_metric(
    client: Any,
    name: str,
    ok: bool,
    duration_ms: int = 0,
) -> None:
    """Record a single metric event.

    Performs an atomic upsert: INSERT on day+metric, or UPDATE incrementing
    count/error_count/sum_ms on conflict. One row per metric per day.

    Args:
        client: Supabase client (service-role).
        name: Metric name (e.g. 'scrape:greenhouse:added', 'ai:resume:ok').
        ok: Whether the operation succeeded.
        duration_ms: Duration of the operation in milliseconds.
    """
    today = date.today().isoformat()
    try:
        # 1. Attempt single-call atomic database RPC
        if hasattr(client, "rpc"):
            try:
                client.rpc(
                    "record_metric",
                    {"p_metric": name, "p_ok": bool(ok), "p_ms": int(duration_ms)},
                ).execute()
                return
            except Exception as rpc_err:
                logger.debug("RPC record_metric fallback: %s", rpc_err)

        # 2. Fallback select-then-upsert for local mocks / instances without RPC
        resp = (
            client.table("metrics_daily")
            .select("count, error_count, sum_ms")
            .eq("day", today)
            .eq("metric", name)
            .maybe_single()
            .execute()
        )

        if resp and resp.data:
            current = resp.data
            update = {
                "count": current["count"] + 1,
                "sum_ms": current["sum_ms"] + duration_ms,
            }
            if not ok:
                update["error_count"] = current["error_count"] + 1

            client.table("metrics_daily").update(update).eq(
                "day", today
            ).eq("metric", name).execute()
        else:
            client.table("metrics_daily").insert({
                "day": today,
                "metric": name,
                "count": 1,
                "error_count": 0 if ok else 1,
                "sum_ms": duration_ms,
            }).execute()

    except Exception as e:
        logger.warning("Failed to record metric %s: %s", name, e)


def record_batch_metrics(
    client: Any,
    metrics: list[tuple[str, bool, int]],
) -> None:
    """Record multiple metrics at once.

    Args:
        client: Supabase client (service-role).
        metrics: List of (name, ok, duration_ms) tuples.
    """
    for name, ok, duration_ms in metrics:
        record_metric(client, name, ok, duration_ms)


def update_pipeline_health(
    client: Any,
    stage: str,
    *,
    success: bool | None = None,
    error: str | None = None,
    backlog: int | None = None,
) -> None:
    """Upsert pipeline_health for a stage.

    Args:
        client: Supabase client (service-role).
        stage: Stage name.
        success: Whether the last operation was a success (sets last_success_at).
        error: Error message (sets last_error_at and last_error).
        backlog: Current number of pending items.
    """
    now = datetime.now(timezone.utc).isoformat()

    try:
        resp = (
            client.table("pipeline_health")
            .select("stage")
            .eq("stage", stage)
            .maybe_single()
            .execute()
        )

        update: dict[str, Any] = {"updated_at": now}
        if success is True:
            update["last_success_at"] = now
        if error:
            update["last_error_at"] = now
            update["last_error"] = error[:2000]
        if backlog is not None:
            update["backlog"] = backlog

        if resp and resp.data:
            client.table("pipeline_health").update(update).eq("stage", stage).execute()
        else:
            update["stage"] = stage
            client.table("pipeline_health").insert(update).execute()

    except Exception as e:
        logger.warning("Failed to update pipeline_health for %s: %s", stage, e)


def get_metrics_range(
    client: Any,
    from_date: str,
    to_date: str,
) -> list[dict[str, Any]]:
    """Fetch metrics_daily rows within a date range.

    Args:
        client: Supabase client (service-role).
        from_date: Start date (inclusive, ISO format).
        to_date: End date (inclusive, ISO format).

    Returns:
        List of metric rows.
    """
    resp = (
        client.table("metrics_daily")
        .select("*")
        .gte("day", from_date)
        .lte("day", to_date)
        .order("day", desc=True)
        .order("metric")
        .execute()
    )
    return resp.data if resp and resp.data else []


def get_pipeline_health(client: Any) -> list[dict[str, Any]]:
    """Fetch all pipeline_health rows."""
    resp = client.table("pipeline_health").select("*").execute()
    return resp.data if resp and resp.data else []


def get_quarantine_list(
    client: Any,
    limit: int = 50,
    unresolved_only: bool = True,
) -> list[dict[str, Any]]:
    """Fetch quarantined items."""
    query = (
        client.table("processing_quarantine")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if unresolved_only:
        query = query.is_("resolved_at", "null")
    resp = query.execute()
    return resp.data if resp and resp.data else []

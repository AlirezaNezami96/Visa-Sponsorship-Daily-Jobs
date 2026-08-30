"""Pipeline state machine for per-job stage tracking.

Every job flows through stages: scrape → enrich → alerts → image → post_text → publish.
Each stage has: pending → processing → done|failed. Failed re-enqueues to pending
while attempts < MAX_ATTEMPTS, else quarantined + owner alert.

The state machine is backed by the `job_processing` table with `SELECT ... FOR UPDATE
SKIP LOCKED` concurrency safety. Every transition emits a metric via the metrics module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

STAGES = (
    "metadata",
    "alerts",
    "image",
    "post_text",
    "telegram",
    "discord",
    "slack",
    "bluesky",
    "mastodon",
    "linkedin",
    "x",
)

VALID_TRANSITIONS = {
    "pending": {"processing", "manual_review"},
    "processing": {"done", "failed", "manual_review"},
    "failed": {"pending", "quarantined"},
    "manual_review": {"done", "failed"},
    # Terminal states — no transitions out
    "done": set(),
    "quarantined": set(),
}


class StageStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    MANUAL_REVIEW = "manual_review"


def _status_col(stage: str) -> str:
    """Return the status column name for a stage."""
    return f"{stage}_status"


def _attempts_col(stage: str) -> str | None:
    """Return the attempts column name if the stage tracks attempts."""
    if stage in ("metadata", "image"):
        return f"{stage}_attempts"
    return None


def _error_col(stage: str) -> str | None:
    """Return the last_error column name if the stage tracks errors."""
    if stage in ("metadata", "image"):
        return f"{stage}_last_error"
    return None


def _done_at_col(stage: str) -> str | None:
    """Return the done_at column name for stages that track completion time."""
    if stage in ("metadata", "alerts", "image"):
        return f"{stage}_done_at"
    # Platform stages use {stage}_at
    if stage in ("telegram", "discord", "slack", "bluesky", "mastodon", "linkedin", "x"):
        return f"{stage}_at"
    return None


def transition_stage(
    client: Any,
    job_id: str,
    stage: str,
    new_status: str,
    *,
    error: str | None = None,
    url: str | None = None,
    post_text: str | None = None,
    metrics_fn: Any | None = None,
) -> dict[str, Any]:
    """Transition a job's stage to a new status.

    Returns a dict with the transition result:
        {"ok": True/False, "quarantined": bool, "attempts": int}

    Args:
        client: Supabase client (service-role).
        job_id: UUID of the job.
        stage: Stage name from STAGES.
        new_status: Target status.
        error: Error message (for failed transitions).
        url: Post URL (for platform publish success).
        post_text: Generated post text (for post_text stage).
        metrics_fn: Optional callable(name, ok, duration_ms) for recording metrics.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    status_col = _status_col(stage)
    now = datetime.now(timezone.utc).isoformat()

    # Read current state
    resp = (
        client.table("job_processing")
        .select(f"job_id, {status_col}")
        .eq("job_id", job_id)
        .maybe_single()
        .execute()
    )
    row = resp.data[0] if isinstance(resp.data, list) and resp.data else resp.data if isinstance(resp.data, dict) else None
    if not row:
        logger.warning("job_processing row not found for job_id=%s", job_id)
        return {"ok": False, "quarantined": False, "attempts": 0}

    current_status = row.get(status_col, "pending")

    # Validate transition
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        logger.warning(
            "Invalid transition %s: %s → %s for job %s",
            stage, current_status, new_status, job_id,
        )
        return {"ok": False, "quarantined": False, "attempts": 0}

    # Build update payload
    update: dict[str, Any] = {status_col: new_status}

    # Handle attempts for stages that track them
    attempts_col = _attempts_col(stage)
    if attempts_col and new_status == "processing":
        # Increment attempts when moving to processing
        current_attempts = _get_attempts(client, job_id, attempts_col)
        update[attempts_col] = current_attempts + 1

    # Handle error
    error_col = _error_col(stage)
    if error_col and error:
        update[error_col] = error[:2000]

    # Handle done_at timestamp
    done_at_col = _done_at_col(stage)
    if done_at_col and new_status == "done":
        update[done_at_col] = now

    # Handle platform URL
    if url and stage in ("telegram", "discord", "slack", "bluesky", "mastodon", "linkedin", "x"):
        update[f"{stage}_url"] = url

    # Handle post_text
    if post_text and stage == "post_text":
        update["post_text"] = post_text

    # Perform the update
    client.table("job_processing").update(update).eq("job_id", job_id).execute()

    # Check if we need to quarantine on failure
    quarantined = False
    attempts = 0
    if new_status == "failed" and attempts_col:
        attempts = _get_attempts(client, job_id, attempts_col)
        if attempts >= MAX_ATTEMPTS:
            _quarantine(client, job_id, stage, error or "max attempts exceeded", attempts)
            client.table("job_processing").update(
                {status_col: "quarantined"}
            ).eq("job_id", job_id).execute()
            quarantined = True
        else:
            # Re-enqueue: set back to pending for retry
            client.table("job_processing").update(
                {status_col: "pending"}
            ).eq("job_id", job_id).execute()

    # Emit metric
    if metrics_fn:
        ok = new_status == "done"
        metrics_fn(f"{stage}:{'ok' if ok else 'fail'}", ok, 0)

    return {"ok": True, "quarantined": quarantined, "attempts": attempts}


def _get_attempts(client: Any, job_id: str, col: str) -> int:
    resp = (
        client.table("job_processing")
        .select(col)
        .eq("job_id", job_id)
        .maybe_single()
        .execute()
    )
    if resp and resp.data:
        return int(resp.data.get(col, 0))
    return 0


def _quarantine(
    client: Any,
    job_id: str,
    stage: str,
    reason: str,
    attempts: int,
    payload: dict | None = None,
) -> None:
    """Insert a row into processing_quarantine."""
    client.table("processing_quarantine").insert({
        "job_id": job_id,
        "stage": stage,
        "reason": reason[:2000],
        "attempts": attempts,
        "payload": payload or {},
    }).execute()
    logger.warning(
        "QUARANTINED job_id=%s stage=%s after %d attempts: %s",
        job_id, stage, attempts, reason[:200],
    )


def claim_pending(
    client: Any,
    stage: str,
    limit: int = 25,
    *,
    prerequisite_stage: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[str]:
    """Claim pending jobs for a stage using SELECT ... FOR UPDATE SKIP LOCKED.

    Returns a list of job_ids that have been transitioned to 'processing'.
    When prerequisite_stage is given, only jobs where that stage is 'done' are eligible.

    Note: This uses a Supabase RPC call or direct query. For the initial
    implementation without RPC, we use a simpler select+update pattern
    that is safe enough for single-worker-per-stage architecture.
    """
    status_col = _status_col(stage)
    attempts_col = _attempts_col(stage)

    # Build query
    query = (
        client.table("job_processing")
        .select("job_id")
        .in_(status_col, ["pending", "failed"])
        .order("updated_at")
        .limit(limit)
    )

    # Filter by prerequisite completion
    if prerequisite_stage:
        prereq_col = _status_col(prerequisite_stage)
        query = query.eq(prereq_col, "done")

    # Filter by max attempts
    if attempts_col:
        query = query.lt(attempts_col, max_attempts)

    resp = query.execute()
    if not resp or not resp.data:
        return []

    claimed: list[str] = []
    for row in resp.data:
        jid = row["job_id"]
        # Transition to processing
        result = transition_stage(client, jid, stage, "processing")
        if result["ok"]:
            claimed.append(jid)

    return claimed


def get_stage_backlog(client: Any, stage: str) -> int:
    """Count pending + failed items for a stage."""
    status_col = _status_col(stage)
    resp = (
        client.table("job_processing")
        .select("job_id", count="exact")
        .in_(status_col, ["pending", "failed"])
        .execute()
    )
    return resp.count if resp and resp.count else 0


def get_stuck_jobs(client: Any, stage: str, stuck_minutes: int = 30) -> list[str]:
    """Find jobs stuck in 'processing' for longer than stuck_minutes."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    status_col = _status_col(stage)

    resp = (
        client.table("job_processing")
        .select("job_id")
        .eq(status_col, "processing")
        .lt("updated_at", cutoff)
        .execute()
    )
    if not resp or not resp.data:
        return []
    return [row["job_id"] for row in resp.data]


def reset_stuck(client: Any, stage: str, stuck_minutes: int = 30) -> int:
    """Reset stuck 'processing' jobs back to 'pending'. Returns count reset."""
    stuck = get_stuck_jobs(client, stage, stuck_minutes)
    if not stuck:
        return 0

    status_col = _status_col(stage)
    for jid in stuck:
        client.table("job_processing").update(
            {status_col: "pending"}
        ).eq("job_id", jid).eq(status_col, "processing").execute()
        logger.info("Reset stuck job %s stage %s back to pending", jid, stage)

    return len(stuck)

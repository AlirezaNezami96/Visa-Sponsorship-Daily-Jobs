"""Job matcher — batches jobs against a user profile using the scorer.

The matcher:
  - Accepts a list of job dicts and a profile dict
  - Scores each job using scorer.compute_match_score (pure, no I/O)
  - Returns jobs sorted by score descending (highest match first)
  - Writes scores back to the database if a Supabase client is provided
  - Reads cached scores (24h TTL) when they exist for a (user, job) pair
  - Handles missing/null data gracefully at every step

Cache contract (user_job_scores table):
  - write_match_scores upserts (user_id, job_id) with score + label
  - read_cached_scores returns fresh rows only (calculated_at within
    the MATCH_CACHE_TTL window); stale rows are treated as misses so
    scores are recomputed lazily on the next request.
  - DB triggers delete a user's rows when their skills change and a
    job's rows when its skills change (see Phase-4 completion migration).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .scorer import compute_match_score

logger = logging.getLogger(__name__)

# Minimum score threshold for "match" label in the API response
MATCH_LABEL_THRESHOLD = 60
GOOD_MATCH_THRESHOLD = 80

# Cached match scores are valid for 24h (spec §3.2 caching strategy).
MATCH_CACHE_TTL = timedelta(hours=24)


def score_jobs_for_profile(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Score and sort a list of jobs for a given user profile.

    Args:
        jobs: List of job dicts (must include 'id' or 'job_db_id').
        profile: User profile dict.

    Returns:
        Jobs sorted by match score (descending), each with a
        'resume_match_score' and 'match_label' field added.
    """
    if not jobs:
        return []

    scored = []
    for job in jobs:
        try:
            score = compute_match_score(profile, job)
        except Exception as exc:
            logger.debug("Scoring failed for job %r: %s", job.get("id"), exc)
            score = 0

        job_out = dict(job)
        job_out["resume_match_score"] = score
        job_out["match_label"] = _match_label(score)
        scored.append(job_out)

    return sorted(scored, key=lambda j: j["resume_match_score"], reverse=True)


def _match_label(score: int) -> str:
    if score >= GOOD_MATCH_THRESHOLD:
        return "great_match"
    if score >= MATCH_LABEL_THRESHOLD:
        return "good_match"
    if score >= 40:
        return "fair_match"
    return "low_match"


def write_match_scores(
    client: Any,
    scored_jobs: list[dict[str, Any]],
    user_id: str,
) -> int:
    """Persist resume_match_score to the user_job_scores cache table.

    Upserts (user_id, job_id) pairs with the current score + label and
    refreshes calculated_at, so subsequent reads within the TTL hit the
    cache and skip recomputation.

    Returns the number of rows written.
    """
    if not client or not scored_jobs:
        return 0

    rows = []
    for job in scored_jobs:
        job_id = job.get("id") or job.get("job_db_id")
        if not job_id:
            continue
        rows.append({
            "user_id": user_id,
            "job_id": job_id,
            "score": job.get("resume_match_score", 0),
            "match_label": job.get("match_label", "low_match"),
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        })

    if not rows:
        return 0

    try:
        # Upsert: update score if same (user, job) pair exists
        client.table("user_job_scores").upsert(
            rows,
            on_conflict="user_id,job_id",
        ).execute()
        logger.debug("Wrote %d match scores for user %s", len(rows), user_id)
        return len(rows)
    except Exception as exc:
        logger.warning("Failed to write match scores: %s", exc)
        return 0


def read_cached_scores(
    client: Any,
    user_id: str,
    job_ids: list[str],
) -> dict[str, int]:
    """Read fresh (non-stale) cached match scores for a (user, jobs) set.

    Args:
        client: Supabase client (user or admin).
        user_id: The user whose cache to read.
        job_ids: Job ids to look up.

    Returns:
        Mapping job_id -> score for rows within the 24h TTL. Stale rows
        and missing rows are simply absent (cache miss).
    """
    if not client or not user_id or not job_ids:
        return {}

    cutoff = (datetime.now(timezone.utc) - MATCH_CACHE_TTL).isoformat()
    try:
        result = (
            client.table("user_job_scores")
            .select("job_id, score, calculated_at")
            .eq("user_id", user_id)
            .in_("job_id", job_ids)
            .gte("calculated_at", cutoff)
            .execute()
        )
        rows = (result.data or []) if hasattr(result, "data") else []
        return {row["job_id"]: int(row["score"]) for row in rows if row.get("job_id")}
    except Exception as exc:
        logger.debug("Match score cache read failed: %s", exc)
        return {}


def purge_stale_scores(client: Any, ttl: timedelta = MATCH_CACHE_TTL) -> int:
    """Delete cached scores older than the TTL. Returns rows deleted."""
    if not client:
        return 0
    cutoff = (datetime.now(timezone.utc) - ttl).isoformat()
    try:
        result = (
            client.table("user_job_scores")
            .delete()
            .lt("calculated_at", cutoff)
            .execute()
        )
        rows = (result.data or []) if hasattr(result, "data") else []
        return len(rows)
    except Exception as exc:
        logger.debug("Match score purge failed: %s", exc)
        return 0

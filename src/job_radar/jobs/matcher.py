"""Job matcher — batches jobs against a user profile using the scorer.

The matcher:
  - Accepts a list of job dicts and a profile dict
  - Scores each job using scorer.compute_match_score (pure, no I/O)
  - Returns jobs sorted by score descending (highest match first)
  - Writes scores back to the database if a Supabase client is provided
  - Handles missing/null data gracefully at every step
"""
from __future__ import annotations

import logging
from typing import Any

from .scorer import compute_match_score

logger = logging.getLogger(__name__)

# Minimum score threshold for "match" label in the API response
MATCH_LABEL_THRESHOLD = 60
GOOD_MATCH_THRESHOLD = 80


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
    """Persist resume_match_score to the job_applications / saved_jobs join table.

    This writes to the `user_job_scores` table (if it exists) to cache
    per-user scores, avoiding re-computation on every page load.

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
            "match_score": job.get("resume_match_score", 0),
            "match_label": job.get("match_label", "low_match"),
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

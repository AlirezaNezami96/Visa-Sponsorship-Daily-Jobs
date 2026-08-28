"""Stages processed jobs into the `social_post_queue` table.

Platform policy (master plan section 6.4):
- Auto-post (no review): telegram, discord, slack, bluesky, mastodon
- Manual-review queue:  linkedin, x  — generated caption + image, admin publishes

Image generation itself stays in the existing social tooling
(image_utils.py / src/job_radar/social/); the posting worker consumes this
queue and falls back to a text-only post when image generation fails.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

AUTO_POST_PLATFORMS = ("telegram", "discord", "slack", "bluesky", "mastodon")
MANUAL_REVIEW_PLATFORMS = ("linkedin", "x")
ALL_PLATFORMS = AUTO_POST_PLATFORMS + MANUAL_REVIEW_PLATFORMS
JOBS_PER_POST = 5


def build_caption(jobs: list[dict[str, Any]], *, max_jobs: int = JOBS_PER_POST) -> str:
    """Compact multi-job caption; apply links included so text-only fallback works."""
    lines = ["Visa-sponsoring roles worth a look today:"]
    for job in jobs[:max_jobs]:
        company = job.get("company") or "Unknown"
        title = job.get("title") or "Role"
        location = job.get("location_raw") or job.get("location") or ""
        verified = " [verified sponsor]" if job.get("visa_sponsorship_verified") else ""
        line = f"- {title} @ {company}"
        if location:
            line += f" ({location})"
        line += verified
        apply_url = job.get("apply_url") or job.get("url") or ""
        if apply_url:
            line += f"\n  Apply: {apply_url}"
        lines.append(line)
    lines.append("\nMore verified visa-sponsoring jobs: visalane.app")
    return "\n".join(lines)


def enqueue_jobs(
    client,
    jobs: list[dict[str, Any]],
    platforms: list[str] | None = None,
) -> int:
    """Create social_post_queue rows for `jobs` across the requested platforms.

    Returns the number of queue rows created (0 on any failure).
    """
    if not jobs:
        return 0
    platforms = [p for p in (platforms or list(ALL_PLATFORMS)) if p in ALL_PLATFORMS]
    if not platforms:
        return 0

    # Dedup jobs by id/fingerprint before chunking
    seen = set()
    unique_jobs: list[dict[str, Any]] = []
    for job in jobs:
        key = job.get("job_db_id") or job.get("fingerprint") or job.get("url") or id(job)
        if key in seen:
            continue
        seen.add(key)
        unique_jobs.append(job)

    rows = []
    for platform in platforms:
        status = "manual_review" if platform in MANUAL_REVIEW_PLATFORMS else "pending"
        for i in range(0, len(unique_jobs), JOBS_PER_POST):
            batch = unique_jobs[i : i + JOBS_PER_POST]
            job_ids = [j["job_db_id"] for j in batch if j.get("job_db_id")]
            rows.append(
                {
                    "job_ids": job_ids,
                    "platform": platform,
                    "status": status,
                    "caption": build_caption(batch),
                }
            )

    try:
        client.table("social_post_queue").insert(rows).execute()
        logger.info("VisaLane: enqueued %d social posts across %s", len(rows), platforms)
        return len(rows)
    except Exception as exc:
        logger.warning("social_post_queue insert failed: %s", exc)
        return 0

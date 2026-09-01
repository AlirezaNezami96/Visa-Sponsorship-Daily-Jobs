"""Stages processed jobs into the `social_post_queue` table with independent platform-native content.

Platform policy (master plan section 6.4 & Part 1):
- Tier 1 (Telegram, Discord): Batched feeds (1-5 jobs) or urgent roles with platform-native rich formatting.
- Tier 2/3 (LinkedIn, X, Bluesky, Mastodon): Single curated jobs with independent LLM generation per platform.
- Tier 4 (DEV.to): Articles only (raw job dumps strictly rejected).
- Manual-review queue: linkedin, x — generated caption + image, admin publishes unless AUTO_PUBLISH is set.
- Auto-post (no review): telegram, discord, bluesky, mastodon.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, List, Optional

from job_radar.social.adapters import get_adapter
from job_radar.social.profiles import get_profile
from job_radar.social.tier_router import validate_tier_routing

logger = logging.getLogger(__name__)

AUTO_POST_PLATFORMS = ("telegram", "discord", "bluesky", "mastodon")
MANUAL_REVIEW_PLATFORMS = ("linkedin", "x")
ALL_PLATFORMS = AUTO_POST_PLATFORMS + MANUAL_REVIEW_PLATFORMS
JOBS_PER_POST = 5


def build_caption(jobs: list[dict[str, Any]], *, max_jobs: int = 5) -> str:
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


def build_platform_caption(platform: str, jobs: List[dict[str, Any]]) -> str:
    """Generate platform-native content for the given platform and jobs."""
    adapter = get_adapter(platform)
    profile = get_profile(platform)

    if profile.tier == 1:
        content = adapter.generate_content(jobs)
        if isinstance(content, dict):
            return json.dumps(content)
        return str(content)

    # Tier 2/3: Single job content
    job = jobs[0] if jobs else {}
    content = adapter.generate_content(job)
    if isinstance(content, dict):
        return json.dumps(content)
    return str(content)


def enqueue_jobs(
    client: Any,
    jobs: list[dict[str, Any]],
    platforms: Optional[list[str]] = None,
    card_factory: Optional[Callable[[list[dict[str, Any]]], Optional[str]]] = None,
) -> int:
    """Create social_post_queue rows for `jobs` across the requested platforms.

    Each platform receives an independently generated, platform-native caption
    respecting its tier, format, and batching constraints.
    """
    if not jobs:
        return 0
    target_platforms = [p for p in (platforms or list(ALL_PLATFORMS)) if p in ALL_PLATFORMS]
    if not target_platforms:
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

    # Optional card rendering per batch
    batch_paths: dict[int, Optional[str]] = {}
    if card_factory is not None:
        for i in range(0, len(unique_jobs), 5):
            batch = unique_jobs[i : i + 5]
            try:
                batch_paths[i] = card_factory(batch)
            except Exception as exc:
                logger.warning("card_factory failed for batch at %d: %s", i, exc)
                batch_paths[i] = None

    rows: List[dict[str, Any]] = []
    for platform in target_platforms:
        status = "manual_review" if platform in MANUAL_REVIEW_PLATFORMS else "pending"
        for i in range(0, len(unique_jobs), JOBS_PER_POST):
            batch = unique_jobs[i : i + JOBS_PER_POST]
            job_ids = [j["job_db_id"] for j in batch if j.get("job_db_id")]
            caption = build_platform_caption(platform, batch)
            rows.append(
                {
                    "job_ids": job_ids,
                    "platform": platform,
                    "status": status,
                    "caption": caption,
                    "image_path": batch_paths.get(i),
                }
            )

    if not rows:
        return 0

    try:
        client.table("social_post_queue").insert(rows).execute()
        logger.info("VisaLane: enqueued %d social posts across %s", len(rows), target_platforms)
        return len(rows)
    except Exception as exc:
        logger.warning("social_post_queue insert failed: %s", exc)
        return 0


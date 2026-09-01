"""Content-tier routing and validation engine (Part 1.7).

Enforces strict boundary rules:
- Tier 1 (Telegram, Discord): raw job feed, batched (1-5 jobs) or urgent single job.
- Tier 2/3 (X, LinkedIn, Bluesky, Mastodon): single curated job or short data insight. Never multi-job dumps or articles.
- Tier 4 (DEV.to): full long-form technical articles only. Never standalone job listings.
"""
from __future__ import annotations

import logging
from typing import Any

from job_radar.social.profiles import get_profile

logger = logging.getLogger(__name__)


class RoutingError(ValueError):
    """Raised when content is routed to an incompatible platform tier."""


def validate_tier_routing(
    platform: str,
    content_type: str,
    jobs: list[dict[str, Any]] | None = None,
    raise_on_error: bool = False,
) -> tuple[bool, str]:
    """Validate whether the requested content type and job count are compatible with platform tier.

    content_type options:
    - "batch_jobs"
    - "single_job"
    - "insight_stat"
    - "article"

    Returns (is_valid, reason).
    """
    plat = platform.lower().strip()
    profile = get_profile(plat)
    jobs_list = jobs or []
    job_count = len(jobs_list)

    # 1. Tier 4 Validation (DEV.to)
    if profile.tier == 4:
        if content_type in ("single_job", "batch_jobs") or job_count > 0:
            msg = (
                f"Routing Violation: Platform '{plat}' (Tier 4) only accepts long-form articles, "
                f"not raw job listings (received content_type='{content_type}', job_count={job_count})."
            )
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        if content_type != "article":
            msg = f"Platform '{plat}' (Tier 4) expects content_type='article', received '{content_type}'."
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        return True, "Valid Tier 4 article route"

    # 2. Prevent Tier 4 article content from reaching Tier 1 / 2 / 3 platforms
    if content_type == "article":
        msg = f"Routing Violation: Article content cannot be published on Tier {profile.tier} platform '{plat}'."
        if raise_on_error:
            raise RoutingError(msg)
        return False, msg

    # 3. Tier 1 Validation (Telegram, Discord)
    if profile.tier == 1:
        if content_type not in ("batch_jobs", "single_job", "urgent_job"):
            msg = f"Platform '{plat}' (Tier 1) expects job listings, received '{content_type}'."
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        if job_count == 0:
            msg = f"Platform '{plat}' (Tier 1) requires at least 1 job."
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        if job_count > profile.max_jobs_per_post:
            msg = f"Platform '{plat}' (Tier 1) max jobs exceeded ({job_count} > {profile.max_jobs_per_post})."
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        return True, f"Valid Tier 1 batch route ({job_count} jobs)"

    # 4. Tier 2 / 3 Validation (X, LinkedIn, Bluesky, Mastodon)
    if profile.tier in (2, 3):
        if content_type == "batch_jobs" or job_count > 1:
            msg = (
                f"Routing Violation: Platform '{plat}' (Tier {profile.tier}) does not accept multi-job dumps "
                f"(received {job_count} jobs). Use single curated job or short data insight."
            )
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        if content_type not in ("single_job", "insight_stat", "weekly_insight"):
            msg = f"Platform '{plat}' (Tier {profile.tier}) invalid content_type '{content_type}'."
            if raise_on_error:
                raise RoutingError(msg)
            return False, msg
        return True, f"Valid Tier {profile.tier} single route"

    return True, "Valid route"

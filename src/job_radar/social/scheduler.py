"""Jittered scheduler, cross-platform staggering queue, daily budget caps, and deduplication.

Part 1.4: Scheduler with jitter, not a fixed cron tick.
Part 1.5: Cross-platform staggering queue (10-90 min offsets across platforms for same job).
Part 1.6: Per-platform deduplication tracking ((platform, job_id) pairs).
Part 1.8: Rate-limit and cost awareness per platform (daily budget hard stop).
"""
from __future__ import annotations

import datetime
import json
import logging
import random
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

from job_radar.social.profiles import PLATFORM_PROFILES, get_profile

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_FILE = Path("state/social_daily_budgets.json")
DEFAULT_STAGGER_FILE = Path("state/social_stagger_queue.json")
DEFAULT_DEDUP_FILE = Path("state/social_posted_dedup.json")


def next_post_time(
    interval_minutes: float,
    jitter_pct: float = 25.0,
    base_time: datetime.datetime | None = None,
) -> datetime.datetime:
    """Compute the next publication timestamp with randomized jitter (Part 1.4).

    jitter = interval_minutes * (jitter_pct / 100)
    delay = random.uniform(interval_minutes - jitter, interval_minutes + jitter)
    return base_time + delay
    """
    jitter = interval_minutes * (max(0.0, min(100.0, jitter_pct)) / 100.0)
    delay = random.uniform(max(1.0, interval_minutes - jitter), interval_minutes + jitter)
    start = base_time or datetime.datetime.now(UTC)
    return start + timedelta(minutes=delay)


class CrossPlatformStaggerQueue:
    """Maintains cross-platform eligibility offsets per job_id (Part 1.5).

    When a job is posted or scheduled on Platform A, other platforms receive
    a randomized 10–90 minute delay before they can post about the same job.
    """

    def __init__(self, persistence_path: Path = DEFAULT_STAGGER_FILE) -> None:
        self.persistence_path = persistence_path
        # job_id -> {platform -> eligible_after_iso_timestamp}
        self._stagger_map: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.persistence_path.exists():
            try:
                with open(self.persistence_path, "r", encoding="utf-8") as f:
                    self._stagger_map = json.load(f)
            except Exception as e:
                logger.warning("Failed to load stagger queue from %s: %s", self.persistence_path, e)
                self._stagger_map = {}

    def _save(self) -> None:
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump(self._stagger_map, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save stagger queue to %s: %s", self.persistence_path, e)

    def is_job_eligible(
        self,
        platform: str,
        job_id: str,
        current_time: datetime.datetime | None = None,
    ) -> bool:
        """Check if job_id is eligible to be posted on platform right now."""
        if not job_id:
            return True
        now = current_time or datetime.datetime.now(UTC)
        job_staggers = self._stagger_map.get(str(job_id), {})
        eligible_after_str = job_staggers.get(platform.lower())
        if not eligible_after_str:
            return True
        try:
            eligible_after = datetime.datetime.fromisoformat(eligible_after_str)
            if eligible_after.tzinfo is None:
                eligible_after = eligible_after.replace(tzinfo=UTC)
            return now >= eligible_after
        except Exception:
            return True

    def record_job_posted(
        self,
        posted_platform: str,
        job_id: str,
        post_time: datetime.datetime | None = None,
        min_stagger_min: float = 10.0,
        max_stagger_min: float = 90.0,
    ) -> None:
        """Offset eligibility across all other platforms by 10-90 minutes."""
        if not job_id:
            return
        base = post_time or datetime.datetime.now(UTC)
        posted_platform_clean = posted_platform.lower().strip()
        job_key = str(job_id)

        if job_key not in self._stagger_map:
            self._stagger_map[job_key] = {}

        # Set other platforms to randomized offset
        for p in PLATFORM_PROFILES:
            if p == posted_platform_clean:
                continue
            offset_mins = random.uniform(min_stagger_min, max_stagger_min)
            eligible_after = base + timedelta(minutes=offset_mins)
            self._stagger_map[job_key][p] = eligible_after.isoformat()

        self._save()


class DailyBudgetTracker:
    """Enforces hard daily post-count budgets per platform (Part 1.8 & Part 2)."""

    def __init__(self, persistence_path: Path = DEFAULT_BUDGET_FILE) -> None:
        self.persistence_path = persistence_path
        # platform -> {"date": "YYYY-MM-DD", "count": int}
        self._counts: dict[str, dict[str, Any]] = {}
        self._load()

    def _today_utc(self) -> str:
        return datetime.datetime.now(UTC).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if self.persistence_path.exists():
            try:
                with open(self.persistence_path, "r", encoding="utf-8") as f:
                    self._counts = json.load(f)
            except Exception as e:
                logger.warning("Failed to load daily budget tracker from %s: %s", self.persistence_path, e)
                self._counts = {}

    def _save(self) -> None:
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump(self._counts, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save daily budget tracker: %s", e)

    def get_count(self, platform: str) -> int:
        plat = platform.lower().strip()
        today = self._today_utc()
        data = self._counts.get(plat, {})
        if data.get("date") == today:
            return int(data.get("count", 0))
        return 0

    def can_post(self, platform: str) -> bool:
        """Check if platform has remaining daily quota."""
        plat = platform.lower().strip()
        try:
            profile = get_profile(plat)
            max_posts = profile.cadence.max_posts_per_day
        except KeyError:
            max_posts = 10
        current = self.get_count(plat)
        return current < max_posts

    def record_post(self, platform: str) -> int:
        """Increment daily post count and persist."""
        plat = platform.lower().strip()
        today = self._today_utc()
        current = self.get_count(plat)
        self._counts[plat] = {"date": today, "count": current + 1}
        self._save()
        return current + 1

    def remaining_budget(self, platform: str) -> int:
        plat = platform.lower().strip()
        try:
            profile = get_profile(plat)
            max_posts = profile.cadence.max_posts_per_day
        except KeyError:
            max_posts = 10
        return max(0, max_posts - self.get_count(plat))


class PlatformDeduplicator:
    """Tracks (platform, job_id) pairs to guarantee zero reposts (Part 1.6)."""

    def __init__(self, persistence_path: Path = DEFAULT_DEDUP_FILE) -> None:
        self.persistence_path = persistence_path
        # platform -> set of str job_ids
        self._posted: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if self.persistence_path.exists():
            try:
                with open(self.persistence_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self._posted = {p: set(ids) for p, ids in raw.items()}
            except Exception as e:
                logger.warning("Failed to load social dedup state from %s: %s", self.persistence_path, e)
                self._posted = {}

    def _save(self) -> None:
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump({p: list(ids) for p, ids in self._posted.items()}, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save social dedup state: %s", e)

    def is_posted(self, platform: str, job_id: str) -> bool:
        plat = platform.lower().strip()
        return str(job_id) in self._posted.get(plat, set())

    def mark_posted(self, platform: str, job_id: str) -> None:
        plat = platform.lower().strip()
        if plat not in self._posted:
            self._posted[plat] = set()
        self._posted[plat].add(str(job_id))
        self._save()

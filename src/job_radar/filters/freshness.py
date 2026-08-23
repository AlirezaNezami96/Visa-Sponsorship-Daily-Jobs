"""Job freshness filter.

Determines whether a job posting is recent enough to be included in the digest.
Conservative (fail-open): jobs with missing or unparseable dates are always included.

Supported date formats (as commonly returned by ATS APIs and job boards):
  - ISO 8601: "2025-08-18", "2025-08-18T14:30:00Z", "2025-08-18T14:30:00+03:00"
  - Relative: "N days ago", "N hours ago", "N minutes ago", "yesterday", "Just posted", "Today"
  - Stale sentinel: "30+ days ago" (always treated as stale)
  - None / missing / empty string (fail-open → kept)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Compiled patterns for relative date strings
_RE_DAYS_AGO = re.compile(r"(\d+)\s+days?\s+ago", re.IGNORECASE)
_RE_HOURS_AGO = re.compile(r"(\d+)\s+hours?\s+ago", re.IGNORECASE)
_RE_MINS_AGO = re.compile(r"(\d+)\s+minutes?\s+ago", re.IGNORECASE)
_RE_WEEKS_AGO = re.compile(r"(\d+)\s+weeks?\s+ago", re.IGNORECASE)
_RE_MONTHS_AGO = re.compile(r"(\d+)\s+months?\s+ago", re.IGNORECASE)
_STALE_SENTINELS = frozenset({
    "30+ days ago",
    "more than 30 days ago",
    "over 30 days ago",
})
_FRESH_SENTINELS = frozenset({
    "just posted",
    "today",
    "new",
    "active",
})
_YESTERDAY_TOKENS = frozenset({"yesterday", "1 day ago"})

# ISO-like date prefixes (YYYY-MM-DD)
_RE_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_date_to_days_old(date_str: str) -> Optional[float]:
    """Return how many days old the posting is, or None if unparseable.

    Returns 0.0 for 'just posted / today', -1 for 'yesterday', etc.
    Returns a large sentinel (999) for stale sentinels ("30+ days ago").
    """
    if not date_str:
        return None

    s = date_str.strip().lower()

    if not s:
        return None

    # Explicit stale sentinels
    if s in _STALE_SENTINELS or "30+" in s:
        return 999.0

    # Fresh sentinels
    if s in _FRESH_SENTINELS:
        return 0.0

    # Yesterday
    if s in _YESTERDAY_TOKENS:
        return 1.0

    # Relative: N minutes ago → treat as 0 days
    if _RE_MINS_AGO.search(s):
        return 0.0

    # Relative: N hours ago → treat as 0 days (< 24h)
    match = _RE_HOURS_AGO.search(s)
    if match:
        hours = int(match.group(1))
        return hours / 24.0

    # Relative: N days ago
    match = _RE_DAYS_AGO.search(s)
    if match:
        return float(match.group(1))

    # Relative: N weeks ago
    match = _RE_WEEKS_AGO.search(s)
    if match:
        return float(match.group(1)) * 7

    # Relative: N months ago (approximate)
    match = _RE_MONTHS_AGO.search(s)
    if match:
        return float(match.group(1)) * 30

    # ISO-like date
    iso_match = _RE_ISO_DATE.search(date_str)  # use original (not lower-cased)
    if iso_match:
        try:
            parsed_date = datetime.fromisoformat(iso_match.group(1))
            now = _now_utc().replace(tzinfo=None)
            delta = now - parsed_date
            return max(0.0, delta.total_seconds() / 86400)
        except ValueError:
            pass

    # Full ISO 8601 with time and/or timezone
    try:
        # Strip trailing Z then parse
        normalized = date_str.strip().replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(normalized)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        delta = _now_utc() - parsed_dt
        return max(0.0, delta.total_seconds() / 86400)
    except ValueError:
        pass

    # Unix timestamp (some APIs return seconds-since-epoch as a string)
    try:
        ts = float(date_str.strip())
        posted = datetime.fromtimestamp(ts, tz=timezone.utc)
        delta = _now_utc() - posted
        return max(0.0, delta.total_seconds() / 86400)
    except (ValueError, OSError):
        pass

    # Unparseable
    return None


def is_fresh_enough(job: dict, max_age_days: int = 5) -> bool:
    """Return True if the job is recent enough to include.

    Fail-open: any job without a parseable date is included (returns True).
    Stale sentinels ("30+ days ago") are correctly excluded.

    Args:
        job: Job dict; looks for "date_posted", "posted_at", "posted_date", "created_at".
        max_age_days: Maximum age in days before a job is considered stale.

    Returns:
        True to keep the job, False to discard it.
    """
    # Try several common field names
    date_str: Optional[str] = None
    for field in ("date_posted", "posted_at", "posted_date", "created_at", "published_at"):
        value = job.get(field)
        if value:
            date_str = str(value)
            break

    if not date_str:
        # No date available — fail-open
        return True

    days_old = _parse_date_to_days_old(date_str)

    if days_old is None:
        # Unparseable — fail-open
        logger.debug("Freshness: unparseable date '%s' for '%s', keeping", date_str, job.get("title", "?"))
        return True

    is_fresh = days_old <= max_age_days
    if not is_fresh:
        logger.debug(
            "Freshness: dropping '%s' @ %s (%.1f days old, max %d)",
            job.get("title", "?"), job.get("company", "?"), days_old, max_age_days,
        )
    return is_fresh


def filter_fresh_jobs(jobs: list, max_age_days: int = 5) -> list:
    """Filter a list of job dicts, returning only those within max_age_days."""
    before = len(jobs)
    fresh = [j for j in jobs if is_fresh_enough(j, max_age_days=max_age_days)]
    dropped = before - len(fresh)
    return fresh


is_job_fresh = is_fresh_enough


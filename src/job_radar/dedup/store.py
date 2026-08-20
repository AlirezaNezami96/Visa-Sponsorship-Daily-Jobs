"""Supabase-backed dedup store for the job radar.

Replaces the three separate seen_*.json files with one shared Supabase table.
Shared across all tracks — a job seen in any track won't be re-sent in another.

Graceful fallback: if SUPABASE_URL or SUPABASE_KEY env vars are not set, all
operations become no-ops and the caller falls back to the JSON seen-store.

Table schema (create once in your Supabase SQL editor):

    CREATE TABLE IF NOT EXISTS sent_jobs (
        id           BIGSERIAL PRIMARY KEY,
        fingerprint  TEXT NOT NULL UNIQUE,
        track        TEXT NOT NULL DEFAULT 'unknown',
        title        TEXT,
        company      TEXT,
        url          TEXT,
        ats_score    INT,
        sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Index for fast fingerprint lookups
    CREATE UNIQUE INDEX IF NOT EXISTS sent_jobs_fingerprint_idx ON sent_jobs (fingerprint);
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

_SUPABASE_CLIENT = None
_SUPABASE_AVAILABLE: Optional[bool] = None


def _get_client():
    """Lazily initialize and cache the Supabase client."""
    global _SUPABASE_CLIENT, _SUPABASE_AVAILABLE

    if _SUPABASE_AVAILABLE is False:
        return None

    if _SUPABASE_CLIENT is not None:
        return _SUPABASE_CLIENT

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        logger.debug(
            "SUPABASE_URL or SUPABASE_KEY not set — "
            "Supabase dedup disabled, falling back to JSON seen-store."
        )
        _SUPABASE_AVAILABLE = False
        return None

    try:
        from supabase import create_client
        _SUPABASE_CLIENT = create_client(url, key)
        _SUPABASE_AVAILABLE = True
        logger.info("✅ Connected to Supabase dedup store")
        return _SUPABASE_CLIENT
    except ImportError:
        logger.warning(
            "supabase-py not installed. Run: pip install supabase. "
            "Falling back to JSON seen-store."
        )
        _SUPABASE_AVAILABLE = False
        return None
    except Exception as exc:
        logger.warning("Failed to connect to Supabase: %s. Falling back to JSON seen-store.", exc)
        _SUPABASE_AVAILABLE = False
        return None


def is_available() -> bool:
    """Return True if Supabase is reachable and configured."""
    return _get_client() is not None


def is_already_sent(fingerprint: str, table_name: str = "sent_jobs") -> bool:
    """Check if a job fingerprint has already been sent.

    Returns False (not yet seen) on any error to avoid blocking the pipeline.
    """
    client = _get_client()
    if client is None:
        return False

    try:
        result = (
            client.table(table_name)
            .select("fingerprint", count="exact")
            .eq("fingerprint", fingerprint)
            .limit(1)
            .execute()
        )
        count = getattr(result, "count", None)
        if count is not None:
            return count > 0
        # Fallback: check data list
        return bool(result.data)
    except Exception as exc:
        logger.warning("Supabase is_already_sent error: %s — treating as unseen", exc)
        return False


def mark_sent(
    job: dict,
    track: str = "unknown",
    ats_score: Optional[int] = None,
    fingerprint: Optional[str] = None,
    table_name: str = "sent_jobs",
    dry_run: bool = False,
) -> None:
    """Insert a job fingerprint into the Supabase sent_jobs table.

    Silently no-ops if Supabase is not configured or on any error.
    Uses 'upsert' with on-conflict=ignore so re-insertion is safe.
    """
    if dry_run:
        logger.debug("Supabase mark_sent [DRY RUN] for '%s — %s'", job.get("company"), job.get("title"))
        return

    client = _get_client()
    if client is None:
        return

    # Derive fingerprint from job if not explicitly provided
    if not fingerprint:
        from job_radar.filters.dedupe import job_fingerprint
        fingerprint = job_fingerprint(
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
        )

    row = {
        "fingerprint": fingerprint,
        "track": track,
        "title": job.get("title", "")[:255],
        "company": job.get("company", "")[:255],
        "url": job.get("url", "")[:2048],
        "ats_score": ats_score,
    }

    try:
        client.table(table_name).upsert(row, on_conflict="fingerprint").execute()
        logger.debug("Supabase: marked '%s — %s' as sent (track=%s)", job.get("company"), job.get("title"), track)
    except Exception as exc:
        logger.warning("Supabase mark_sent error: %s — state not persisted for this job", exc)


def bulk_mark_sent(
    jobs: list,
    track: str = "unknown",
    table_name: str = "sent_jobs",
    dry_run: bool = False,
) -> None:
    """Bulk-insert a list of job fingerprints. Uses upsert with on_conflict=ignore."""
    if dry_run or not jobs:
        return

    client = _get_client()
    if client is None:
        return

    from job_radar.filters.dedupe import job_fingerprint

    rows = []
    for job in jobs:
        fp = job_fingerprint(
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
        )
        ats_score = None
        rm = job.get("resume_match")
        if rm and isinstance(rm, dict):
            ats_score = rm.get("ats_score")

        rows.append({
            "fingerprint": fp,
            "track": track,
            "title": job.get("title", "")[:255],
            "company": job.get("company", "")[:255],
            "url": job.get("url", "")[:2048],
            "ats_score": ats_score,
        })

    try:
        client.table(table_name).upsert(rows, on_conflict="fingerprint").execute()
        logger.info("Supabase: bulk-marked %d jobs as sent (track=%s)", len(rows), track)
    except Exception as exc:
        logger.warning("Supabase bulk_mark_sent error: %s — state not persisted for batch", exc)

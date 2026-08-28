"""Sponsor registry runtime freshness and cache fallback management for the Apify Actor."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from job_radar.visa.db import DEFAULT_DB_PATH, load_all_sponsors
from job_radar.visa.ingest_uk import ingest_uk_sponsors

logger = logging.getLogger(__name__)


async def ensure_fresh_registries(
    refresh_requested: bool = False,
    timeout_secs: float = 30.0,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Ensures sponsor registry is ready for the Actor run.
    If refresh_requested is True, attempts to download the live UK sponsor registry with timeout.
    On failure or by default, falls back to the pre-bundled SQLite database.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if refresh_requested:
        logger.info("Live sponsor registry refresh requested. Fetching with %ds timeout...", int(timeout_secs))
        try:
            # Run ingestion in worker thread bounded by timeout
            uk_count = await asyncio.wait_for(
                asyncio.to_thread(ingest_uk_sponsors, db_path=db_path),
                timeout=timeout_secs,
            )
            if uk_count >= 10_000:
                logger.info("Successfully refreshed live UK sponsor registry: %d records ingested.", uk_count)
                return {
                    "sponsors_db_source": "live_cache",
                    "sponsors_db_built": now_iso,
                    "sponsors_count": uk_count,
                }
            else:
                logger.warning("Downloaded registry had only %d records (expected >= 10,000). Using bundled DB.", uk_count)
        except asyncio.TimeoutError:
            logger.warning("Registry live download timed out after %ds. Falling back to bundled sponsor DB.", int(timeout_secs))
        except Exception as e:
            logger.warning("Live registry refresh failed: %s. Falling back to bundled sponsor DB.", e)

    # Fallback to bundled SQLite database
    try:
        sponsors = load_all_sponsors(db_path=db_path, allow_empty=True)
        count = len(sponsors)
    except Exception:
        count = 0

    return {
        "sponsors_db_source": "bundled",
        "sponsors_db_built": now_iso,
        "sponsors_count": count,
    }

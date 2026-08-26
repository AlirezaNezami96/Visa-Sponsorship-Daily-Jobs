"""Cross-Run Deduplication for Apify Actor using a persistent Named Key-Value Store."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from apify import Actor

from job_radar.models.job import Job

logger = logging.getLogger(__name__)

KV_STORE_NAME = "visa-jobs-dedup-state"
DEDUP_STATE_KEY = "DEDUP_STATE"
MAX_DEDUP_ENTRIES = 100_000


class CrossRunDeduplicator:
    """
    Manages job fingerprint state across independent Actor runs to prevent duplicate billing.
    State schema:
    {
        "<sha256_canonical_fingerprint>": {
            "first_seen": "<iso_timestamp>",
            "last_seen": "<iso_timestamp>"
        }
    }
    """

    def __init__(self) -> None:
        self.state: Dict[str, Dict[str, str]] = {}
        self.kv_store: Optional[Any] = None
        self.initialized = False

    async def init(self, reset: bool = False) -> None:
        """Attach to persistent Named Key-Value Store and load historical fingerprint state."""
        try:
            self.kv_store = await Actor.open_key_value_store(name=KV_STORE_NAME)
            if reset:
                logger.info("Cross-run deduplication state reset requested. Starting with fresh state.")
                self.state = {}
                await self.kv_store.set_value(DEDUP_STATE_KEY, self.state)
            else:
                loaded = await self.kv_store.get_value(DEDUP_STATE_KEY)
                if isinstance(loaded, dict):
                    self.state = loaded
                    logger.info("Loaded %d historical job fingerprints from Named KV Store '%s'.", len(self.state), KV_STORE_NAME)
                else:
                    self.state = {}
            self.initialized = True
        except Exception as e:
            logger.warning(
                "Could not initialize Named Key-Value store '%s': %s. Continuing in fail-safe memory mode.",
                KV_STORE_NAME,
                e,
            )
            self.state = {}
            self.initialized = True

    def filter_jobs(
        self,
        jobs: List[Job],
        enabled: bool = True,
        ttl_days: int = 30,
    ) -> Tuple[List[Job], int]:
        """
        Filter out jobs seen within the TTL window.
        Updates state timestamps for retained and newly discovered jobs.
        """
        if not enabled:
            return jobs, 0

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        ttl_seconds = max(1, ttl_days) * 86400

        retained: List[Job] = []
        skipped_count = 0

        for job in jobs:
            fp = job.fingerprint
            if fp in self.state:
                entry = self.state[fp]
                last_seen_str = entry.get("last_seen") or entry.get("first_seen")
                is_recent = False
                if last_seen_str:
                    try:
                        last_seen_dt = datetime.fromisoformat(last_seen_str)
                        if (now_dt - last_seen_dt).total_seconds() < ttl_seconds:
                            is_recent = True
                    except Exception:
                        pass

                if is_recent:
                    skipped_count += 1
                    continue
                else:
                    # Expired, update last_seen
                    entry["last_seen"] = now_iso
                    retained.append(job)
            else:
                # Newly discovered job
                self.state[fp] = {
                    "first_seen": now_iso,
                    "last_seen": now_iso,
                }
                retained.append(job)

        return retained, skipped_count

    async def save_state(self, ttl_days: int = 30) -> None:
        """Prunes expired entries and persists state to Named Key-Value Store."""
        if not self.initialized or self.kv_store is None:
            return

        try:
            now_dt = datetime.now(timezone.utc)
            ttl_seconds = max(1, ttl_days) * 86400

            # 1. Prune expired entries
            pruned_state: Dict[str, Dict[str, str]] = {}
            for fp, entry in self.state.items():
                last_seen_str = entry.get("last_seen") or entry.get("first_seen")
                if last_seen_str:
                    try:
                        last_seen_dt = datetime.fromisoformat(last_seen_str)
                        if (now_dt - last_seen_dt).total_seconds() < ttl_seconds:
                            pruned_state[fp] = entry
                    except Exception:
                        pass

            # 2. Enforce FIFO capacity limit (keep newest MAX_DEDUP_ENTRIES)
            if len(pruned_state) > MAX_DEDUP_ENTRIES:
                sorted_entries = sorted(
                    pruned_state.items(),
                    key=lambda item: item[1].get("last_seen", ""),
                    reverse=True,
                )
                pruned_state = dict(sorted_entries[:MAX_DEDUP_ENTRIES])

            self.state = pruned_state
            await self.kv_store.set_value(DEDUP_STATE_KEY, self.state)
            logger.info("Persisted %d job fingerprints to Named KV Store '%s'.", len(self.state), KV_STORE_NAME)
        except Exception as e:
            logger.warning("Could not persist deduplication state to Named KV Store: %s", e)

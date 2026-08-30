"""Match score caching layer for high-performance job search and matching.

Provides:
  - In-memory LRU/TTL cache for hot (user_id, job_id) scores
  - Supabase database cache persistence with 24-hour TTL
  - Explicit cache invalidation upon user profile or job skills updates
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default in-memory cache TTL: 24 hours
DEFAULT_CACHE_TTL_SECONDS = 24 * 3600
MAX_IN_MEMORY_ENTRIES = 10000


class MatchScoreCache:
    """In-memory + Database-backed cache for computed job match scores."""

    def __init__(self, db_client: Optional[Any] = None, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS):
        self.db_client = db_client
        self.ttl_seconds = ttl_seconds
        # Key: (user_id, job_id) -> (score, timestamp)
        self._memory_cache: Dict[Tuple[str, str], Tuple[int, float]] = {}

    def get(self, user_id: str, job_id: str, now: Optional[float] = None) -> Optional[int]:
        """Get cached score for (user_id, job_id). Returns None on cache miss or expiration."""
        now = time.time() if now is None else now
        key = (user_id, job_id)

        # 1. Check in-memory cache
        if key in self._memory_cache:
            score, ts = self._memory_cache[key]
            if now - ts <= self.ttl_seconds:
                return score
            # Expired
            del self._memory_cache[key]

        # 2. Check Database cache if available
        if self.db_client:
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)).isoformat()
                res = (
                    self.db_client.table("user_job_scores")
                    .select("score, calculated_at")
                    .eq("user_id", user_id)
                    .eq("job_id", job_id)
                    .gte("calculated_at", cutoff)
                    .maybe_single()
                    .execute()
                )
                if res and res.data:
                    score = int(res.data["score"])
                    self._memory_cache[key] = (score, now)
                    return score
            except Exception as exc:
                logger.debug("Database match score cache read failed: %s", exc)

        return None

    def get_many(self, user_id: str, job_ids: List[str]) -> Dict[str, int]:
        """Batch retrieve cached scores for a list of job IDs."""
        now = time.time()
        results: Dict[str, int] = {}
        missing_job_ids: List[str] = []

        for jid in job_ids:
            key = (user_id, jid)
            if key in self._memory_cache:
                score, ts = self._memory_cache[key]
                if now - ts <= self.ttl_seconds:
                    results[jid] = score
                else:
                    del self._memory_cache[key]
                    missing_job_ids.append(jid)
            else:
                missing_job_ids.append(jid)

        if missing_job_ids and self.db_client:
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)).isoformat()
                res = (
                    self.db_client.table("user_job_scores")
                    .select("job_id, score, calculated_at")
                    .eq("user_id", user_id)
                    .in_("job_id", missing_job_ids)
                    .gte("calculated_at", cutoff)
                    .execute()
                )
                rows = res.data if res and res.data else []
                for row in rows:
                    jid = row.get("job_id")
                    if jid:
                        score = int(row["score"])
                        results[jid] = score
                        self._memory_cache[(user_id, jid)] = (score, now)
            except Exception as exc:
                logger.debug("Database batch cache read failed: %s", exc)

        return results

    def set(self, user_id: str, job_id: str, score: int, now: Optional[float] = None) -> None:
        """Store score for (user_id, job_id) in memory and database."""
        now = time.time() if now is None else now
        if len(self._memory_cache) >= MAX_IN_MEMORY_ENTRIES:
            # Simple eviction: drop first 100 entries
            for k in list(self._memory_cache.keys())[:100]:
                self._memory_cache.pop(k, None)

        self._memory_cache[(user_id, job_id)] = (score, now)

        if self.db_client:
            try:
                self.db_client.table("user_job_scores").upsert({
                    "user_id": user_id,
                    "job_id": job_id,
                    "score": score,
                    "calculated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="user_id,job_id").execute()
            except Exception as exc:
                logger.debug("Database match score upsert failed: %s", exc)

    def set_many(self, user_id: str, scores: Dict[str, int]) -> None:
        """Batch store scores."""
        now = time.time()
        for jid, score in scores.items():
            self._memory_cache[(user_id, jid)] = (score, now)

        if self.db_client and scores:
            rows = [
                {
                    "user_id": user_id,
                    "job_id": jid,
                    "score": score,
                    "calculated_at": datetime.now(timezone.utc).isoformat(),
                }
                for jid, score in scores.items()
            ]
            try:
                self.db_client.table("user_job_scores").upsert(rows, on_conflict="user_id,job_id").execute()
            except Exception as exc:
                logger.debug("Database batch match score upsert failed: %s", exc)

    def invalidate_user(self, user_id: str) -> None:
        """Invalidate all cached match scores for a specific user (e.g. after profile update)."""
        keys_to_del = [k for k in self._memory_cache.keys() if k[0] == user_id]
        for k in keys_to_del:
            self._memory_cache.pop(k, None)

        if self.db_client:
            try:
                self.db_client.table("user_job_scores").delete().eq("user_id", user_id).execute()
            except Exception as exc:
                logger.debug("Failed to invalidate DB user cache: %s", exc)

    def invalidate_job(self, job_id: str) -> None:
        """Invalidate all cached match scores for a specific job (e.g. after job skills updated)."""
        keys_to_del = [k for k in self._memory_cache.keys() if k[1] == job_id]
        for k in keys_to_del:
            self._memory_cache.pop(k, None)

        if self.db_client:
            try:
                self.db_client.table("user_job_scores").delete().eq("job_id", job_id).execute()
            except Exception as exc:
                logger.debug("Failed to invalidate DB job cache: %s", exc)

    def clear(self) -> None:
        """Clear all in-memory cache entries."""
        self._memory_cache.clear()


# Global cache instance
_GLOBAL_MATCH_CACHE: Optional[MatchScoreCache] = None


def get_match_score_cache(db_client: Optional[Any] = None) -> MatchScoreCache:
    """Get or create singleton match score cache."""
    global _GLOBAL_MATCH_CACHE
    if _GLOBAL_MATCH_CACHE is None:
        _GLOBAL_MATCH_CACHE = MatchScoreCache(db_client=db_client)
    elif db_client and _GLOBAL_MATCH_CACHE.db_client is None:
        _GLOBAL_MATCH_CACHE.db_client = db_client
    return _GLOBAL_MATCH_CACHE

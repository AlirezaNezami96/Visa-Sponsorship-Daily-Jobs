"""Circuit breaker for ATS and job board scraping endpoints.

Prevents hammering broken or rate-limited ATS providers during a run
if error rates exceed threshold (default: 30% failure rate after min 5 attempts).
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ATSCircuitBreaker:
    """Tracks error rates per ATS provider and halts further calls when tripped."""

    def __init__(self, failure_threshold: float = 0.30, min_attempts: int = 5):
        self.failure_threshold = failure_threshold
        self.min_attempts = min_attempts
        self._lock = threading.Lock()
        self._stats: Dict[str, Dict[str, int]] = {}
        self._tripped: Dict[str, bool] = {}

    def _get_stats(self, ats_name: str) -> Dict[str, int]:
        ats = ats_name.lower()
        if ats not in self._stats:
            self._stats[ats] = {"attempts": 0, "success": 0, "failures": 0}
            self._tripped[ats] = False
        return self._stats[ats]

    def record_success(self, ats_name: str) -> None:
        ats = ats_name.lower()
        with self._lock:
            stats = self._get_stats(ats)
            stats["attempts"] += 1
            stats["success"] += 1

    def record_failure(self, ats_name: str, error: Optional[Exception] = None) -> None:
        ats = ats_name.lower()
        with self._lock:
            stats = self._get_stats(ats)
            stats["attempts"] += 1
            stats["failures"] += 1

            if stats["attempts"] >= self.min_attempts:
                fail_rate = stats["failures"] / stats["attempts"]
                if fail_rate >= self.failure_threshold and not self._tripped.get(ats, False):
                    self._tripped[ats] = True
                    logger.warning(
                        "⚠️ ATS Circuit Breaker TRIPPED for '%s' (Failure rate: %.1f%% across %d companies). Skipping further requests for this run.",
                        ats,
                        fail_rate * 100,
                        stats["attempts"],
                    )

    def is_tripped(self, ats_name: str) -> bool:
        ats = ats_name.lower()
        with self._lock:
            return self._tripped.get(ats, False)

    def get_trip_counts(self) -> Dict[str, int]:
        with self._lock:
            return {ats: stats["failures"] for ats, stats in self._stats.items() if self._tripped.get(ats, False)}

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()
            self._tripped.clear()

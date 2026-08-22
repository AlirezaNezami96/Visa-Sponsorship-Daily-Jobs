"""
src/job_radar/fetchers/funding_watch.py

Maintains a 90-day watchlist of newly funded AI/Tech companies.
Tags matching job postings with recent funding badges and quality boosts.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path("state/funding_watchlist.json")
WATCH_DURATION_SECONDS = 90 * 86400  # 90 days


class FundingWatchlist:
    def __init__(self, storage_path: Path = WATCHLIST_PATH):
        self.storage_path = storage_path
        self._watchlist: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self._watchlist = json.load(f)
            except Exception as e:
                logger.warning("Failed to load funding watchlist from %s: %s", self.storage_path, e)
                self._watchlist = {}
        self._cleanup()

    def _save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._watchlist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save funding watchlist: %s", e)

    def _cleanup(self) -> None:
        now = time.time()
        expired = [k for k, v in self._watchlist.items() if v.get("expires_at", 0) < now]
        for k in expired:
            del self._watchlist[k]
        if expired:
            self._save()

    def add_funded_company(
        self,
        company_name: str,
        round_name: str = "Seed/Series A",
        amount_usd: Optional[float] = None,
        article_url: Optional[str] = None,
        careers_url: Optional[str] = None,
    ) -> None:
        norm = normalize_company_name(company_name)
        if not norm:
            return

        now = time.time()
        self._watchlist[norm] = {
            "company_name": company_name,
            "round": round_name,
            "amount_usd": amount_usd,
            "article_url": article_url,
            "careers_url": careers_url,
            "raised_at": now,
            "expires_at": now + WATCH_DURATION_SECONDS,
        }
        self._save()

    def check_company(self, company_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a company is on the recent funding watchlist.
        Returns (is_watched, description_string).
        """
        norm = normalize_company_name(company_name)
        if not norm or norm not in self._watchlist:
            return False, None

        data = self._watchlist[norm]
        now = time.time()
        days_ago = max(0, int((now - data.get("raised_at", now)) / 86400))
        round_info = data.get("round", "funding")

        desc = f"raised {round_info} {days_ago}d ago"
        return True, desc


# Singleton
_GLOBAL_WATCHLIST: Optional[FundingWatchlist] = None


def get_funding_watchlist() -> FundingWatchlist:
    global _GLOBAL_WATCHLIST
    if _GLOBAL_WATCHLIST is None:
        _GLOBAL_WATCHLIST = FundingWatchlist()
    return _GLOBAL_WATCHLIST

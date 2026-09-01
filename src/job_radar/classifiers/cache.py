"""On-disk caching for LLM classification results."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ClassificationCache:
    """Persistent on-disk cache for LLM classification results."""

    def __init__(self, cache_file: str = "state/classifier_cache.json") -> None:
        self.cache_file = cache_file
        self.cache: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read classifier cache %s: %s", self.cache_file, exc)
                return {}
        return {}

    def get(self, key: str) -> Optional[dict]:
        return self.cache.get(key)

    def set(self, key: str, value: dict) -> None:
        self.cache[key] = {**value, "_cached_at": int(time.time())}

    def save(self) -> None:
        from job_radar.filters.dedupe import atomic_save_json
        try:
            atomic_save_json(self.cache, self.cache_file)
        except Exception as exc:
            logger.warning("Could not save classifier cache %s: %s", self.cache_file, exc)


ClassifierCache = ClassificationCache


def get_classifier_cache(path: str = "state/classifier_cache.json") -> ClassificationCache:
    return ClassificationCache(path)


def make_cache_key(
    company: str,
    title: str,
    description: str = "",
    resume_text: str = "",
    location: str = "",
    url: str = "",
    version: str = "v3-occupation-agnostic",
) -> str:
    """
    Generate deterministic hash key using full available text and prompt version.
    Two jobs sharing identical prefix but different tails will not collide.
    """
    import hashlib
    res_hash = hashlib.sha256(resume_text.strip().encode("utf-8")).hexdigest()[:16] if resume_text else ""
    full_desc = description.strip() or f"{location}|{url}"
    raw = f"{version}|{company.strip().lower()}|{title.strip().lower()}|{full_desc}|{res_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

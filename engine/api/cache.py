"""
Caching layer for VisaLane read-only endpoints.
Provides in-memory TTLCache with optional Redis fallback.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Default in-memory cache with 15-minute default TTL, max 2000 entries
_DEFAULT_TTL = 300  # 5 minutes
_LOCK = threading.Lock()
_IN_MEMORY_CACHES: Dict[int, TTLCache] = {}


def _get_in_memory_cache(ttl_seconds: int) -> TTLCache:
    with _LOCK:
        if ttl_seconds not in _IN_MEMORY_CACHES:
            _IN_MEMORY_CACHES[ttl_seconds] = TTLCache(maxsize=2000, ttl=ttl_seconds)
        return _IN_MEMORY_CACHES[ttl_seconds]


# Optional Redis client
_REDIS_CLIENT = None
_REDIS_CHECKED = False


def _get_redis():
    global _REDIS_CLIENT, _REDIS_CHECKED
    if _REDIS_CHECKED:
        return _REDIS_CLIENT
    _REDIS_CHECKED = True
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        try:
            import redis
            _REDIS_CLIENT = redis.from_url(redis_url, decode_responses=True)
            logger.info("Connected to Redis cache at %s", redis_url.split("@")[-1])
        except Exception as e:
            logger.warning("Redis initialization failed, falling back to in-memory: %s", e)
            _REDIS_CLIENT = None
    return _REDIS_CLIENT


def get_cache(key: str, ttl_seconds: int = _DEFAULT_TTL) -> Optional[Any]:
    """Retrieve value from Redis or in-memory cache."""
    r = _get_redis()
    if r is not None:
        try:
            val = r.get(key)
            if val is not None:
                return json.loads(val)
        except Exception as e:
            logger.warning("Redis get error for %s: %s", key, e)

    cache = _get_in_memory_cache(ttl_seconds)
    with _LOCK:
        return cache.get(key)


def set_cache(key: str, value: Any, ttl_seconds: int = _DEFAULT_TTL) -> None:
    """Store value in Redis or in-memory cache."""
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl_seconds, json.dumps(value, default=str))
        except Exception as e:
            logger.warning("Redis set error for %s: %s", key, e)

    cache = _get_in_memory_cache(ttl_seconds)
    with _LOCK:
        cache[key] = value


def clear_all_caches() -> None:
    """Clear all in-memory caches and Redis (for testing)."""
    with _LOCK:
        for c in _IN_MEMORY_CACHES.values():
            c.clear()
    r = _get_redis()
    if r is not None:
        try:
            r.flushdb()
        except Exception:
            pass


def clear_cache(key: Optional[str] = None) -> None:
    """Clear specific cache key or all caches if key is None."""
    if key is None:
        clear_all_caches()
        return
    with _LOCK:
        for c in _IN_MEMORY_CACHES.values():
            c.pop(key, None)
    r = _get_redis()
    if r is not None:
        try:
            r.delete(key)
        except Exception:
            pass


def make_cache_key(prefix: str, params: Dict[str, Any]) -> str:
    """Generate a deterministic cache key from parameters."""
    sorted_items = sorted((k, str(v)) for k, v in params.items() if v is not None)
    serialized = "&".join(f"{k}={v}" for k, v in sorted_items)
    return f"{prefix}:{serialized}"

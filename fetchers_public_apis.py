"""Public Job Board API Fetchers (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.public_apis import (
    DEFAULT_TIMEOUT,
    FETCHERS_PUBLIC_REGISTRY,
    USER_AGENT,
    _session,
    fetch_all_public_apis,
    fetch_arbeitnow,
    fetch_himalayas,
    fetch_hn_who_is_hiring,
    fetch_remoteok,
    fetch_remotive,
)

__all__ = [
    "fetch_all_public_apis",
    "fetch_remoteok",
    "fetch_remotive",
    "fetch_arbeitnow",
    "fetch_himalayas",
    "fetch_hn_who_is_hiring",
    "FETCHERS_PUBLIC_REGISTRY",
    "USER_AGENT",
    "DEFAULT_TIMEOUT",
    "_session",
]

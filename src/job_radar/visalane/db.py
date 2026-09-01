"""Lazy service-role Supabase client for the VisaLane tables.

The Python pipeline always writes with the service-role key (never exposed to
the FE). All callers must treat a None client as "feature disabled" and
fail open, mirroring job_radar.dedup.store behavior.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_CLIENT = None
_CHECKED = False
_LOCK = threading.Lock()


def get_service_client():
    """Return a cached service-role Supabase client, or None when unconfigured."""
    global _CLIENT, _CHECKED
    with _LOCK:
        if _CHECKED:
            return _CLIENT
        _CHECKED = True

        url = os.environ.get("SUPABASE_URL", "").strip()
        key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or "").strip()
        if not url or not key:
            logger.debug("SUPABASE_URL/SUPABASE_KEY not set — VisaLane sync disabled.")
            return None
        try:
            from supabase import create_client

            _CLIENT = create_client(url, key)
            logger.info("VisaLane: service-role Supabase client ready")
        except Exception as exc:
            logger.warning("VisaLane Supabase client init failed: %s", exc)
            _CLIENT = None
        return _CLIENT


def reset_client_cache() -> None:
    """Test helper: force re-init on next access."""
    global _CLIENT, _CHECKED
    with _LOCK:
        _CLIENT = None
        _CHECKED = False

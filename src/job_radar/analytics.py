"""Vendor-neutral analytics emitter writing to the `analytics_events` table.

Design rules (see master plan section 5):
- No Firebase, no third-party SDK — one Supabase table shared by both runtimes.
- Fail-open: if SUPABASE_URL / SUPABASE_KEY are missing or any request fails,
  events are dropped with a debug log. Analytics must never break the pipeline.
- Batched: buffer in memory, flush at `flush_interval` size or on explicit flush.

The TS Edge Functions write to the same table directly via the service client.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Canonical event names (keep in sync with Edge Function EventTracker).
KNOWN_EVENTS = frozenset(
    {
        "user_signup",
        "profile_completed",
        "resume_parsed",
        "resume_generated",
        "cover_letter_generated",
        "application_completed",
        "alert_created",
        "alert_sent",
        "social_post_published",
        "ai_fallback_triggered",
        "ai_validation_repair",
        "ai_error",
        "api_error",
        # Pipeline-emitted operational events
        "scrape_completed",
        "jobs_added",
        "pipeline_fallback_triggered",
    }
)

DEFAULT_FLUSH_SIZE = 25

_client = None
_client_checked = False
_lock = threading.Lock()


def _get_client():
    """Lazily build a cached Supabase client; None when unconfigured."""
    global _client, _client_checked
    with _lock:
        if _client_checked:
            return _client
        _client_checked = True
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_KEY", "").strip()
        if not url or not key:
            logger.debug("SUPABASE_URL/SUPABASE_KEY not set — analytics emitter disabled.")
            return None
        try:
            from supabase import create_client

            _client = create_client(url, key)
        except Exception as exc:
            logger.debug("Analytics client init failed: %s", exc)
            _client = None
        return _client


class AnalyticsEmitter:
    """In-memory buffered emitter for `analytics_events`."""

    def __init__(self, flush_size: int = DEFAULT_FLUSH_SIZE):
        self.flush_size = max(1, flush_size)
        self._buffer: list[dict[str, Any]] = []

    def emit(
        self,
        event_name: str,
        *,
        user_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Buffer one event; auto-flushes when the buffer reaches flush_size."""
        if event_name not in KNOWN_EVENTS:
            logger.debug("Unknown analytics event '%s' — still recording.", event_name)
        self._buffer.append(
            {
                "event_name": event_name,
                "user_id": user_id,
                "job_id": job_id,
                "metadata": metadata or {},
            }
        )
        if len(self._buffer) >= self.flush_size:
            self.flush()

    def flush(self) -> int:
        """Write buffered events to Supabase. Returns count written (0 on any failure)."""
        if not self._buffer:
            return 0
        batch, self._buffer = self._buffer, []

        client = _get_client()
        if client is None:
            return 0
        try:
            client.table("analytics_events").insert(batch).execute()
            logger.debug("analytics: flushed %d events", len(batch))
            return len(batch)
        except Exception as exc:
            logger.warning("analytics flush failed (%s) — %d events dropped", exc, len(batch))
            return 0


_EMITTER: AnalyticsEmitter | None = None


def get_emitter() -> AnalyticsEmitter:
    global _EMITTER
    if _EMITTER is None:
        _EMITTER = AnalyticsEmitter()
    return _EMITTER


def emit_event(
    event_name: str,
    *,
    user_id: str | None = None,
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Convenience wrapper around the global emitter."""
    get_emitter().emit(event_name, user_id=user_id, job_id=job_id, metadata=metadata)


def flush_events() -> int:
    """Flush the global emitter; call at pipeline shutdown."""
    return get_emitter().flush()

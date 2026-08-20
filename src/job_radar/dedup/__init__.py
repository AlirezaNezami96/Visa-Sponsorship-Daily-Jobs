"""Dedup subpackage — Supabase-backed deduplication store."""
from job_radar.dedup.store import (
    bulk_mark_sent,
    is_already_sent,
    is_available,
    mark_sent,
)

__all__ = [
    "is_available",
    "is_already_sent",
    "mark_sent",
    "bulk_mark_sent",
]

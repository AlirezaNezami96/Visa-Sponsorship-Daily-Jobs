"""Unit tests for match score caching layer."""
from __future__ import annotations

from unittest.mock import MagicMock

from job_radar.jobs.cache import MatchScoreCache, get_match_score_cache


def test_match_score_cache_in_memory():
    cache = MatchScoreCache(ttl_seconds=60)
    now = 1000.0

    # Set and get
    cache.set("u1", "j1", 85, now=now)
    assert cache.get("u1", "j1", now=now) == 85
    assert cache.get("u1", "j2", now=now) is None

    # TTL Expiration
    assert cache.get("u1", "j1", now=now + 50) == 85
    assert cache.get("u1", "j1", now=now + 70) is None


def test_match_score_cache_batch():
    cache = MatchScoreCache(ttl_seconds=60)
    cache.set_many("u1", {"j1": 90, "j2": 75, "j3": 60})

    scores = cache.get_many("u1", ["j1", "j2", "j3", "j4"])
    assert scores == {"j1": 90, "j2": 75, "j3": 60}


def test_match_score_cache_invalidation():
    cache = MatchScoreCache(ttl_seconds=60)
    cache.set("u1", "j1", 80)
    cache.set("u1", "j2", 70)
    cache.set("u2", "j1", 85)

    # Invalidate user u1
    cache.invalidate_user("u1")
    assert cache.get("u1", "j1") is None
    assert cache.get("u1", "j2") is None
    assert cache.get("u2", "j1") == 85

    # Invalidate job j1
    cache.invalidate_job("j1")
    assert cache.get("u2", "j1") is None


def test_match_score_cache_db_sync():
    mock_db = MagicMock()
    cache = MatchScoreCache(db_client=mock_db, ttl_seconds=60)

    cache.set("u1", "j1", 95)
    mock_db.table().upsert().execute.assert_called()

    cache.invalidate_user("u1")
    mock_db.table().delete().eq().execute.assert_called()

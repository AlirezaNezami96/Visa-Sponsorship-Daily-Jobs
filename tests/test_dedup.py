"""Unit tests for CrossRunDeduplicator."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from job_radar.models.job import Job
from apify_actor.dedup import CrossRunDeduplicator, DEDUP_STATE_KEY, KV_STORE_NAME, MAX_DEDUP_ENTRIES


def _make_job(job_id: str, title: str = "Backend Engineer", company: str = "Acme Corp") -> Job:
    return Job(
        id=job_id,
        title=title,
        company=company,
        url=f"https://example.com/jobs/{job_id}",
        location="Remote",
    )


def test_dedup_hash_invariance():
    """Verify that fingerprints are identical for identical company, title, location regardless of scrape time."""
    j1 = _make_job("1", title="Senior Python Developer", company="Google LLC")
    j1.metadata = {"scraped_at": "2026-01-01T00:00:00Z"}
    
    j2 = _make_job("2", title="senior python developer", company="Google")
    j2.metadata = {"scraped_at": "2026-08-26T12:00:00Z"}

    # Fingerprints normalize case and company alias
    assert j1.fingerprint == j2.fingerprint


def test_multi_run_deduplication():
    """Verify that jobs seen in a prior run are filtered out on subsequent runs."""
    async def _test():
        mock_kv = MagicMock()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        j1 = _make_job("1", title="DevOps Engineer", company="Stripe")
        j2 = _make_job("2", title="Frontend Engineer", company="Airbnb")

        # Initial state with j1 already recorded
        initial_state = {
            j1.fingerprint: {
                "first_seen": now_iso,
                "last_seen": now_iso,
            }
        }
        mock_kv.get_value = AsyncMock(return_value=initial_state)
        mock_kv.set_value = AsyncMock()

        dedup = CrossRunDeduplicator()
        with patch("apify.Actor.open_key_value_store", AsyncMock(return_value=mock_kv)):
            await dedup.init(reset=False)

        retained, skipped = dedup.filter_jobs([j1, j2], enabled=True, ttl_days=30)
        assert skipped == 1
        assert len(retained) == 1
        assert retained[0].id == "2"

    asyncio.run(_test())


def test_ttl_expiry_allows_revisit():
    """Verify that jobs seen outside the TTL window are treated as fresh."""
    async def _test():
        mock_kv = MagicMock()
        old_iso = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        
        j1 = _make_job("1", title="DevOps Engineer", company="Stripe")
        initial_state = {
            j1.fingerprint: {
                "first_seen": old_iso,
                "last_seen": old_iso,
            }
        }
        mock_kv.get_value = AsyncMock(return_value=initial_state)
        mock_kv.set_value = AsyncMock()

        dedup = CrossRunDeduplicator()
        with patch("apify.Actor.open_key_value_store", AsyncMock(return_value=mock_kv)):
            await dedup.init(reset=False)

        retained, skipped = dedup.filter_jobs([j1], enabled=True, ttl_days=30)
        assert skipped == 0
        assert len(retained) == 1

    asyncio.run(_test())


def test_fifo_eviction_under_capacity_limit():
    """Verify that save_state prunes expired items and bounds state to MAX_DEDUP_ENTRIES."""
    async def _test():
        mock_kv = MagicMock()
        mock_kv.get_value = AsyncMock(return_value={})
        mock_kv.set_value = AsyncMock()

        dedup = CrossRunDeduplicator()
        with patch("apify.Actor.open_key_value_store", AsyncMock(return_value=mock_kv)):
            await dedup.init(reset=False)

        now_iso = datetime.now(timezone.utc).isoformat()
        # Add excessive number of entries
        for i in range(MAX_DEDUP_ENTRIES + 50):
            dedup.state[f"hash_{i}"] = {
                "first_seen": now_iso,
                "last_seen": now_iso,
            }

        await dedup.save_state(ttl_days=30)
        assert len(dedup.state) == MAX_DEDUP_ENTRIES

    asyncio.run(_test())

"""Unit tests for ApifyDatasetSink Charge-Before-Push and PPE billing integrity."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from job_radar.models.job import Job
from apify_actor.sink import ApifyDatasetSink


def _make_test_job(job_id: str, title: str = "Software Engineer", company: str = "TestCorp") -> Job:
    return Job(
        id=job_id,
        title=title,
        company=company,
        url=f"https://example.com/jobs/{job_id}",
        location="London, UK",
        visa_sponsorship=True,
        visa_confidence="on_sponsor_list",
    )


def test_charge_before_push_order():
    """Verify that Actor.charge is called before Actor.push_data."""
    async def _test():
        call_order = []

        async def mock_charge(event_name: str):
            call_order.append(f"charge:{event_name}")
            res = MagicMock()
            res.event_charge_limit_reached = False
            return res

        async def mock_push_data(data):
            call_order.append(f"push:{len(data)}")

        sink = ApifyDatasetSink(include_description=False)
        jobs = [_make_test_job("1"), _make_test_job("2")]

        with patch("apify.Actor.charge", side_effect=mock_charge), \
             patch("apify.Actor.push_data", side_effect=mock_push_data):
            await sink.emit(jobs)
            await sink.close()

        assert "charge:job-result" in call_order
        assert "charge:visa-enriched-job" in call_order
        # First charge event must happen before push
        first_charge_idx = next(i for i, c in enumerate(call_order) if c.startswith("charge:"))
        first_push_idx = next(i for i, c in enumerate(call_order) if c.startswith("push:"))
        assert first_charge_idx < first_push_idx
        assert sink.emitted_count == 2
        assert sink.dataset_pushed_count == 2

    asyncio.run(_test())


def test_spending_limit_halts_and_discards_uncharged_tail():
    """Verify that when spending limit is reached during charge, only charged prefix is pushed."""
    async def _test():
        charge_count = 0

        async def mock_charge(event_name: str):
            nonlocal charge_count
            res = MagicMock()
            if event_name == "job-result":
                charge_count += 1
                if charge_count > 2:
                    res.event_charge_limit_reached = True
                    return res
            res.event_charge_limit_reached = False
            return res

        pushed_items = []

        async def mock_push_data(data):
            pushed_items.extend(data)

        sink = ApifyDatasetSink(include_description=False)
        jobs = [_make_test_job(str(i)) for i in range(1, 6)]

        with patch("apify.Actor.charge", side_effect=mock_charge), \
             patch("apify.Actor.push_data", side_effect=mock_push_data):
            await sink.emit(jobs)
            await sink.close()

        assert sink.limit_reached is True
        assert sink.emitted_count == 2
        assert sink.dataset_pushed_count == 2
        assert len(pushed_items) == 2

    asyncio.run(_test())


def test_push_retry_failure_saves_recovery_items():
    """Verify that if Actor.push_data fails after retry, charged items are written to RECOVERY_UNPUSHED_ITEMS."""
    async def _test():
        async def mock_charge(event_name: str):
            res = MagicMock()
            res.event_charge_limit_reached = False
            return res

        async def mock_push_data_fail(data):
            raise RuntimeError("Push network failure")

        mock_set_value = AsyncMock()

        sink = ApifyDatasetSink(include_description=False)
        jobs = [_make_test_job("1"), _make_test_job("2")]

        with patch("apify.Actor.charge", side_effect=mock_charge), \
             patch("apify.Actor.push_data", side_effect=mock_push_data_fail), \
             patch("apify.Actor.set_value", mock_set_value):
            await sink.emit(jobs)
            await sink.close()

        assert sink.charged_not_delivered is True
        assert sink.emitted_count == 2
        assert sink.dataset_pushed_count == 0
        assert mock_set_value.call_count >= 1
        assert mock_set_value.call_args_list[0][0][0] == "RECOVERY_UNPUSHED_ITEMS"

    asyncio.run(_test())

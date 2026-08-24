"""Tests for the new non-fatal `overseas-job` PPE event in ApifyDatasetSink.

Invariants under test:
- overseas items charge `overseas-job` and increment `overseas_count`
- a billing failure on `overseas-job` NEVER kills the run (warning only)
- `job-result` charging stays fatal on error (existing behavior)
- the spending-limit path still stops ALL emission (existing behavior)
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from apify_actor.sink import ApifyDatasetSink
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job


class MockChargeResult:
    def __init__(self, limit_reached: bool = False):
        self.event_charge_limit_reached = limit_reached


def _overseas_job(job_id: str = "ov-a.example-1") -> Job:
    return Job(
        id=job_id,
        source="overseas",
        ats="a.example",
        company="Agency",
        title="Mason",
        location="Dubai",
        country="UAE",
        visa_confidence=VisaConfidence.EMPLOYER_SPONSORED_REGION,
        metadata={"overseas": True, "source_category": "manpower_agency"},
    )


def _plain_job(job_id: str = "gh-1") -> Job:
    return Job(
        id=job_id,
        source="greenhouse",
        company="Acme",
        title="Engineer",
        location="London",
        visa_confidence=VisaConfidence.UNKNOWN,
    )


def test_overseas_item_charges_overseas_job_event():
    async def _test():
        sink = ApifyDatasetSink()
        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", new_callable=AsyncMock) as mock_charge:
            mock_charge.return_value = MockChargeResult()

            await sink.emit([_overseas_job()])

            events = [
                c.kwargs.get("event_name") or c.args[0]
                for c in mock_charge.call_args_list
            ]
            assert events == ["job-result", "overseas-job"]
            assert sink.emitted_count == 1
            assert sink.overseas_count == 1
            assert mock_push.call_count == 1

    asyncio.run(_test())


def test_plain_item_does_not_charge_overseas_job_event():
    async def _test():
        sink = ApifyDatasetSink()
        with patch("apify.Actor.push_data", new_callable=AsyncMock), \
             patch("apify.Actor.charge", new_callable=AsyncMock) as mock_charge:
            mock_charge.return_value = MockChargeResult()

            await sink.emit([_plain_job()])

            events = [
                c.kwargs.get("event_name") or c.args[0]
                for c in mock_charge.call_args_list
            ]
            assert events == ["job-result"]
            assert sink.overseas_count == 0
            assert sink.emitted_count == 1

    asyncio.run(_test())


def test_overseas_job_billing_error_is_non_fatal():
    async def _test():
        sink = ApifyDatasetSink()

        async def _charge(*args, **kwargs):
            event_name = kwargs.get("event_name") or (args[0] if args else None)
            if event_name == "overseas-job":
                raise RuntimeError("event not configured")
            return MockChargeResult()

        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", side_effect=_charge) as mock_charge, \
             patch("apify_actor.sink.logger.warning", new_callable=MagicMock) as mock_warn:
            await sink.emit([_overseas_job(), _overseas_job("ov-b.example-2")])

            # Per job: job-result (1) + failing overseas-job attempt (1) = 2; x2 jobs.
            assert mock_charge.call_count == 4
            # No exception escaped; both base emissions succeeded.
            assert sink.emitted_count == 2
            assert sink.overseas_count == 0
            assert mock_warn.call_count == 2
            assert mock_push.call_count == 1

    asyncio.run(_test())


def test_job_result_billing_error_still_fatal():
    async def _test():
        sink = ApifyDatasetSink()
        with patch("apify.Actor.push_data", new_callable=AsyncMock), \
             patch("apify.Actor.charge", new_callable=AsyncMock,
                   side_effect=RuntimeError("payment required")):
            try:
                await sink.emit([_overseas_job()])
                raised = False
            except RuntimeError:
                raised = True
            assert raised, "job-result billing failure must stay fatal"

    asyncio.run(_test())


def test_spending_limit_stops_everything_including_overseas():
    async def _test():
        sink = ApifyDatasetSink()
        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", new_callable=AsyncMock) as mock_charge, \
             patch("apify_actor.sink.logger.warning", new_callable=MagicMock):
            # First job-result trips the spending limit.
            mock_charge.return_value = MockChargeResult(limit_reached=True)

            await sink.emit([_overseas_job("ov-a.example-1"), _overseas_job("ov-b.example-2")])

            assert sink.limit_reached is True
            assert sink.emitted_count == 0
            assert sink.overseas_count == 0
            # Only the single limit-tripping charge happened; nothing after.
            assert mock_charge.call_count == 1
            assert mock_push.call_count == 1

    asyncio.run(_test())


def test_close_logs_overseas_counter():
    async def _test():
        sink = ApifyDatasetSink()
        sink.overseas_count = 7
        with patch("apify.Actor.log.info", new_callable=MagicMock) as mock_log:
            await sink.close()
            line = mock_log.call_args.args[0]
            assert "7 overseas" in line

    asyncio.run(_test())

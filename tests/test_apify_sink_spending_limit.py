"""Tests for ApifyDatasetSink spending limit handling."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from apify_actor.sink import ApifyDatasetSink
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job


class MockChargeResult:
    def __init__(self, limit_reached: bool):
        self.event_charge_limit_reached = limit_reached


def test_spending_limit_stops_emission():
    async def _test():
        sink = ApifyDatasetSink(include_description=True)

        jobs = [
            Job(id="1", company="A", title="SWE", location="Remote", visa_confidence=VisaConfidence.ON_SPONSOR_LIST),
            Job(id="2", company="B", title="SWE", location="Remote", visa_confidence=VisaConfidence.ON_SPONSOR_LIST),
            Job(id="3", company="C", title="SWE", location="Remote", visa_confidence=VisaConfidence.ON_SPONSOR_LIST),
        ]

        # First call hits spending limit
        mock_charge_res = MockChargeResult(limit_reached=True)

        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", new_callable=AsyncMock) as mock_charge, \
             patch("apify.Actor.log.warning", new_callable=MagicMock) as mock_warn:

            mock_charge.return_value = mock_charge_res

            await sink.emit(jobs)

            # First job pushed and charged, but subsequent jobs stopped
            assert sink.limit_reached is True
            assert sink.emitted_count == 1
            assert mock_push.call_count == 1
            assert mock_warn.call_count >= 1

    asyncio.run(_test())

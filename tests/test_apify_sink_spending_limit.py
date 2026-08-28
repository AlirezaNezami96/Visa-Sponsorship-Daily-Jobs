"""Tests for ApifyDatasetSink spending limit handling and billing error escalation."""
import asyncio
import pytest
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
             patch("apify_actor.sink.logger.warning", new_callable=MagicMock) as mock_warn:

            mock_charge.return_value = mock_charge_res

            await sink.emit(jobs)

            # Spending limit encountered -> limit_reached set to True and warning logged
            assert sink.limit_reached is True
            assert mock_push.call_count == 0
            assert mock_warn.call_count >= 1

    asyncio.run(_test())


def test_billing_failure_logs_warning_once():
    async def _test():
        sink = ApifyDatasetSink(include_description=True)
        jobs = [
            Job(id="1", company="A", title="SWE", location="Remote", visa_confidence=VisaConfidence.UNKNOWN),
            Job(id="2", company="B", title="SWE", location="Remote", visa_confidence=VisaConfidence.UNKNOWN),
        ]

        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", new_callable=AsyncMock, side_effect=RuntimeError("Event not configured")), \
             patch("apify_actor.sink.logger.warning", new_callable=MagicMock) as mock_warn:

            await sink.emit(jobs)

            assert mock_push.call_count == 1
            # Warning is logged once per unconfigured event
            assert mock_warn.call_count == 1

    asyncio.run(_test())

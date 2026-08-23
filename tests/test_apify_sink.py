"""Tests for ApifyDatasetSink and PPE monetization events."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from apify_actor.sink import ApifyDatasetSink
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job


def test_apify_dataset_sink_emits_and_charges_ppe():
    async def _test():
        sink = ApifyDatasetSink(include_description=True, include_raw_metadata=False)

        jobs = [
            # Job 1: Standard job with official visa enrichment and AI classification
            Job(
                id="gh-1",
                source="greenhouse",
                company="Stripe",
                title="Senior Engineer",
                location="Berlin, Germany",
                visa_confidence=VisaConfidence.ON_SPONSOR_LIST,
                relevance_score=0.9,
                composite_score=0.85,
            ),
            # Job 2: Unknown visa, no AI classification
            Job(
                id="remoteok-2",
                source="remoteok",
                company="StartupCo",
                title="Junior SWE",
                location="Remote",
                visa_confidence=VisaConfidence.UNKNOWN,
                relevance_score=None,
                composite_score=0.60,
            ),
        ]

        with patch("apify.Actor.push_data", new_callable=AsyncMock) as mock_push, \
             patch("apify.Actor.charge", new_callable=AsyncMock) as mock_charge, \
             patch("apify.Actor.log.info", new_callable=MagicMock) as mock_log:

            await sink.emit(jobs)

            # Batched push: 1 call pushing 2 items
            assert mock_push.call_count == 1
            pushed_items = mock_push.call_args_list[0][0][0]
            assert len(pushed_items) == 2
            first_item = pushed_items[0]
            assert "companyNormalized" in first_item
            assert first_item["companyNormalized"] == "stripe"
            assert first_item["visaSignal"] == "on_sponsor_list"
            assert first_item["visaConfidence"] == 0.85

            # PPE Charges:
            # Job 1: job-result, ai-classified-job, visa-enriched-job (3 charges)
            # Job 2: job-result (1 charge)
            # Total = 4 charges
            assert mock_charge.call_count == 4
            charged_events = [c.kwargs.get("event_name") or c.args[0] for c in mock_charge.call_args_list]
            assert charged_events.count("job-result") == 2
            assert charged_events.count("ai-classified-job") == 1
            assert charged_events.count("visa-enriched-job") == 1

            assert sink.emitted_count == 2
            assert sink.ai_classified_count == 1
            assert sink.visa_enriched_count == 1

            await sink.close()
            assert mock_log.call_count >= 1

    asyncio.run(_test())

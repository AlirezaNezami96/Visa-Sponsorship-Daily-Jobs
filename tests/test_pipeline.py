"""Integration tests for the shared pipeline orchestrator."""
import asyncio
from unittest.mock import AsyncMock, patch

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.orchestrator import run_pipeline
from job_radar.pipeline.sink import InMemoryJobSink


def test_full_pipeline_orchestration_end_to_end():
    async def _test():
        config = JobSearchConfig(
            keywords=["Engineer"],
            visa_sponsorship_only=False,
            posted_within_days=30,
            max_results=10,
            deduplicate_within_run=True,
        )
        sink = InMemoryJobSink()

        mock_jobs_source1 = [
            Job(
                id="gh-1",
                source="greenhouse",
                company="Stripe, Inc.",
                title="Software Engineer",
                location="Berlin, Germany",
                remote=True,
                description="Build payment infrastructure. We offer visa sponsorship.",
            ),
            Job(
                id="gh-2",
                source="greenhouse",
                company="DeepMind",
                title="Research Engineer",
                location="London, UK",
                remote=False,
                description="Frontier AI research.",
            ),
        ]

        mock_jobs_source2 = [
            Job(
                id="remoteok-1",
                source="remoteok",
                company="Stripe",
                title="Software Engineer",
                location="Berlin, Germany",
                remote=True,
                description="Duplicate listing of Stripe SWE.",
            ),
            Job(
                id="remoteok-2",
                source="remoteok",
                company="Example Corp",
                title="Product Designer",  # Should be filtered out by keywords
                location="Remote",
                description="Design modern web products.",
            ),
        ]

        with patch("job_radar.pipeline.orchestrator.fetch_all_sources") as mock_fetch:
            mock_fetch.return_value = (
                mock_jobs_source1 + mock_jobs_source2,
                ["greenhouse", "remoteok"],
                [],
            )

            result = await run_pipeline(config, sink)

            assert len(result.jobs) == 2  # Product Designer filtered; Duplicate Stripe removed
            assert len(sink.jobs) == 2

            titles = [j.title for j in result.jobs]
            assert "Software Engineer" in titles
            assert "Research Engineer" in titles

            for j in result.jobs:
                assert j.composite_score is not None
                assert 0.0 <= j.composite_score <= 1.0

            assert result.stats["totalFetched"] == 4
            assert result.stats["totalDeduplicated"] == 1
            assert result.stats["totalEmitted"] == 2

    asyncio.run(_test())

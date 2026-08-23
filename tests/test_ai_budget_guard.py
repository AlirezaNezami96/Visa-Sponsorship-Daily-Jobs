"""Tests for budget check prior to AI classification stage."""
import asyncio
from unittest.mock import AsyncMock, patch

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.orchestrator import run_pipeline
from job_radar.pipeline.sink import JobSink


class MockSink(JobSink):
    def __init__(self, limit_reached=False):
        self.emitted_jobs = []
        self.stats = {}
        self.limit_reached = limit_reached

    async def emit(self, jobs):
        self.emitted_jobs.extend(jobs)

    async def emit_stats(self, stats):
        self.stats = stats

    async def close(self):
        pass


def test_ai_skipped_when_limit_reached():
    async def _test():
        jobs = [
            Job(id="1", source="greenhouse", company="Stripe", title="SWE", location="Remote", visa_confidence=VisaConfidence.ON_SPONSOR_LIST),
            Job(id="2", source="greenhouse", company="DeepMind", title="SWE", location="Remote", visa_confidence=VisaConfidence.ON_SPONSOR_LIST),
        ]

        config = JobSearchConfig(
            enable_ai_classification=True,
            max_results=10,
            sources=["greenhouse"],
        )

        sink = MockSink(limit_reached=True)

        with patch("job_radar.pipeline.orchestrator.fetch_all_sources", new_callable=AsyncMock) as mock_fetch, \
             patch("job_radar.pipeline.orchestrator.classify_jobs_stage", new_callable=AsyncMock) as mock_classify:

            mock_fetch.return_value = (jobs, ["greenhouse"], [])

            result = await run_pipeline(config, sink)

            # AI classification stage should have been SKIPPED
            assert mock_classify.call_count == 0
            assert result.stats["aiClassifiedJobs"] == 0
            assert len(result.jobs) == 2

    asyncio.run(_test())

"""Tests for AI candidate pre-filtering to protect LLM budget."""
import asyncio
from unittest.mock import AsyncMock, patch

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.orchestrator import run_pipeline
from job_radar.pipeline.sink import JobSink


class MockSink(JobSink):
    def __init__(self):
        self.emitted_jobs = []
        self.stats = {}

    async def emit(self, jobs):
        self.emitted_jobs.extend(jobs)

    async def emit_stats(self, stats):
        self.stats = stats

    async def close(self):
        pass


def test_ai_prefiltering_slices_to_max_results_plus_50():
    async def _test():
        # Create 120 jobs
        jobs = [
            Job(
                id=f"job-{i}",
                source="greenhouse",
                company=f"Company {i}",
                title=f"Engineer {i}",
                location="Remote",
                visa_confidence=VisaConfidence.ON_SPONSOR_LIST if i % 2 == 0 else VisaConfidence.UNKNOWN,
            )
            for i in range(120)
        ]

        config = JobSearchConfig(
            enable_ai_classification=True,
            max_results=10,  # Max results = 10 -> Pre-filter should slice to 10 + 50 = 60
            sources=["greenhouse"],
            visa_sponsorship_only=False,
        )

        sink = MockSink()

        with patch("job_radar.pipeline.orchestrator.fetch_all_sources", new_callable=AsyncMock) as mock_fetch, \
             patch("job_radar.pipeline.orchestrator.classify_jobs_stage", new_callable=AsyncMock) as mock_classify:

            mock_fetch.return_value = (jobs, ["greenhouse"], [])
            mock_classify.side_effect = lambda passed_jobs, cfg: (passed_jobs, len(passed_jobs))

            result = await run_pipeline(config, sink)

            # Assert classify_jobs_stage received ONLY top 60 jobs (10 + 50), not all 120
            assert mock_classify.call_count == 1
            passed_to_ai = mock_classify.call_args_list[0][0][0]
            assert len(passed_to_ai) == 60, f"Expected 60 jobs passed to AI, got {len(passed_to_ai)}"

            # Assert final emitted jobs sliced to max_results = 10
            assert len(result.jobs) == 10
            assert len(sink.emitted_jobs) == 10

    asyncio.run(_test())

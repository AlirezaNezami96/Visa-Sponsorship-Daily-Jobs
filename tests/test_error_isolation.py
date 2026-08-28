"""Tests for error isolation and graceful degradation across sources."""
import asyncio
from unittest.mock import AsyncMock, patch

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.pipeline.orchestrator import fetch_all_sources, run_pipeline
from job_radar.pipeline.sink import InMemoryJobSink


def test_error_isolation_single_source_failure():
    async def _test():
        config = JobSearchConfig(sources=["greenhouse", "lever", "remoteok"])

        with patch("job_radar.sources.greenhouse.GreenhouseAdapter.fetch", new_callable=AsyncMock) as mock_gh, \
             patch("job_radar.sources.lever.LeverAdapter.fetch", new_callable=AsyncMock) as mock_lever, \
             patch("job_radar.sources.remoteok.RemoteOKAdapter.fetch", new_callable=AsyncMock) as mock_remoteok:

            # Greenhouse succeeds
            mock_gh.return_value = [
                Job(id="gh-1", source="greenhouse", company="Stripe", title="SWE", location="Remote", description="Desc")
            ]
            # Lever throws unexpected 500 exception
            mock_lever.side_effect = RuntimeError("HTTP 500 Server Error")
            # RemoteOK succeeds
            mock_remoteok.return_value = [
                Job(id="rok-1", source="remoteok", company="RemoteCo", title="Backend Dev", location="Remote", description="Desc")
            ]

            raw_jobs, successful, failed = await fetch_all_sources(config)

            # Greenhouse and RemoteOK jobs collected
            assert len(raw_jobs) == 2
            assert "greenhouse" in successful
            assert "remoteok" in successful
            assert len(failed) == 1
            assert failed[0]["name"] == "lever"
            assert "HTTP 500" in failed[0]["error"]

    asyncio.run(_test())


def test_all_sources_failing_does_not_crash_pipeline():
    async def _test():
        config = JobSearchConfig(sources=["greenhouse"])
        sink = InMemoryJobSink()

        with patch("job_radar.sources.greenhouse.GreenhouseAdapter.fetch", new_callable=AsyncMock) as mock_gh:
            mock_gh.side_effect = TimeoutError("Connection timed out")

            result = await run_pipeline(config, sink)

            assert len(result.jobs) == 0
            assert len(sink.jobs) == 0
            assert len(result.failed_sources) == 1
            assert result.stats["totalEmitted"] == 0

    asyncio.run(_test())

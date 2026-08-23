"""Remotive job board source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.public_apis import fetch_remotive
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class RemotiveAdapter(SourceAdapter):
    """Adapter for Remotive public API."""

    @property
    def name(self) -> str:
        return "remotive"

    @property
    def source_type(self) -> str:
        return "job_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        queries = ("AI", "machine learning", "software engineer", "developer")
        if config.keywords:
            queries = tuple(config.keywords[:4])

        try:
            raw_dicts = fetch_remotive(queries=queries)
            jobs = [Job.from_legacy_dict(d) for d in raw_dicts]
            if len(jobs) > config.max_per_source:
                jobs = jobs[:config.max_per_source]
            return jobs
        except Exception as e:
            logger.warning("Remotive fetch failed: %s", e)
            return []

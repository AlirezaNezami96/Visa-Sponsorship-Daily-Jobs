"""Hacker News 'Who is Hiring' source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.public_apis import fetch_hn_who_is_hiring
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class HNWhoHiringAdapter(SourceAdapter):
    """Adapter for Hacker News 'Who is Hiring' monthly threads via Algolia."""

    @property
    def name(self) -> str:
        return "hn_whoshiring"

    @property
    def source_type(self) -> str:
        return "aggregator"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        try:
            raw_dicts = fetch_hn_who_is_hiring()
            jobs = [Job.from_legacy_dict(d) for d in raw_dicts]
            if len(jobs) > config.max_per_source:
                jobs = jobs[:config.max_per_source]
            return jobs
        except Exception as e:
            logger.warning("Hacker News Who is Hiring fetch failed: %s", e)
            return []

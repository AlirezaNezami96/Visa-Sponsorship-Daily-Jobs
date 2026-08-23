"""Arbeitnow job board source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.public_apis import fetch_arbeitnow, fetch_arbeitnow_uk
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class ArbeitnowAdapter(SourceAdapter):
    """Adapter for Arbeitnow public API (EU and UK feeds)."""

    @property
    def name(self) -> str:
        return "arbeitnow"

    @property
    def source_type(self) -> str:
        return "job_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        all_jobs: List[Job] = []
        try:
            raw_eu = fetch_arbeitnow()
            all_jobs.extend([Job.from_legacy_dict(d) for d in raw_eu])
        except Exception as e:
            logger.warning("Arbeitnow EU fetch failed: %s", e)

        try:
            raw_uk = fetch_arbeitnow_uk()
            all_jobs.extend([Job.from_legacy_dict(d) for d in raw_uk])
        except Exception as e:
            logger.warning("Arbeitnow UK fetch failed: %s", e)

        if len(all_jobs) > config.max_per_source:
            all_jobs = all_jobs[:config.max_per_source]
        return all_jobs

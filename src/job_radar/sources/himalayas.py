"""Himalayas job board source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.public_apis import fetch_himalayas
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class HimalayasAdapter(SourceAdapter):
    """Adapter for Himalayas public remote jobs API."""

    @property
    def name(self) -> str:
        return "himalayas"

    @property
    def source_type(self) -> str:
        return "job_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        try:
            raw_dicts = fetch_himalayas()
            jobs = [Job.from_legacy_dict(d) for d in raw_dicts]
            if len(jobs) > config.max_per_source:
                jobs = jobs[:config.max_per_source]
            return jobs
        except Exception as e:
            logger.warning("Himalayas fetch failed: %s", e)
            return []

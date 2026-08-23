"""RemoteOK job board source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.public_apis import fetch_remoteok
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class RemoteOKAdapter(SourceAdapter):
    """Adapter for RemoteOK public API."""

    @property
    def name(self) -> str:
        return "remoteok"

    @property
    def source_type(self) -> str:
        return "job_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        tags = ("ai", "machine-learning", "intern", "junior", "engineer", "software")
        if config.keywords:
            tags = tuple(k.lower().replace(" ", "-") for k in config.keywords[:4])

        try:
            raw_dicts = fetch_remoteok(tags=tags)
            jobs = [Job.from_legacy_dict(d) for d in raw_dicts]
            if len(jobs) > config.max_per_source:
                jobs = jobs[:config.max_per_source]
            return jobs
        except Exception as e:
            logger.warning("RemoteOK fetch failed: %s", e)
            return []

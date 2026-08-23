"""Lever ATS source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.ats import fetch_lever
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.ats_utils import extract_slug_from_url, get_curated_companies_for_ats
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class LeverAdapter(SourceAdapter):
    """Adapter for Lever ATS job boards."""

    @property
    def name(self) -> str:
        return "lever"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        all_jobs: List[Job] = []

        slugs = set()
        if config.company_urls:
            for url in config.company_urls:
                slug = extract_slug_from_url(url, "lever")
                if slug:
                    slugs.add(slug)

        if config.company_names:
            for name in config.company_names:
                slugs.add(name.lower().replace(" ", "-"))

        if not slugs and not config.company_urls and not config.company_names:
            curated = get_curated_companies_for_ats("lever")
            for c in curated:
                slug = c.get("slug") or c.get("name", "").lower().replace(" ", "-")
                if slug:
                    slugs.add(slug)

        days_back = config.posted_within_days or 30

        for slug in slugs:
            try:
                jobs = fetch_lever(slug=slug, days_back=days_back)
                all_jobs.extend(jobs)
                if len(all_jobs) >= config.max_per_source:
                    all_jobs = all_jobs[:config.max_per_source]
                    break
            except Exception as e:
                logger.debug("Error fetching lever for %s: %s", slug, e)

        return all_jobs

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        slug = extract_slug_from_url(company_url, "lever")
        if not slug:
            return []
        days_back = config.posted_within_days or 30
        return fetch_lever(slug=slug, days_back=days_back)

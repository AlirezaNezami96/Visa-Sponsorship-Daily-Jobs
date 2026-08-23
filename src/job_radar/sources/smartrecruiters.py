"""SmartRecruiters ATS source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.ats import fetch_smartrecruiters
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.ats_utils import extract_slug_from_url, get_curated_companies_for_ats
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class SmartRecruitersAdapter(SourceAdapter):
    """Adapter for SmartRecruiters ATS job boards."""

    @property
    def name(self) -> str:
        return "smartrecruiters"

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
                slug = extract_slug_from_url(url, "smartrecruiters")
                if slug:
                    slugs.add(slug)

        if config.company_names:
            for name in config.company_names:
                slugs.add(name.lower().replace(" ", "-"))

        if not slugs and not config.company_urls and not config.company_names:
            curated = get_curated_companies_for_ats("smartrecruiters")
            for c in curated:
                slug = c.get("slug") or c.get("name", "").lower().replace(" ", "-")
                if slug:
                    slugs.add(slug)

        days_back = config.posted_within_days or 30

        for slug in slugs:
            try:
                jobs = fetch_smartrecruiters(slug=slug, days_back=days_back)
                all_jobs.extend(jobs)
                if len(all_jobs) >= config.max_per_source:
                    all_jobs = all_jobs[:config.max_per_source]
                    break
            except Exception as e:
                logger.debug("Error fetching smartrecruiters for %s: %s", slug, e)

        return all_jobs

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        slug = extract_slug_from_url(company_url, "smartrecruiters")
        if not slug:
            return []
        days_back = config.posted_within_days or 30
        return fetch_smartrecruiters(slug=slug, days_back=days_back)

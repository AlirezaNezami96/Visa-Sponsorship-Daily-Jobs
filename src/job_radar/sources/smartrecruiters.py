"""SmartRecruiters ATS source adapter."""
from __future__ import annotations

import logging
from typing import List

from job_radar.fetchers.ats import fetch_smartrecruiters
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.ats_utils import (
    extract_slug_from_url,
    fetch_ats_companies_concurrently,
    get_curated_companies_for_ats,
)
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class SmartRecruitersAdapter(SourceAdapter):
    """Adapter for SmartRecruiters ATS job boards with bounded concurrency and per-company timeouts."""

    @property
    def name(self) -> str:
        return "smartrecruiters"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
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
        max_per_source = config.max_per_source or 500

        return await fetch_ats_companies_concurrently(
            slugs=slugs,
            fetch_fn=fetch_smartrecruiters,
            days_back=days_back,
            max_per_source=max_per_source,
            concurrency=5,
        )

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        slug = extract_slug_from_url(company_url, "smartrecruiters")
        if not slug:
            return []
        days_back = config.posted_within_days or 30
        return await fetch_ats_companies_concurrently(
            slugs=[slug],
            fetch_fn=fetch_smartrecruiters,
            days_back=days_back,
            max_per_source=config.max_per_source or 500,
        )

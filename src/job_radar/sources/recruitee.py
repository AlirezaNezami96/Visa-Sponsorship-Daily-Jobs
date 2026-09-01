"""
src/job_radar/sources/recruitee.py

Recruitee ATS Source Adapter.
Interacts with Recruitee public JSON API endpoint: https://{company}.recruitee.com/api/offers/
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.ats_utils import (
    extract_slug_from_url,
    fetch_ats_companies_concurrently,
    get_curated_companies_for_ats,
)
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def parse_recruitee_slug(url_or_slug: str) -> str:
    if not url_or_slug:
        return ""
    u = url_or_slug.strip().lower()
    if "recruitee.com" in u:
        parsed = urllib.parse.urlparse(u if "://" in u else f"https://{u}")
        return parsed.netloc.split(".")[0]
    return u.split("/")[0]


def fetch_recruitee_jobs(
    slug_or_url: str,
    days_back: int = 30,
    limit: int = 50,
) -> List[Job]:
    """Fetch jobs from Recruitee public JSON API."""
    company_slug = parse_recruitee_slug(slug_or_url)
    if not company_slug:
        return []

    api_url = f"https://{company_slug}.recruitee.com/api/offers/"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    jobs: List[Job] = []
    try:
        resp = requests.get(api_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return []

        data = resp.json()
        offers = data.get("offers", []) if isinstance(data, dict) else []
        company_name = company_slug.replace("-", " ").title()

        for item in offers[:limit]:
            title = item.get("title", "").strip()
            if not title:
                continue

            job_id = str(item.get("id", ""))
            careers_url = item.get("careers_url") or f"https://{company_slug}.recruitee.com/o/{item.get('slug', job_id)}"
            loc_city = item.get("city") or ""
            loc_country = item.get("country") or ""
            location = f"{loc_city}, {loc_country}".strip(", ") or "Onsite"

            is_remote = bool(item.get("remote")) or "remote" in location.lower()
            dept = item.get("department") or ""

            raw_desc = item.get("description") or ""
            snippet = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)[:300] if raw_desc else ""

            jobs.append(
                Job(
                    id=f"recruitee-{company_slug}-{job_id}",
                    source="recruitee",
                    ats="recruitee",
                    company=company_name,
                    title=title,
                    location=location,
                    remote=is_remote,
                    department=dept,
                    apply_url=careers_url,
                    job_url=careers_url,
                    date_posted=item.get("created_at"),
                    description=snippet or f"{title} at {company_name}",
                )
            )
    except Exception as exc:
        logger.debug("Recruitee fetch failed for %s: %s", slug_or_url, exc)

    return jobs


class RecruiteeAdapter(SourceAdapter):
    """Adapter for Recruitee ATS."""

    @property
    def name(self) -> str:
        return "recruitee"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return fetch_recruitee_jobs(company_url, days_back=config.posted_within_days or 30)

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        curated = get_curated_companies_for_ats(
            "recruitee",
            limit=getattr(config, "max_companies_per_ats", 50) or 50,
        )
        if not curated:
            return []

        slugs = [c.get("careers_url") or c.get("slug") or c.get("name") for c in curated if c]
        slugs = [s for s in slugs if s]

        return await fetch_ats_companies_concurrently(
            slugs=slugs,
            fetch_fn=fetch_recruitee_jobs,
            days_back=config.posted_within_days or 30,
            max_per_source=config.max_per_source,
            concurrency=config.concurrency or 5,
        )

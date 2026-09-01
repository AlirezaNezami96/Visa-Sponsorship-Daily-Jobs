"""
src/job_radar/sources/bamboohr.py

BambooHR ATS Source Adapter.
Interacts with BambooHR public jobs endpoints ({subdomain}.bamboohr.com/careers/list or /jobs/embed).
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


def parse_bamboohr_subdomain(url_or_subdomain: str) -> str:
    """Extract BambooHR subdomain."""
    if not url_or_subdomain:
        return ""
    u = url_or_subdomain.strip().lower()
    if "bamboohr.com" in u:
        parsed = urllib.parse.urlparse(u if "://" in u else f"https://{u}")
        return parsed.netloc.split(".")[0]
    return u.split("/")[0]


def fetch_bamboohr_jobs(
    subdomain_or_url: str,
    days_back: int = 30,
    limit: int = 50,
) -> List[Job]:
    """Fetch jobs from BambooHR public careers JSON endpoint."""
    subdomain = parse_bamboohr_subdomain(subdomain_or_url)
    if not subdomain:
        return []

    api_url = f"https://{subdomain}.bamboohr.com/careers/list"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    jobs: List[Job] = []
    try:
        resp = requests.get(api_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return []

        data = resp.json()
        job_list = data.get("result", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        company_name = subdomain.replace("-", " ").title()

        for item in job_list:
            title = item.get("jobOpeningName") or item.get("title", "")
            if not title:
                continue

            job_id = str(item.get("id", ""))
            job_url = f"https://{subdomain}.bamboohr.com/careers/{job_id}" if job_id else f"https://{subdomain}.bamboohr.com/careers"
            location = item.get("location", {}).get("city") if isinstance(item.get("location"), dict) else item.get("location", "")
            is_remote = bool(item.get("isRemote") or "remote" in str(location).lower())

            dept = item.get("department") or ""

            jobs.append(
                Job(
                    id=f"bamboohr-{subdomain}-{job_id}",
                    source="bamboohr",
                    ats="bamboohr",
                    company=company_name,
                    title=title.strip(),
                    location=str(location).strip() or "Onsite",
                    remote=is_remote,
                    department=dept,
                    apply_url=job_url,
                    job_url=job_url,
                    description=f"{title} at {company_name} ({dept})",
                )
            )
    except Exception as exc:
        logger.debug("BambooHR fetch failed for %s: %s", subdomain_or_url, exc)

    return jobs


class BambooHRAdapter(SourceAdapter):
    """Adapter for BambooHR ATS."""

    @property
    def name(self) -> str:
        return "bamboohr"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return fetch_bamboohr_jobs(company_url, days_back=config.posted_within_days or 30)

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        curated = get_curated_companies_for_ats(
            "bamboohr",
            limit=getattr(config, "max_companies_per_ats", 50) or 50,
        )
        if not curated:
            return []

        slugs = [c.get("careers_url") or c.get("slug") or c.get("name") for c in curated if c]
        slugs = [s for s in slugs if s]

        return await fetch_ats_companies_concurrently(
            slugs=slugs,
            fetch_fn=fetch_bamboohr_jobs,
            days_back=config.posted_within_days or 30,
            max_per_source=config.max_per_source,
            concurrency=config.concurrency or 5,
        )

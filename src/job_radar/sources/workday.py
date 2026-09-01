"""
src/job_radar/sources/workday.py

Workday Enterprise ATS Source Adapter.
Interacts with Workday CXS / Wday public JSON career endpoints across enterprise employers,
hospitals, universities, banks, and industrial corporations.
"""
from __future__ import annotations

import datetime
import logging
import re
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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def parse_workday_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parse a Workday careers URL into (host, tenant, site_id).
    Example: https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
    """
    if not url:
        return None
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"

    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "myworkdayjobs.com" not in host:
        return None

    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    tenant = host.split(".")[0]
    site_id = path_parts[0] if path_parts else "External"

    return {
        "host": host,
        "tenant": tenant,
        "site_id": site_id,
        "base_api_url": f"https://{host}/wday/cxs/{tenant}/{site_id}/jobs",
    }


def fetch_workday_jobs(
    slug_or_url: str,
    days_back: int = 30,
    limit: int = 50,
) -> List[Job]:
    """
    Fetch job postings from a Workday career site JSON endpoint.
    """
    wday_info = parse_workday_url(slug_or_url)
    if not wday_info:
        # Assume slug is tenant and default site
        tenant = slug_or_url.strip().lower()
        host = f"{tenant}.wd1.myworkdayjobs.com"
        wday_info = {
            "host": host,
            "tenant": tenant,
            "site_id": "External",
            "base_api_url": f"https://{host}/wday/cxs/{tenant}/External/jobs",
        }

    api_url = wday_info["base_api_url"]
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "appliedFacets": {},
        "limit": min(limit, 50),
        "offset": 0,
        "searchText": "",
    }

    jobs: List[Job] = []
    page_limit = 50
    offset = 0
    max_to_fetch = limit or 500

    try:
        while offset < max_to_fetch:
            payload = {
                "appliedFacets": {},
                "limit": page_limit,
                "offset": offset,
                "searchText": "",
            }
            resp = requests.post(api_url, headers=headers, json=payload, timeout=15)
            if resp.status_code != 200:
                if offset == 0:
                    logger.debug("Workday API returned HTTP %d for %s", resp.status_code, api_url)
                break

            data = resp.json()
            job_postings = data.get("jobPostings", [])
            if not job_postings:
                break

            company_name = wday_info["tenant"].replace("-", " ").title()

            for item in job_postings:
                title = item.get("title", "").strip()
                if not title:
                    continue

                external_path = item.get("externalPath", "")
                job_url = f"https://{wday_info['host']}{external_path}" if external_path else ""
                job_id = item.get("bulletFields", [None])[0] or item.get("id") or external_path.strip("/")

                posted_str = item.get("postedOn")  # e.g., "Posted 2 Days Ago", "Posted Yesterday"
                location = item.get("locationsText", "") or "Onsite"

                is_remote = "remote" in location.lower() or "remote" in title.lower()

                jobs.append(
                    Job(
                        id=f"workday-{wday_info['tenant']}-{job_id}",
                        source="workday",
                        ats="workday",
                        company=company_name,
                        title=title,
                        location=location,
                        remote=is_remote,
                        apply_url=job_url,
                        job_url=job_url,
                        date_posted=posted_str,
                        description=f"{title} at {company_name} ({location})",
                    )
                )
                if len(jobs) >= max_to_fetch:
                    break

            total = data.get("total", len(jobs))
            offset += page_limit
            if offset >= total:
                break
    except Exception as exc:
        logger.debug("Workday fetch failed for %s: %s", slug_or_url, exc)

    return jobs


class WorkdayAdapter(SourceAdapter):
    """Adapter for Workday Enterprise ATS."""

    @property
    def name(self) -> str:
        return "workday"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return fetch_workday_jobs(company_url, days_back=config.posted_within_days or 30)

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        curated = get_curated_companies_for_ats(
            "workday",
            limit=getattr(config, "max_companies_per_ats", 50) or 50,
        )
        if not curated:
            return []

        slugs = [c.get("careers_url") or c.get("slug") or c.get("name") for c in curated if c]
        slugs = [s for s in slugs if s]

        return await fetch_ats_companies_concurrently(
            slugs=slugs,
            fetch_fn=fetch_workday_jobs,
            days_back=config.posted_within_days or 30,
            max_per_source=config.max_per_source,
            concurrency=config.concurrency or 5,
        )

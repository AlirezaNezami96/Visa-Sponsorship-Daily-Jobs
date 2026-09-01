"""
src/job_radar/sources/taleo.py

Oracle Taleo Enterprise ATS Source Adapter.
Parses Taleo enterprise career portal endpoints (e.g. {company}.taleo.net/careersection).
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


def parse_taleo_url(url: str) -> Optional[Dict[str, str]]:
    """Extract Taleo tenant domain and career section."""
    if not url:
        return None
    u = url.strip()
    if not u.startswith("http"):
        u = f"https://{u}"
    parsed = urllib.parse.urlparse(u)
    if "taleo.net" not in parsed.netloc:
        return None
    tenant = parsed.netloc.split(".")[0]
    return {
        "tenant": tenant,
        "host": parsed.netloc,
        "url": u,
    }


def fetch_taleo_jobs(
    slug_or_url: str,
    days_back: int = 30,
    limit: int = 50,
) -> List[Job]:
    """Fetch jobs from Oracle Taleo career section."""
    info = parse_taleo_url(slug_or_url)
    if not info:
        tenant = slug_or_url.strip().lower()
        info = {
            "tenant": tenant,
            "host": f"{tenant}.taleo.net",
            "url": f"https://{tenant}.taleo.net/careersection/2/jobsearch.ftl",
        }

    headers = {"User-Agent": USER_AGENT}
    jobs: List[Job] = []
    try:
        resp = requests.get(info["url"], headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        company_name = info["tenant"].replace("-", " ").title()

        # Parse Taleo HTML job table
        rows = soup.find_all("tr", class_=lambda c: c and "taleo" in c.lower()) or soup.find_all("div", class_=lambda c: c and "job" in c.lower())
        for idx, row in enumerate(rows[:limit]):
            title_tag = row.find("a") or row.find("h3") or row.find("span")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            link = title_tag.get("href", "") if title_tag.name == "a" else ""
            if link and not link.startswith("http"):
                link = f"https://{info['host']}{link}"

            jobs.append(
                Job(
                    id=f"taleo-{info['tenant']}-{idx}",
                    source="taleo",
                    ats="taleo",
                    company=company_name,
                    title=title,
                    location="Onsite",
                    remote=False,
                    apply_url=link or info["url"],
                    job_url=link or info["url"],
                    description=f"{title} at {company_name}",
                )
            )
    except Exception as exc:
        logger.debug("Taleo fetch failed for %s: %s", slug_or_url, exc)

    return jobs


class TaleoAdapter(SourceAdapter):
    """Adapter for Oracle Taleo Enterprise ATS."""

    @property
    def name(self) -> str:
        return "taleo"

    @property
    def source_type(self) -> str:
        return "ats"

    def supports_company_urls(self) -> bool:
        return True

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return fetch_taleo_jobs(company_url, days_back=config.posted_within_days or 30)

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        curated = get_curated_companies_for_ats(
            "taleo",
            limit=getattr(config, "max_companies_per_ats", 50) or 50,
        )
        if not curated:
            return []

        slugs = [c.get("careers_url") or c.get("slug") or c.get("name") for c in curated if c]
        slugs = [s for s in slugs if s]

        return await fetch_ats_companies_concurrently(
            slugs=slugs,
            fetch_fn=fetch_taleo_jobs,
            days_back=config.posted_within_days or 30,
            max_per_source=config.max_per_source,
            concurrency=config.concurrency or 5,
        )

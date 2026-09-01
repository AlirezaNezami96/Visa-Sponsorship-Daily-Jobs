"""
src/job_radar/sources/energyjobline.py

Energy Jobline Global Energy & Renewables Vertical Source Adapter.
Scrapes jobs from Energy Jobline covering oil, gas, renewable energy, solar, wind, and nuclear sectors.
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job, WorkplaceType
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (VisaLane/1.0; +https://github.com)"

ENERGY_JOBLINE_URL = "https://www.energyjobline.com/jobs/"


def parse_energyjobline_html(html_content: str) -> List[Job]:
    """Parse Energy Jobline HTML job postings into Job objects."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    items = soup.find_all("li", class_=lambda c: c and ("lister__item" in c or "job-item" in c))
    if not items:
        items = soup.find_all(["div", "article"], class_=lambda c: c and "job" in c.lower())

    for item in items:
        link_elem = item.find("a", href=lambda h: h and "/job/" in h)
        if not link_elem:
            link_elem = item.find("a", href=True)
        if not link_elem or not link_elem.get("href"):
            continue

        title = link_elem.get_text(strip=True)
        if not title or len(title) < 4:
            continue

        href = link_elem["href"]
        if not href.startswith("http"):
            href = f"https://www.energyjobline.com{href}"

        company_elem = item.find(["span", "div", "p"], class_=lambda c: c and "company" in c.lower())
        company = company_elem.get_text(strip=True) if company_elem else "Energy Sector Employer"

        loc_elem = item.find(["span", "div", "li"], class_=lambda c: c and "location" in c.lower())
        location = loc_elem.get_text(strip=True) if loc_elem else "Global"

        desc_elem = item.find(["div", "p"], class_=lambda c: c and ("description" in c.lower() or "summary" in c.lower()))
        desc = desc_elem.get_text(strip=True) if desc_elem else f"{title} at {company} ({location})"

        job_id = f"energyjobline-{re.sub(r'[^a-zA-Z0-9]', '-', href)[-30:]}"
        is_remote = "remote" in location.lower() or "remote" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="energyjobline",
                company=company,
                title=title,
                location=location,
                location_raw=location,
                locations=[location] if location else [],
                remote=is_remote,
                is_remote=is_remote,
                workplace_type=WorkplaceType.REMOTE.value if is_remote else WorkplaceType.ONSITE.value,
                apply_url=href,
                job_url=href,
                url=href,
                description=desc,
                fetched_at=fetched_at,
            )
        )

    return jobs


class EnergyJoblineAdapter(SourceAdapter):
    """Adapter for Energy Jobline renewable and conventional energy roles."""

    @property
    def name(self) -> str:
        return "energyjobline"

    @property
    def source_type(self) -> str:
        return "vertical_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        max_per_source = config.max_per_source or 500

        try:
            resp = requests.get(ENERGY_JOBLINE_URL, headers=headers, timeout=15)
            if resp.status_code == 200:
                jobs = parse_energyjobline_html(resp.text)
                logger.info("EnergyJobline adapter fetched %d jobs.", len(jobs))
                return jobs[:max_per_source]
        except Exception as exc:
            logger.debug("Failed fetching EnergyJobline: %s", exc)

        return []

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

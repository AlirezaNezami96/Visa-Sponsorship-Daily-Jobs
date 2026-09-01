"""
src/job_radar/sources/bayt.py

Bayt Middle East & Gulf Region Job Source Adapter.
Scrapes jobs from Bayt across UAE, Saudi Arabia, Qatar, and the wider MENA region.
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

BAYT_FEEDS = [
    ("AE", "https://www.bayt.com/en/uae/jobs/information-technology-jobs/"),
    ("SA", "https://www.bayt.com/en/saudi-arabia/jobs/information-technology-jobs/"),
    ("QA", "https://www.bayt.com/en/qatar/jobs/information-technology-jobs/"),
]


def parse_bayt_html(html_content: str, country_code: str = "AE") -> List[Job]:
    """Parse Bayt HTML job cards into Job objects."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cards = soup.find_all("li", attrs={"data-js-job": True})
    if not cards:
        cards = soup.find_all(["div", "li"], class_=lambda c: c and ("job-item" in c or "has-pointer-d" in c))

    for card in cards:
        title_elem = card.find(["h2", "a"], class_=lambda c: c and ("jb-title" in c or "job-title" in c or "title" in c))
        if not title_elem:
            title_elem = card.find("a", href=lambda h: h and "/job/" in h)
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        link = title_elem.get("href", "")
        if link.startswith("/"):
            link = f"https://www.bayt.com{link}"

        company_elem = card.find(["b", "span", "div"], class_=lambda c: c and ("jb-company" in c or "company" in c.lower()))
        company = company_elem.get_text(strip=True) if company_elem else "Bayt Employer"

        loc_elem = card.find(["span", "div"], class_=lambda c: c and ("jb-loc" in c or "location" in c.lower()))
        location = loc_elem.get_text(strip=True) if loc_elem else country_code

        desc_elem = card.find(["div", "p"], class_=lambda c: c and ("jb-descr" in c or "description" in c.lower()))
        desc = desc_elem.get_text(strip=True) if desc_elem else f"{title} at {company} ({location})"

        job_id = f"bayt-{country_code.lower()}-{re.sub(r'[^a-zA-Z0-9]', '-', link)[-30:]}"
        is_remote = "remote" in location.lower() or "remote" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="bayt",
                company=company,
                title=title,
                location=location,
                location_raw=location,
                locations=[location] if location else [],
                country=country_code,
                remote=is_remote,
                is_remote=is_remote,
                workplace_type=WorkplaceType.REMOTE.value if is_remote else WorkplaceType.ONSITE.value,
                apply_url=link,
                job_url=link,
                url=link,
                description=desc,
                fetched_at=fetched_at,
            )
        )

    return jobs


class BaytAdapter(SourceAdapter):
    """Adapter for Bayt Middle East & Gulf jobs."""

    @property
    def name(self) -> str:
        return "bayt"

    @property
    def source_type(self) -> str:
        return "regional_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, url in BAYT_FEEDS:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_bayt_html(resp.text, country_code=country_code)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching Bayt %s: %s", country_code, exc)
                continue

        logger.info("Bayt adapter fetched %d jobs across MENA.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

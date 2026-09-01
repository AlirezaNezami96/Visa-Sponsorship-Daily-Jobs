"""
src/job_radar/sources/gulftalent.py

GulfTalent Middle East & GCC Professional Job Source Adapter.
Scrapes jobs from GulfTalent across UAE, Saudi Arabia, Qatar, Kuwait, Bahrain, and Oman.
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

GULFTALENT_URLS = [
    ("AE", "https://www.gulftalent.com/uae/jobs/category/information-technology"),
    ("SA", "https://www.gulftalent.com/saudi-arabia/jobs/category/information-technology"),
    ("QA", "https://www.gulftalent.com/qatar/jobs/category/information-technology"),
]


def parse_gulftalent_html(html_content: str, country_code: str = "AE") -> List[Job]:
    """Parse GulfTalent HTML job listings into Job objects."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    rows = soup.find_all("tr", class_=lambda c: c and ("job-row" in c or "clickable" in c))
    if not rows:
        rows = soup.find_all("div", class_=lambda c: c and "job-item" in c)

    for row in rows:
        link_elem = row.find("a", href=lambda h: h and "/jobs/" in h)
        if not link_elem:
            continue

        title = link_elem.get_text(strip=True)
        link = link_elem["href"]
        if not link.startswith("http"):
            link = f"https://www.gulftalent.com{link}"

        company_elem = row.find(["span", "div", "a"], class_=lambda c: c and "company" in c.lower())
        company = company_elem.get_text(strip=True) if company_elem else "GulfTalent Employer"

        loc_elem = row.find(["span", "div", "td"], class_=lambda c: c and "location" in c.lower())
        location = loc_elem.get_text(strip=True) if loc_elem else country_code

        job_id = f"gulftalent-{country_code.lower()}-{re.sub(r'[^a-zA-Z0-9]', '-', link)[-30:]}"
        is_remote = "remote" in location.lower() or "remote" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="gulftalent",
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
                description=f"{title} at {company} ({location})",
                fetched_at=fetched_at,
            )
        )

    return jobs


class GulfTalentAdapter(SourceAdapter):
    """Adapter for GulfTalent Middle East executive and professional jobs."""

    @property
    def name(self) -> str:
        return "gulftalent"

    @property
    def source_type(self) -> str:
        return "regional_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, url in GULFTALENT_URLS:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_gulftalent_html(resp.text, country_code=country_code)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching GulfTalent %s: %s", country_code, exc)
                continue

        logger.info("GulfTalent adapter fetched %d jobs across GCC.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

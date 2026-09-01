"""
src/job_radar/sources/healthcare_placement.py

International Healthcare & Nurse Placement Source Adapter.
Scrapes healthcare, international nursing, and NHS overseas placement agencies
(e.g., Health Carousel, O'Grady Peyton, NHS International recruitment feeds).
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

HEALTHCARE_FEEDS = [
    ("UK", "NHS International Nursing", "https://www.healthjobsuk.com/job_list/s1/Nursing_and_midwifery?_ts=1"),
    ("US", "Health Carousel International", "https://healthcarousel.com/international-healthcare-professionals/nursing-jobs"),
    ("IE", "HSE Ireland Nursing", "https://www.hse.ie/eng/staff/jobs/job-search/nursing/"),
]


def parse_healthjobsuk_html(html_content: str, country_code: str = "UK") -> List[Job]:
    """Parse healthcare jobs from NHS and international placement portals."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cards = soup.find_all(["article", "li", "div"], class_=lambda c: c and ("job-result" in c or "vacancy" in c or "job-item" in c))

    for card in cards:
        title_elem = card.find(["a", "h2", "h3"], class_=lambda c: c and ("title" in c.lower() or "heading" in c.lower()))
        if not title_elem:
            title_elem = card.find("a", href=True)
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        if not title or len(title) < 4:
            continue

        href = title_elem.get("href", "")
        if href.startswith("/"):
            href = f"https://www.healthjobsuk.com{href}"

        company_elem = card.find(["span", "p", "div"], class_=lambda c: c and ("trust" in c.lower() or "employer" in c.lower() or "company" in c.lower()))
        company = company_elem.get_text(strip=True) if company_elem else "NHS / Healthcare Trust"

        loc_elem = card.find(["span", "p", "div"], class_=lambda c: c and ("location" in c.lower() or "place" in c.lower()))
        location = loc_elem.get_text(strip=True) if loc_elem else country_code

        desc_elem = card.find(["div", "p"], class_=lambda c: c and ("summary" in c.lower() or "description" in c.lower()))
        desc = desc_elem.get_text(strip=True) if desc_elem else f"{title} at {company} ({location}) - Healthcare & Nursing Visa Eligible"

        job_id = f"healthcare-{country_code.lower()}-{re.sub(r'[^a-zA-Z0-9]', '-', href)[-30:]}"

        jobs.append(
            Job(
                id=job_id,
                source="healthcare_placement",
                company=company,
                title=title,
                location=location,
                location_raw=location,
                locations=[location] if location else [],
                country=country_code,
                remote=False,
                is_remote=False,
                workplace_type=WorkplaceType.ONSITE.value,
                apply_url=href,
                job_url=href,
                url=href,
                description=desc,
                fetched_at=fetched_at,
            )
        )

    return jobs


class HealthcarePlacementAdapter(SourceAdapter):
    """Adapter for international healthcare and nurse placement vacancies."""

    @property
    def name(self) -> str:
        return "healthcare_placement"

    @property
    def source_type(self) -> str:
        return "vertical_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, name, url in HEALTHCARE_FEEDS:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_healthjobsuk_html(resp.text, country_code=country_code)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching %s (%s): %s", name, url, exc)
                continue

        logger.info("Healthcare placement adapter fetched %d healthcare jobs.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

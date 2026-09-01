"""
src/job_radar/sources/jobstreet.py

JobStreet / JobsDB Southeast Asia Job Source Adapter.
Scrapes jobs from JobStreet / JobsDB across Singapore, Malaysia, Philippines, and Indonesia.
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
from job_radar.models.job import Job, WorkplaceType
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (VisaLane/1.0; +https://github.com)"

JOBSTREET_COUNTRIES = {
    "SG": "https://www.jobstreet.com.sg/en/job-search/information-technology-jobs/",
    "MY": "https://www.jobstreet.com.my/en/job-search/information-technology-jobs/",
    "PH": "https://www.jobstreet.com.ph/en/job-search/information-technology-jobs/",
    "ID": "https://www.jobstreet.co.id/en/job-search/information-technology-jobs/",
}


def parse_jobstreet_html(html_content: str, country_code: str = "SG", base_url: str = "") -> List[Job]:
    """Parse HTML listing from JobStreet into Job models."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", attrs={"data-automation": re.compile(r"jobListing|jobCard", re.IGNORECASE)})

    for art in articles:
        title_tag = art.find(["a", "h1", "h2", "h3"], attrs={"data-automation": re.compile(r"jobTitle|job-link", re.IGNORECASE)})
        if not title_tag:
            title_tag = art.find("a", href=lambda h: h and "/job/" in h)
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")
        if link.startswith("/"):
            link = f"{base_url.rstrip('/')}{link}"

        company_tag = art.find(["a", "span", "p"], attrs={"data-automation": re.compile(r"jobCompany", re.IGNORECASE)})
        company = company_tag.get_text(strip=True) if company_tag else "JobStreet Employer"

        loc_tag = art.find(["a", "span", "p"], attrs={"data-automation": re.compile(r"jobLocation", re.IGNORECASE)})
        location = loc_tag.get_text(strip=True) if loc_tag else country_code

        desc_tag = art.find(["span", "div", "p"], attrs={"data-automation": re.compile(r"jobShortDescription|job-snippet", re.IGNORECASE)})
        desc = desc_tag.get_text(strip=True) if desc_tag else f"{title} at {company} ({location})"

        job_id = f"jobstreet-{country_code.lower()}-{re.sub(r'[^a-zA-Z0-9]', '-', link)[-30:]}"
        is_remote = "remote" in location.lower() or "remote" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="jobstreet",
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


class JobStreetAdapter(SourceAdapter):
    """Adapter for JobStreet & JobsDB Southeast Asia job search portals."""

    @property
    def name(self) -> str:
        return "jobstreet"

    @property
    def source_type(self) -> str:
        return "regional_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, url in JOBSTREET_COUNTRIES.items():
            try:
                base = f"https://www.jobstreet.com.{country_code.lower()}"
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_jobstreet_html(resp.text, country_code=country_code, base_url=base)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching JobStreet %s: %s", country_code, exc)
                continue

        logger.info("JobStreet adapter fetched %d jobs across Southeast Asia.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

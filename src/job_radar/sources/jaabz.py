"""
src/job_radar/sources/jaabz.py

Jaabz.com Dedicated Visa Sponsorship Tech Job Source Adapter.
Performs faceted crawls across category × country combinations:
  - https://jaabz.com/jobs/{category}/visasponsorship
  - https://jaabz.com/jobs/in/{country}/visasponsorship

CRITICAL EVIDENCE POLICY:
Any visa sponsorship claim sourced from Jaabz is classified strictly as THIRD_PARTY
evidence with a baseline LOW confidence tier. It NEVER elevates a job to VERIFIED
or HIGH confidence on its own without independent government or verified employer confirmation.
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

JAABZ_CATEGORIES = [
    "programming",
    "data-science",
    "machine-learning",
    "cyber-security",
    "devops",
    "mobile",
    "product-management",
    "cloud",
    "qa",
    "marketing",
    "design",
    "hr",
]

JAABZ_COUNTRIES = [
    ("UK", "united-kingdom"),
    ("DE", "germany"),
    ("NL", "netherlands"),
    ("CA", "canada"),
    ("IE", "ireland"),
    ("DK", "denmark"),
    ("SE", "sweden"),
    ("PL", "poland"),
    ("SG", "singapore"),
    ("AU", "australia"),
    ("US", "united-states"),
]


def parse_jaabz_html(html_content: str, default_country: str = "GLOBAL", category: str = "tech") -> List[Job]:
    """Parse Jaabz HTML job postings into Job objects with third-party visa metadata."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cards = soup.find_all("div", class_=lambda c: c and ("job-card" in c or "job-item" in c or "card" in c.lower()))
    if not cards:
        cards = soup.find_all("article")

    for card in cards:
        link_elem = card.find("a", href=lambda h: h and ("/job/" in h or "/jobs/" in h))
        if not link_elem:
            link_elem = card.find("a", href=True)
        if not link_elem or not link_elem.get("href"):
            continue

        title = link_elem.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        href = link_elem["href"]
        if not href.startswith("http"):
            href = f"https://jaabz.com{href}"

        company_elem = card.find(["span", "div", "p", "h3"], class_=lambda c: c and ("company" in c.lower() or "employer" in c.lower()))
        company = company_elem.get_text(strip=True) if company_elem else "Jaabz Tech Employer"

        loc_elem = card.find(["span", "div", "p"], class_=lambda c: c and ("location" in c.lower() or "country" in c.lower()))
        location = loc_elem.get_text(strip=True) if loc_elem else default_country

        desc_elem = card.find(["div", "p"], class_=lambda c: c and ("desc" in c.lower() or "snippet" in c.lower()))
        desc = desc_elem.get_text(strip=True) if desc_elem else f"{title} at {company} ({location}) - Visa Sponsorship Tagged (Jaabz)"

        job_id = f"jaabz-{re.sub(r'[^a-zA-Z0-9]', '-', href)[-30:]}"
        is_remote = "remote" in location.lower() or "remote" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="jaabz",
                company=company,
                title=title,
                location=location,
                location_raw=location,
                locations=[location] if location else [],
                country=default_country if len(default_country) == 2 else None,
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


class JaabzAdapter(SourceAdapter):
    """Adapter for Jaabz.com faceted visa-sponsorship job crawls."""

    @property
    def name(self) -> str:
        return "jaabz"

    @property
    def source_type(self) -> str:
        return "aggregator"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        seen_ids = set()
        max_per_source = config.max_per_source or 500

        # 1. Category Facets
        for cat in JAABZ_CATEGORIES:
            url = f"https://jaabz.com/jobs/{cat}/visasponsorship"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    batch = parse_jaabz_html(resp.text, category=cat)
                    for j in batch:
                        if j.id not in seen_ids:
                            seen_ids.add(j.id)
                            all_jobs.append(j)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching Jaabz category %s: %s", cat, exc)
                continue

        # 2. Country Facets (if capacity remains)
        if len(all_jobs) < max_per_source:
            for country_code, slug in JAABZ_COUNTRIES:
                url = f"https://jaabz.com/jobs/in/{slug}/visasponsorship"
                try:
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        batch = parse_jaabz_html(resp.text, default_country=country_code)
                        for j in batch:
                            if j.id not in seen_ids:
                                seen_ids.add(j.id)
                                all_jobs.append(j)
                        if len(all_jobs) >= max_per_source:
                            break
                except Exception as exc:
                    logger.debug("Failed fetching Jaabz country %s: %s", slug, exc)
                    continue

        logger.info("Jaabz adapter fetched %d visa-sponsorship tagged jobs.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

"""
src/job_radar/sources/bumeran.py

Bumeran Latin America Job Source Adapter.
Scrapes jobs from Bumeran across Argentina, Peru, Ecuador, and Venezuela.
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

BUMERAN_FEEDS = {
    "AR": "https://www.bumeran.com.ar/empleos-tecnologia-sistemas.html",
    "PE": "https://www.bumeran.com.pe/empleos-tecnologia-sistemas.html",
    "EC": "https://www.multitrabajos.com/empleos-tecnologia-sistemas.html",
}


def parse_bumeran_html(html_content: str, country_code: str = "AR") -> List[Job]:
    """Parse Bumeran HTML job cards into Job objects."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Look for job links/cards
    cards = soup.find_all("div", class_=lambda c: c and ("Card" in c or "Aviso" in c or "job" in c.lower()))
    if not cards:
        cards = soup.find_all("a", href=lambda h: h and "/empleos/" in h)

    for card in cards:
        link_elem = card if card.name == "a" else card.find("a", href=True)
        if not link_elem or not link_elem.get("href"):
            continue

        href = link_elem["href"]
        if not href.startswith("http"):
            href = f"https://www.bumeran.com.ar{href}"

        title = link_elem.get_text(strip=True)
        if not title or len(title) < 4:
            h2 = card.find(["h2", "h3"])
            if h2:
                title = h2.get_text(strip=True)

        if not title or len(title) < 4:
            continue

        company_elem = card.find(["h3", "span", "p"], class_=lambda c: c and ("company" in c.lower() or "empresa" in c.lower()))
        company = company_elem.get_text(strip=True) if company_elem else "Empresa Destacada"

        loc_elem = card.find(["span", "p"], class_=lambda c: c and ("location" in c.lower() or "lugar" in c.lower()))
        location = loc_elem.get_text(strip=True) if loc_elem else country_code

        job_id = f"bumeran-{country_code.lower()}-{re.sub(r'[^a-zA-Z0-9]', '-', href)[-30:]}"
        is_remote = "remoto" in location.lower() or "remoto" in title.lower()

        jobs.append(
            Job(
                id=job_id,
                source="bumeran",
                company=company,
                title=title,
                location=location,
                location_raw=location,
                locations=[location] if location else [],
                country=country_code,
                remote=is_remote,
                is_remote=is_remote,
                workplace_type=WorkplaceType.REMOTE.value if is_remote else WorkplaceType.ONSITE.value,
                apply_url=href,
                job_url=href,
                url=href,
                description=f"{title} en {company} ({location})",
                fetched_at=fetched_at,
            )
        )

    return jobs


class BumeranAdapter(SourceAdapter):
    """Adapter for Bumeran Latin America job portals."""

    @property
    def name(self) -> str:
        return "bumeran"

    @property
    def source_type(self) -> str:
        return "regional_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, url in BUMERAN_FEEDS.items():
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_bumeran_html(resp.text, country_code=country_code)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching Bumeran %s: %s", country_code, exc)
                continue

        logger.info("Bumeran adapter fetched %d jobs.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

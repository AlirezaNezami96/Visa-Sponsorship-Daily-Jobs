"""
src/job_radar/sources/computrabajo.py

Computrabajo Latin America Regional Job Source Adapter.
Scrapes jobs from Computrabajo across Colombia, Mexico, Argentina, Chile, and Peru.
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

COMPUTRABAJO_COUNTRIES = {
    "CO": "https://co.computrabajo.com/empleos-de-tecnologia-informatica-y-sistemas",
    "MX": "https://mx.computrabajo.com/empleos-de-tecnologia-informatica-y-sistemas",
    "AR": "https://ar.computrabajo.com/empleos-de-tecnologia-informatica-y-sistemas",
    "CL": "https://cl.computrabajo.com/empleos-de-tecnologia-informatica-y-sistemas",
    "PE": "https://pe.computrabajo.com/empleos-de-tecnologia-informatica-y-sistemas",
}


def parse_computrabajo_html(html_content: str, country_code: str = "CO", base_url: str = "") -> List[Job]:
    """Parse HTML listing from Computrabajo into Job objects."""
    jobs: List[Job] = []
    soup = BeautifulSoup(html_content, "html.parser")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    articles = soup.find_all("article", class_=lambda c: c and "box_offer" in c)
    if not articles:
        # Fallback to general offer containers
        articles = soup.find_all(["article", "div"], class_=lambda c: c and ("offer" in c.lower() or "bRS" in c))

    for art in articles:
        title_tag = art.find(["a", "h2"], class_=lambda c: c and ("js-o-link" in c or "title" in c.lower()))
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")
        if link.startswith("/"):
            link = f"{base_url.rstrip('/')}{link}"

        # Company
        company_tag = art.find(["p", "a", "span"], class_=lambda c: c and ("it-blank" in c or "company" in c.lower()))
        company = company_tag.get_text(strip=True) if company_tag else "Confidencial / Empresa Líder"

        # Location
        loc_tag = art.find(["p", "span"], class_=lambda c: c and ("loc" in c.lower() or "city" in c.lower()))
        location = loc_tag.get_text(strip=True) if loc_tag else country_code

        # Snippet/Description
        desc_tag = art.find(["p", "div"], class_=lambda c: c and ("desc" in c.lower() or "body" in c.lower()))
        desc = desc_tag.get_text(strip=True) if desc_tag else f"{title} en {company} ({location})"

        # ID
        offer_id = art.get("data-id") or re.sub(r"[^a-zA-Z0-9]", "-", link).strip("-")[-30:]
        job_id = f"computrabajo-{country_code.lower()}-{offer_id}"

        is_remote = "remoto" in location.lower() or "remoto" in title.lower() or "teletrabajo" in desc.lower()

        jobs.append(
            Job(
                id=job_id,
                source="computrabajo",
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


class ComputrabajoAdapter(SourceAdapter):
    """Adapter for Computrabajo Latin America regional job boards."""

    @property
    def name(self) -> str:
        return "computrabajo"

    @property
    def source_type(self) -> str:
        return "regional_board"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        all_jobs: List[Job] = []
        max_per_source = config.max_per_source or 500

        for country_code, url in COMPUTRABAJO_COUNTRIES.items():
            try:
                base = f"https://{country_code.lower()}.computrabajo.com"
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_computrabajo_html(resp.text, country_code=country_code, base_url=base)
                    all_jobs.extend(batch)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching Computrabajo %s: %s", country_code, exc)
                continue

        logger.info("Computrabajo adapter fetched %d jobs across %d LatAm countries.", len(all_jobs), len(COMPUTRABAJO_COUNTRIES))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

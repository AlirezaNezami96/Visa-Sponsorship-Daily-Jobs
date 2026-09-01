"""
src/job_radar/sources/weworkremotely.py

We Work Remotely (WWR) Source Adapter.
Fetches high-quality global remote tech and non-tech jobs from We Work Remotely's
official category RSS and JSON feeds.
"""
from __future__ import annotations

import datetime
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job, WorkplaceType
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (VisaLane/1.0; +https://github.com)"

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
    "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
]


def parse_wwr_rss(xml_content: str, max_jobs: int = 500) -> List[Job]:
    """Parse We Work Remotely RSS XML stream into Job models."""
    jobs: List[Job] = []
    try:
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pub_date_elem = item.find("pubDate")
            guid_elem = item.find("guid")

            raw_title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            job_url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            raw_desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ""
            guid = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else job_url

            if not raw_title:
                continue

            # WWR titles are often formatted as "Company Name: Job Title"
            company = "We Work Remotely Company"
            title = raw_title
            if ":" in raw_title:
                parts = raw_title.split(":", 1)
                company = parts[0].strip()
                title = parts[1].strip()

            # Clean HTML description
            clean_desc = ""
            if raw_desc:
                soup = BeautifulSoup(raw_desc, "html.parser")
                clean_desc = soup.get_text(separator=" ", strip=True)

            job_id = f"wwr-{re.sub(r'[^a-zA-Z0-9]', '-', guid).strip('-')}"

            jobs.append(
                Job(
                    id=job_id,
                    source="weworkremotely",
                    company=company,
                    title=title,
                    location="Remote / Worldwide",
                    location_raw="Remote",
                    locations=["Remote"],
                    remote=True,
                    is_remote=True,
                    workplace_type=WorkplaceType.REMOTE.value,
                    apply_url=job_url,
                    job_url=job_url,
                    url=job_url,
                    date_posted=pub_date,
                    description=clean_desc or f"{title} at {company}",
                    fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                )
            )
            if len(jobs) >= max_jobs:
                break
    except Exception as e:
        logger.debug("Error parsing WWR RSS feed: %s", e)

    return jobs


class WeWorkRemotelyAdapter(SourceAdapter):
    """Adapter for We Work Remotely (WWR) RSS and category feeds."""

    @property
    def name(self) -> str:
        return "weworkremotely"

    @property
    def source_type(self) -> str:
        return "aggregator"

    def supports_company_urls(self) -> bool:
        return False

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"}
        all_jobs: List[Job] = []
        seen_ids = set()
        max_per_source = config.max_per_source or 500

        for feed_url in WWR_FEEDS:
            try:
                resp = requests.get(feed_url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    batch = parse_wwr_rss(resp.text, max_jobs=max_per_source)
                    for j in batch:
                        if j.id not in seen_ids:
                            seen_ids.add(j.id)
                            all_jobs.append(j)
                    if len(all_jobs) >= max_per_source:
                        break
            except Exception as exc:
                logger.debug("Failed fetching WWR feed %s: %s", feed_url, exc)
                continue

        logger.info("WeWorkRemotely adapter fetched %d jobs.", len(all_jobs))
        return all_jobs[:max_per_source]

    async def fetch_by_company(self, company_url: str, config: JobSearchConfig) -> List[Job]:
        return []

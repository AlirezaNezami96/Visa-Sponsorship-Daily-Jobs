"""
src/job_radar/sources/config_adapter.py

Configuration-Driven Universal Source Adapter Framework.
Enables instant onboarding of new job sources via JSON/YAML declarations without writing custom code.
Supports 7 extraction strategies:
  1. OFFICIAL_API
  2. PUBLIC_JSON
  3. ATS_ENDPOINT
  4. RSS_XML
  5. SITEMAP
  6. JSON_LD
  7. HTML_FALLBACK
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


class ExtractionStrategy(str, Enum):
    OFFICIAL_API = "official_api"
    PUBLIC_JSON = "public_json"
    ATS_ENDPOINT = "ats_endpoint"
    RSS_XML = "rss_xml"
    SITEMAP = "sitemap"
    JSON_LD = "json_ld"
    HTML_FALLBACK = "html_fallback"


@dataclass
class SourceConfig:
    """Declarative specification for a job board or employer source."""
    name: str
    domain: str
    strategy: ExtractionStrategy
    start_urls: List[str]
    country: str = "Worldwide"
    category: str = "commercial_board"
    tier: str = "tier2_board"
    enabled: bool = True
    rate_limit_delay_secs: float = 0.5
    headers: Dict[str, str] = field(default_factory=dict)
    json_jobs_path: Optional[str] = None  # JSONPath or key (e.g., 'data.jobs' or 'results')
    field_mappings: Dict[str, str] = field(default_factory=dict)  # standard_field -> source_field
    html_selectors: Dict[str, str] = field(default_factory=dict)  # card, title, company, location, link, date


class UniversalConfigAdapter(SourceAdapter):
    """Executes scraping for any source defined by a SourceConfig."""

    def __init__(self, source_config: SourceConfig) -> None:
        self.cfg = source_config

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def source_type(self) -> str:
        return self.cfg.category

    def supports_company_urls(self) -> bool:
        return self.cfg.strategy in (ExtractionStrategy.ATS_ENDPOINT, ExtractionStrategy.JSON_LD, ExtractionStrategy.HTML_FALLBACK)

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        if not self.cfg.enabled or not self.cfg.start_urls:
            return []

        jobs: List[Job] = []
        for url in self.cfg.start_urls:
            try:
                extracted = await asyncio.to_thread(self._fetch_url_sync, url)
                jobs.extend(extracted)
                if len(jobs) >= config.max_per_source:
                    return jobs[:config.max_per_source]
            except Exception as e:
                logger.debug("Source '%s' fetch failed for %s: %s", self.cfg.name, url, e)

        return jobs

    def _fetch_url_sync(self, url: str) -> List[Job]:
        headers = {"User-Agent": USER_AGENT, **self.cfg.headers}
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []

        if self.cfg.strategy in (ExtractionStrategy.PUBLIC_JSON, ExtractionStrategy.OFFICIAL_API):
            return self._extract_json(resp.json(), url)
        elif self.cfg.strategy == ExtractionStrategy.RSS_XML:
            return self._extract_rss(resp.text, url)
        elif self.cfg.strategy == ExtractionStrategy.JSON_LD:
            return self._extract_json_ld(resp.text, url)
        else:
            return self._extract_html(resp.text, url)

    def _extract_json(self, data: Any, source_url: str) -> List[Job]:
        items: List[Dict[str, Any]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if self.cfg.json_jobs_path:
                curr = data
                for k in self.cfg.json_jobs_path.split("."):
                    if isinstance(curr, dict):
                        curr = curr.get(k, [])
                items = curr if isinstance(curr, list) else []
            else:
                for k in ("jobs", "data", "results", "positions", "offers", "postings"):
                    if k in data and isinstance(data[k], list):
                        items = data[k]
                        break

        jobs = []
        mappings = self.cfg.field_mappings or {
            "title": "title", "company": "company", "location": "location",
            "url": "url", "description": "description", "date_posted": "date_posted",
        }

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            title = str(item.get(mappings.get("title", "title")) or item.get("position") or "").strip()
            if not title:
                continue

            company = str(item.get(mappings.get("company", "company")) or item.get("company_name") or self.cfg.name).strip()
            loc = str(item.get(mappings.get("location", "location")) or self.cfg.country).strip()
            apply_url = str(item.get(mappings.get("url", "url")) or item.get("apply_url") or source_url).strip()
            desc = str(item.get(mappings.get("description", "description")) or item.get("snippet") or "")

            jobs.append(
                Job(
                    id=f"{self.cfg.name}-{idx}-{abs(hash(apply_url or title))}",
                    source=self.cfg.name,
                    country=self.cfg.country,
                    company=company,
                    title=title,
                    location=loc,
                    remote="remote" in loc.lower() or "remote" in title.lower(),
                    apply_url=apply_url,
                    job_url=apply_url,
                    description=desc or f"{title} at {company}",
                    metadata={"source_category": self.cfg.category, "country": self.cfg.country},
                )
            )
        return jobs

    def _extract_rss(self, xml_text: str, source_url: str) -> List[Job]:
        soup = BeautifulSoup(xml_text, "xml")
        items = soup.find_all("item") or soup.find_all("entry")
        jobs = []

        for idx, item in enumerate(items):
            title_tag = item.find("title")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link_tag = item.find("link")
            link = link_tag.get_text(strip=True) if link_tag else source_url
            if not link and link_tag and link_tag.get("href"):
                link = link_tag["href"]

            desc_tag = item.find("description") or item.find("summary") or item.find("content")
            desc = desc_tag.get_text(separator=" ", strip=True) if desc_tag else ""
            pub_tag = item.find("pubDate") or item.find("published") or item.find("updated")
            pub_date = pub_tag.get_text(strip=True) if pub_tag else None

            jobs.append(
                Job(
                    id=f"{self.cfg.name}-rss-{idx}-{abs(hash(link or title))}",
                    source=self.cfg.name,
                    country=self.cfg.country,
                    company=self.cfg.name.replace("_", " ").title(),
                    title=title,
                    location=self.cfg.country,
                    remote="remote" in title.lower() or "remote" in desc.lower(),
                    apply_url=link,
                    job_url=link,
                    date_posted=pub_date,
                    description=desc[:1500] or f"{title} ({self.cfg.country})",
                    metadata={"source_category": self.cfg.category, "country": self.cfg.country},
                )
            )
        return jobs

    def _extract_json_ld(self, html_text: str, source_url: str) -> List[Job]:
        soup = BeautifulSoup(html_text, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        jobs = []

        for idx, s in enumerate(scripts):
            try:
                data = json.loads(s.get_text(strip=True))
                if isinstance(data, list):
                    candidates = data
                else:
                    candidates = [data]

                for item in candidates:
                    if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                        continue

                    title = item.get("title", "").strip()
                    if not title:
                        continue

                    hiring_org = item.get("hiringOrganization", {})
                    company = hiring_org.get("name", self.cfg.name) if isinstance(hiring_org, dict) else str(hiring_org)

                    job_loc = item.get("jobLocation", {})
                    address = job_loc.get("address", {}) if isinstance(job_loc, dict) else {}
                    city = address.get("addressLocality", "") if isinstance(address, dict) else ""
                    country = address.get("addressCountry", self.cfg.country) if isinstance(address, dict) else self.cfg.country
                    location = f"{city}, {country}".strip(", ") or self.cfg.country

                    url = item.get("url") or source_url
                    desc = item.get("description", "")
                    date_posted = item.get("datePosted")

                    jobs.append(
                        Job(
                            id=f"{self.cfg.name}-jsonld-{idx}-{abs(hash(url or title))}",
                            source=self.cfg.name,
                            country=self.cfg.country,
                            company=company,
                            title=title,
                            location=location,
                            remote="TELECOMMUTE" in str(item.get("jobLocationType", "")).upper(),
                            apply_url=url,
                            job_url=url,
                            date_posted=date_posted,
                            description=desc[:2000],
                            metadata={"source_category": self.cfg.category, "country": self.cfg.country},
                        )
                    )
            except Exception:
                continue

        return jobs

    def _extract_html(self, html_text: str, source_url: str) -> List[Job]:
        soup = BeautifulSoup(html_text, "html.parser")
        selectors = self.cfg.html_selectors or {
            "card": "article, .job-item, .job-card, .listing-item, li.job",
            "title": "h2, h3, a.title, .job-title",
            "company": ".company, .employer, .company-name",
            "location": ".location, .city, .region",
            "link": "a",
        }

        cards = soup.select(selectors.get("card", "article"))
        jobs = []

        for idx, card in enumerate(cards[:50]):
            title_tag = card.select_one(selectors.get("title", "h2, h3, a"))
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            link_tag = card.select_one(selectors.get("link", "a[href]")) or (title_tag if title_tag.name == "a" else None)
            link = link_tag["href"] if link_tag and link_tag.get("href") else source_url
            if link and not link.startswith("http"):
                link = urllib.parse.urljoin(source_url, link)

            comp_tag = card.select_one(selectors.get("company", ".company"))
            company = comp_tag.get_text(strip=True) if comp_tag else self.cfg.name.replace("_", " ").title()

            loc_tag = card.select_one(selectors.get("location", ".location"))
            location = loc_tag.get_text(strip=True) if loc_tag else self.cfg.country

            jobs.append(
                Job(
                    id=f"{self.cfg.name}-html-{idx}-{abs(hash(link or title))}",
                    source=self.cfg.name,
                    country=self.cfg.country,
                    company=company,
                    title=title,
                    location=location,
                    remote="remote" in location.lower() or "remote" in title.lower(),
                    apply_url=link,
                    job_url=link,
                    description=f"{title} at {company} ({location})",
                    metadata={"source_category": self.cfg.category, "country": self.cfg.country},
                )
            )

        return jobs

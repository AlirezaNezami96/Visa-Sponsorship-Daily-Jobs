"""API Fetchers for standard Applicant Tracking Systems (ATS).

Supports: Greenhouse, Lever, Ashby, SmartRecruiters, Personio, Workable.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0
DEFAULT_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

_thread_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(
            total=0,
            connect=0,
            read=0,
            status=0,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _thread_local.session = s
    return s


def _extract_text_snippet(raw_html: str, max_chars: int = 300) -> str:
    if not raw_html:
        return ""
    try:
        return BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)[:max_chars]
    except Exception:
        return raw_html[:max_chars]


def fetch_greenhouse(slug: str) -> List[dict]:
    """Fetch jobs from Greenhouse board API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for j in data.get("jobs", []):
            loc = j.get("location", {}).get("name", "")
            dept = ", ".join(d.get("name", "") for d in j.get("departments", []))
            jobs.append({
                "title": j.get("title", ""),
                "url": j.get("absolute_url", ""),
                "location": loc,
                "department": dept,
                "date_posted": j.get("updated_at"),
                "source": "Greenhouse",
            })
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Greenhouse for %s: %s", slug, exc)
        return []


def fetch_lever(slug: str) -> List[dict]:
    """Fetch jobs from Lever postings API."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for j in data:
            loc = j.get("categories", {}).get("location", "")
            team = j.get("categories", {}).get("team", "")
            desc = j.get("descriptionPlain", "") or _extract_text_snippet(j.get("description", ""))
            jobs.append({
                "title": j.get("text", ""),
                "url": j.get("hostedUrl", ""),
                "location": loc,
                "department": team,
                "date_posted": str(j.get("createdAt")),
                "snippet": desc[:300],
                "source": "Lever",
            })
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Lever for %s: %s", slug, exc)
        return []


def fetch_ashby(slug: str) -> List[dict]:
    """Fetch jobs from Ashby posting API."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = _session().post(url, json={}, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for j in data.get("jobPostings", []):
            if not j.get("isListed", True):
                continue
            loc = j.get("locationName", "")
            dept = j.get("departmentName", "")
            desc = j.get("descriptionPlain", "") or _extract_text_snippet(j.get("descriptionHtml", ""))
            jobs.append({
                "title": j.get("title", ""),
                "url": j.get("jobUrl", ""),
                "location": loc,
                "department": dept,
                "date_posted": j.get("publishedAt"),
                "snippet": desc[:300],
                "source": "Ashby",
            })
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Ashby for %s: %s", slug, exc)
        return []


def fetch_smartrecruiters(slug: str) -> List[dict]:
    """Fetch jobs from SmartRecruiters postings API."""
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    jobs = []
    offset = 0
    limit = 100
    try:
        while True:
            r = _session().get(f"{url}?offset={offset}&limit={limit}", timeout=DEFAULT_TIMEOUT)
            if r.status_code != 200:
                break
            data = r.json()
            content = data.get("content", [])
            if not content:
                break
            for j in content:
                city = j.get("location", {}).get("city", "")
                country = j.get("location", {}).get("country", "")
                loc = f"{city}, {country}".strip(", ")
                dept = j.get("department", {}).get("label", "")
                jobs.append({
                    "title": j.get("name", ""),
                    "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id', '')}",
                    "location": loc,
                    "department": dept,
                    "date_posted": j.get("releasedDate"),
                    "source": "SmartRecruiters",
                })
            offset += limit
            if offset >= data.get("totalFound", 0) or offset >= 500:
                break
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching SmartRecruiters for %s: %s", slug, exc)
        return jobs


def fetch_personio(slug: str) -> List[dict]:
    """Fetch jobs from Personio XML feed."""
    import xml.etree.ElementTree as ET

    url = f"https://{slug}.jobs.personio.de/xml"
    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        jobs = []
        root = ET.fromstring(r.content)
        for pos in root.findall(".//position"):
            title = pos.findtext("name", "")
            job_id = pos.findtext("id", "")
            loc = pos.findtext("office", "")
            dept = pos.findtext("department", "")
            jobs.append({
                "title": title,
                "url": f"https://{slug}.jobs.personio.de/job/{job_id}",
                "location": loc,
                "department": dept,
                "source": "Personio",
            })
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Personio for %s: %s", slug, exc)
        return []


def fetch_workable(slug: str) -> List[dict]:
    """Fetch jobs from Workable widget API."""
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    try:
        r = _session().post(url, json={}, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for j in data.get("results", []):
            city = j.get("city", "")
            country = j.get("country", "")
            loc = f"{city}, {country}".strip(", ")
            if j.get("telecommuting"):
                loc = f"Remote ({loc})" if loc else "Remote"
            dept = j.get("department", "")
            jobs.append({
                "title": j.get("title", ""),
                "url": f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}/",
                "location": loc,
                "department": dept,
                "source": "Workable",
            })
        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Workable for %s: %s", slug, exc)
        return []


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "personio": fetch_personio,
    "workable": fetch_workable,
}


def fetch_ats_jobs(ats_name: str, slug: str) -> List[dict]:
    """Dispatch fetcher for a given ATS name and slug."""
    fn = ATS_FETCHERS.get(ats_name.lower())
    if not fn:
        raise ValueError(f"Unsupported ATS: {ats_name}")
    return fn(slug)

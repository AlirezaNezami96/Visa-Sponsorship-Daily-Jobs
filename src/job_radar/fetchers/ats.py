"""API Fetchers for standard Applicant Tracking Systems (ATS).

Supports: Greenhouse, Lever, Ashby, SmartRecruiters, Personio, Workable.
Provides production enrichment: full HTML content, structured compensation,
remote/workplace detection, and per-ATS circuit breaker protection.
"""
from __future__ import annotations

import datetime
import logging
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from job_radar.fetchers.circuit_breaker import ATSCircuitBreaker
from job_radar.models import Job, WorkplaceType

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
CONNECT_TIMEOUT = 3.5
READ_TIMEOUT = 10.0
DEFAULT_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

_thread_local = threading.local()
global_circuit_breaker = ATSCircuitBreaker(failure_threshold=0.30, min_attempts=5)


def _session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        # Handle 429 and 5xx retries with backoff
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=0.5,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _thread_local.session = s
    return s


def _extract_text_from_html(raw_html: str, max_chars: Optional[int] = None) -> str:
    if not raw_html:
        return ""
    try:
        text = BeautifulSoup(raw_html, "html.parser").get_text(separator="\n", strip=True)
        if max_chars and len(text) > max_chars:
            return text[:max_chars]
        return text
    except Exception:
        return raw_html[:max_chars] if max_chars else raw_html


def _parse_workplace_type(location_text: str, title_text: str = "") -> Tuple[Optional[bool], Optional[bool], str]:
    """Detects is_remote, is_hybrid, and workplace_type string from text."""
    combined = f"{location_text} {title_text}".lower()
    if "hybrid" in combined:
        return False, True, WorkplaceType.HYBRID.value
    if any(k in combined for k in ("remote", "anywhere", "worldwide", "work from home", "virtual", "telecommute")):
        return True, False, WorkplaceType.REMOTE.value
    if any(k in combined for k in ("onsite", "in-office", "in office", "office")):
        return False, False, WorkplaceType.ONSITE.value
    return None, None, WorkplaceType.UNSPECIFIED.value


def _is_stale(date_str: Optional[str], days_back: Optional[int]) -> bool:
    """Check if date string is older than days_back. Returns False if date is missing (fail-open)."""
    if not date_str or not days_back or days_back <= 0:
        return False
    try:
        # Support epoch timestamps
        if isinstance(date_str, (int, float)) or date_str.isdigit():
            epoch = float(date_str)
            if epoch > 1e11:  # Milliseconds
                epoch /= 1000
            posted = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
        else:
            # ISO timestamp
            posted = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - posted).days > days_back
    except Exception:
        return False


# ── Greenhouse Fetcher ────────────────────────────────────────────────────────

def fetch_greenhouse(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """
    Fetch jobs from Greenhouse boards API with full content.
    Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    """
    if global_circuit_breaker.is_tripped("greenhouse"):
        logger.debug("Greenhouse circuit tripped; skipping %s", slug)
        return []

    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []

    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            if r.status_code in (404, 410):
                # Permanent non-existent slug, not a platform failure
                pass
            else:
                global_circuit_breaker.record_failure("greenhouse")
            return []

        global_circuit_breaker.record_success("greenhouse")
        data = r.json()
        raw_jobs = data.get("jobs", [])

        for j in raw_jobs:
            updated_at = j.get("updated_at")
            if _is_stale(updated_at, days_back):
                continue

            loc_name = j.get("location", {}).get("name", "")
            departments = [d.get("name", "") for d in j.get("departments", []) if d.get("name")]
            dept_name = ", ".join(departments) if departments else None
            html_content = j.get("content", "")
            plain_text = _extract_text_from_html(html_content) if html_content else None
            snippet = plain_text[:300] if plain_text else None
            title = j.get("title", "").strip()

            is_remote, is_hybrid, workplace = _parse_workplace_type(loc_name, title)
            job_id = f"gh-{j.get('id', '')}" if j.get("id") else f"gh-{slug}-{hash(j.get('absolute_url', ''))}"

            job = Job(
                id=job_id,
                source="greenhouse",
                company=slug.capitalize(),
                title=title,
                url=j.get("absolute_url", ""),
                apply_url=j.get("absolute_url"),
                location_raw=loc_name,
                locations=[loc_name] if loc_name else [],
                is_remote=is_remote,
                is_hybrid=is_hybrid,
                workplace_type=workplace,
                description_html=html_content or None,
                description_text=plain_text,
                snippet=snippet,
                department=dept_name,
                date_posted=updated_at,
                fetched_at=fetched_at,
            )
            jobs.append(job)

        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Greenhouse for %s: %s", slug, exc)
        global_circuit_breaker.record_failure("greenhouse", exc)
        return []


# ── Lever Fetcher ────────────────────────────────────────────────────────────

def fetch_lever(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """
    Fetch jobs from Lever postings API with EU fallback and structured compensation.
    Endpoint: GET https://api.lever.co/v0/postings/{slug}?mode=json
    Fallback: GET https://api.eu.lever.co/v0/postings/{slug}?mode=json
    """
    if global_circuit_breaker.is_tripped("lever"):
        logger.debug("Lever circuit tripped; skipping %s", slug)
        return []

    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []

    urls = [
        f"https://api.lever.co/v0/postings/{slug}?mode=json",
        f"https://api.eu.lever.co/v0/postings/{slug}?mode=json",
    ]

    response_data = None
    success_url = None

    for url in urls:
        try:
            r = _session().get(url, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                response_data = r.json()
                success_url = url
                break
        except Exception:
            continue

    if response_data is None or not isinstance(response_data, list):
        global_circuit_breaker.record_failure("lever")
        return []

    global_circuit_breaker.record_success("lever")

    for j in response_data:
        created_at = j.get("createdAt")
        created_str = str(created_at) if created_at else None
        if _is_stale(created_str, days_back):
            continue

        categories = j.get("categories", {})
        loc = categories.get("location", "")
        team = categories.get("team", "") or categories.get("department", "")
        workplace_str = j.get("workplaceType", "").lower()
        title = j.get("text", "").strip()

        is_remote, is_hybrid, workplace = _parse_workplace_type(f"{loc} {workplace_str}", title)
        if workplace_str in ("remote", "hybrid", "onsite"):
            workplace = workplace_str

        # Plain & HTML descriptions
        desc_plain = j.get("descriptionPlain", "")
        desc_html = j.get("description", "")
        if not desc_plain and desc_html:
            desc_plain = _extract_text_from_html(desc_html)
        snippet = desc_plain[:300] if desc_plain else None

        # Structured Salary Range
        salary_min = None
        salary_max = None
        salary_curr = None
        salary_interval = None
        salary_raw = None

        salary_range = j.get("salaryRange")
        if isinstance(salary_range, dict):
            salary_min = salary_range.get("min")
            salary_max = salary_range.get("max")
            salary_curr = salary_range.get("currency")
            salary_interval = salary_range.get("interval")
            if salary_min and salary_max:
                salary_raw = f"{salary_curr or '$'}{salary_min:,.0f} - {salary_max:,.0f} / {salary_interval or 'year'}"

        job_id = f"lever-{j.get('id', '')}" if j.get("id") else f"lever-{slug}-{hash(j.get('hostedUrl', ''))}"

        job = Job(
            id=job_id,
            source="lever",
            company=slug.capitalize(),
            title=title,
            url=j.get("hostedUrl", ""),
            apply_url=j.get("applyUrl") or j.get("hostedUrl"),
            location_raw=loc,
            locations=[loc] if loc else [],
            is_remote=is_remote,
            is_hybrid=is_hybrid,
            workplace_type=workplace,
            description_html=desc_html or None,
            description_text=desc_plain or None,
            snippet=snippet,
            department=team or None,
            team=team or None,
            date_posted=created_str,
            fetched_at=fetched_at,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_curr,
            salary_interval=salary_interval,
            salary_raw=salary_raw,
        )
        jobs.append(job)

    return jobs


# ── Ashby Fetcher ────────────────────────────────────────────────────────────

def fetch_ashby(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """
    Fetch jobs from Ashby posting API with compensation and location requirements.
    Endpoint: POST https://api.ashbyhq.com/posting-api/job-board/{slug}
    """
    if global_circuit_breaker.is_tripped("ashby"):
        logger.debug("Ashby circuit tripped; skipping %s", slug)
        return []

    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []

    try:
        r = _session().post(url, json={"includeCompensation": True}, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            if r.status_code in (404, 410):
                pass
            else:
                global_circuit_breaker.record_failure("ashby")
            return []

        global_circuit_breaker.record_success("ashby")
        data = r.json()
        raw_postings = data.get("jobPostings", [])

        for j in raw_postings:
            # Skip unlisted postings
            if not j.get("isListed", True):
                continue

            published_at = j.get("publishedAt")
            if _is_stale(published_at, days_back):
                continue

            title = j.get("title", "").strip()
            loc_name = j.get("locationName", "")
            dept_name = j.get("departmentName", "")
            desc_html = j.get("descriptionHtml", "")
            desc_plain = j.get("descriptionPlain", "") or (_extract_text_from_html(desc_html) if desc_html else "")
            snippet = desc_plain[:300] if desc_plain else None

            is_remote, is_hybrid, workplace = _parse_workplace_type(loc_name, title)
            if j.get("isRemote"):
                is_remote = True
                workplace = WorkplaceType.REMOTE.value

            # Structured Compensation
            salary_min = None
            salary_max = None
            salary_curr = None
            salary_interval = None
            salary_raw = None

            comp = j.get("compensation") or {}
            if isinstance(comp, dict):
                salary_curr = comp.get("currency")
                salary_interval = comp.get("interval")
                ranges = comp.get("compensationRanges") or []
                if ranges and isinstance(ranges, list) and isinstance(ranges[0], dict):
                    salary_min = ranges[0].get("min")
                    salary_max = ranges[0].get("max")
                if salary_min and salary_max:
                    salary_raw = f"{salary_curr or '$'}{salary_min:,.0f} - {salary_max:,.0f} / {salary_interval or 'year'}"

            # Location Requirements
            loc_reqs: List[str] = []
            req_data = j.get("locationRequirements") or []
            if isinstance(req_data, list):
                for req in req_data:
                    if isinstance(req, str):
                        loc_reqs.append(req)
                    elif isinstance(req, dict) and req.get("country"):
                        loc_reqs.append(req["country"])

            job_id = f"ashby-{j.get('id', '')}" if j.get("id") else f"ashby-{slug}-{hash(j.get('jobUrl', ''))}"

            job = Job(
                id=job_id,
                source="ashby",
                company=slug.capitalize(),
                title=title,
                url=j.get("jobUrl", ""),
                apply_url=j.get("applyUrl") or j.get("jobUrl"),
                location_raw=loc_name,
                locations=[loc_name] if loc_name else [],
                is_remote=is_remote,
                is_hybrid=is_hybrid,
                workplace_type=workplace,
                location_requirements=loc_reqs or None,
                description_html=desc_html or None,
                description_text=desc_plain or None,
                snippet=snippet,
                department=dept_name or None,
                date_posted=published_at,
                fetched_at=fetched_at,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=salary_curr,
                salary_interval=salary_interval,
                salary_raw=salary_raw,
            )
            jobs.append(job)

        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Ashby for %s: %s", slug, exc)
        global_circuit_breaker.record_failure("ashby", exc)
        return []


# ── SmartRecruiters Fetcher ──────────────────────────────────────────────────

def fetch_smartrecruiters(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """
    Fetch jobs from SmartRecruiters postings API with pagination and date filter.
    Endpoint: GET https://api.smartrecruiters.com/v1/companies/{slug}/postings
    """
    if global_circuit_breaker.is_tripped("smartrecruiters"):
        logger.debug("SmartRecruiters circuit tripped; skipping %s", slug)
        return []

    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []
    offset = 0
    limit = 100

    try:
        while True:
            r = _session().get(f"{url}?offset={offset}&limit={limit}", timeout=DEFAULT_TIMEOUT)
            if r.status_code != 200:
                if offset == 0 and r.status_code not in (404, 410):
                    global_circuit_breaker.record_failure("smartrecruiters")
                break

            global_circuit_breaker.record_success("smartrecruiters")
            data = r.json()
            content = data.get("content", [])
            if not content:
                break

            for j in content:
                released_date = j.get("releasedDate")
                if _is_stale(released_date, days_back):
                    continue

                city = j.get("location", {}).get("city", "")
                country = j.get("location", {}).get("country", "")
                loc = f"{city}, {country}".strip(", ")
                dept = j.get("department", {}).get("label", "")
                title = j.get("name", "").strip()

                is_remote, is_hybrid, workplace = _parse_workplace_type(loc, title)
                if j.get("location", {}).get("remote"):
                    is_remote = True
                    workplace = WorkplaceType.REMOTE.value

                job_id = f"sr-{j.get('id', '')}"
                job_url = f"https://jobs.smartrecruiters.com/{slug}/{j.get('id', '')}"

                job = Job(
                    id=job_id,
                    source="smartrecruiters",
                    company=slug.capitalize(),
                    title=title,
                    url=job_url,
                    apply_url=job_url,
                    location_raw=loc,
                    locations=[loc] if loc else [],
                    is_remote=is_remote,
                    is_hybrid=is_hybrid,
                    workplace_type=workplace,
                    country=country or None,
                    department=dept or None,
                    date_posted=released_date,
                    fetched_at=fetched_at,
                )
                jobs.append(job)

            offset += limit
            if offset >= data.get("totalFound", 0) or offset >= 500:
                break

        return jobs
    except Exception as exc:
        logger.debug("Failed fetching SmartRecruiters for %s: %s", slug, exc)
        global_circuit_breaker.record_failure("smartrecruiters", exc)
        return jobs


# ── Personio Fetcher ─────────────────────────────────────────────────────────

def fetch_personio(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """Fetch jobs from Personio XML feed."""
    if global_circuit_breaker.is_tripped("personio"):
        logger.debug("Personio circuit tripped; skipping %s", slug)
        return []

    import xml.etree.ElementTree as ET

    url = f"https://{slug}.jobs.personio.de/xml"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []

    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            if r.status_code not in (404, 410):
                global_circuit_breaker.record_failure("personio")
            return []

        global_circuit_breaker.record_success("personio")
        root = ET.fromstring(r.content)

        for pos in root.findall(".//position"):
            title = (pos.findtext("name") or "").strip()
            job_id_raw = pos.findtext("id", "")
            loc = pos.findtext("office", "")
            dept = pos.findtext("department", "")
            job_type = pos.findtext("employmentType", "")
            created_at = pos.findtext("createdAt", "")

            if _is_stale(created_at, days_back):
                continue

            is_remote, is_hybrid, workplace = _parse_workplace_type(loc, title)
            job_url = f"https://{slug}.jobs.personio.de/job/{job_id_raw}"

            job = Job(
                id=f"personio-{job_id_raw}" if job_id_raw else f"personio-{slug}-{hash(title)}",
                source="personio",
                company=slug.capitalize(),
                title=title,
                url=job_url,
                apply_url=job_url,
                location_raw=loc,
                locations=[loc] if loc else [],
                is_remote=is_remote,
                is_hybrid=is_hybrid,
                workplace_type=workplace,
                department=dept or None,
                job_type=job_type or None,
                date_posted=created_at or None,
                fetched_at=fetched_at,
            )
            jobs.append(job)

        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Personio for %s: %s", slug, exc)
        global_circuit_breaker.record_failure("personio", exc)
        return []


# ── Workable Fetcher ─────────────────────────────────────────────────────────

def fetch_workable(slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """Fetch jobs from Workable widget API."""
    if global_circuit_breaker.is_tripped("workable"):
        logger.debug("Workable circuit tripped; skipping %s", slug)
        return []

    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs: List[Job] = []

    try:
        r = _session().post(url, json={}, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            if r.status_code not in (404, 410):
                global_circuit_breaker.record_failure("workable")
            return []

        global_circuit_breaker.record_success("workable")
        data = r.json()
        raw_results = data.get("results", [])

        for j in raw_results:
            published_on = j.get("published_on") or j.get("published")
            if _is_stale(published_on, days_back):
                continue

            city = j.get("city", "")
            country = j.get("country", "")
            loc = f"{city}, {country}".strip(", ")
            is_telecommuting = bool(j.get("telecommuting"))
            title = j.get("title", "").strip()

            is_remote, is_hybrid, workplace = _parse_workplace_type(loc, title)
            if is_telecommuting:
                is_remote = True
                workplace = WorkplaceType.REMOTE.value
                loc = f"Remote ({loc})" if loc else "Remote"

            shortcode = j.get("shortcode", "")
            job_url = f"https://apply.workable.com/{slug}/j/{shortcode}/"

            job = Job(
                id=f"workable-{shortcode}" if shortcode else f"workable-{slug}-{hash(title)}",
                source="workable",
                company=slug.capitalize(),
                title=title,
                url=job_url,
                apply_url=job_url,
                location_raw=loc,
                locations=[loc] if loc else [],
                is_remote=is_remote,
                is_hybrid=is_hybrid,
                workplace_type=workplace,
                country=country or None,
                department=j.get("department") or None,
                date_posted=published_on,
                fetched_at=fetched_at,
            )
            jobs.append(job)

        return jobs
    except Exception as exc:
        logger.debug("Failed fetching Workable for %s: %s", slug, exc)
        global_circuit_breaker.record_failure("workable", exc)
        return []


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "personio": fetch_personio,
    "workable": fetch_workable,
}


def fetch_ats_jobs(ats_name: str, slug: str, days_back: Optional[int] = 30) -> List[Job]:
    """Dispatch fetcher for a given ATS name and slug."""
    fn = ATS_FETCHERS.get(ats_name.lower())
    if not fn:
        raise ValueError(f"Unsupported ATS: {ats_name}")
    return fn(slug, days_back=days_back)

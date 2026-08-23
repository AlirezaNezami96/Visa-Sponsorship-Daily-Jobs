"""Shared concurrent acquisition layer for company job boards."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, Iterable, List

from job_radar.fetchers.ats import ATS_FETCHERS
from job_radar.fetchers.custom import fetch_custom_many_sync

logger = logging.getLogger(__name__)

DEFAULT_API_WORKERS = 32
API_ATS = frozenset(ATS_FETCHERS.keys())


@dataclass
class CompanyFetch:
    """The acquisition result for one company, retained in input order."""

    company: dict
    jobs: List[Any]
    method: str
    error: str | None = None


def _env_positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        logger.warning("Ignoring invalid %s value", name)
        return default


def _fetch_api_company(company: dict) -> CompanyFetch:
    ats = company.get("ats", "unknown").lower()
    slug = company.get("slug")
    if not slug:
        return CompanyFetch(company, [], ats, "Missing ATS slug")
    try:
        jobs = ATS_FETCHERS[ats](slug)
        return CompanyFetch(company, jobs, ats)
    except Exception as exc:
        return CompanyFetch(company, [], ats, str(exc))


def fetch_companies(companies: Iterable[dict]) -> List[CompanyFetch]:
    """Fetch jobs for companies with bounded parallelism and stable ordering."""
    company_list = list(companies)
    results: Dict[int, CompanyFetch] = {}
    api_items = [
        (index, company)
        for index, company in enumerate(company_list)
        if company.get("ats", "").lower() in API_ATS
    ]
    custom_items = [
        (index, company)
        for index, company in enumerate(company_list)
        if company.get("ats", "").lower() not in API_ATS
    ]
    logger.info(
        "Fetching %d companies concurrently (%d ATS API, %d custom)",
        len(company_list), len(api_items), len(custom_items),
    )

    api_workers = _env_positive_int("SCRAPER_API_WORKERS", DEFAULT_API_WORKERS)
    with ThreadPoolExecutor(
        max_workers=min(api_workers, max(1, len(api_items))),
        thread_name_prefix="ats-api",
    ) as executor:
        futures = {
            executor.submit(_fetch_api_company, company): index
            for index, company in api_items
        }

        custom_urls = [company.get("careers_url", "") for _, company in custom_items]
        custom_results = fetch_custom_many_sync(custom_urls)
        for index, company in custom_items:
            url = company.get("careers_url", "")
            if not url:
                results[index] = CompanyFetch(company, [], "custom", "Missing careers URL")
            else:
                results[index] = CompanyFetch(company, custom_results.get(url, []), "custom")

        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                company = company_list[index]
                results[index] = CompanyFetch(company, [], company.get("ats", "unknown"), str(exc))

    return [
        results.get(
            index,
            CompanyFetch(company, [], company.get("ats", "unknown"), "Unsupported ATS"),
        )
        for index, company in enumerate(company_list)
    ]

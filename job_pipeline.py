"""Shared concurrent acquisition layer for the visa and remote job pipelines."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, Iterable, List

from fetcher_custom import fetch_custom_many_sync
from fetchers import FETCHERS

logger = logging.getLogger(__name__)

DEFAULT_API_WORKERS = 12
API_ATS = frozenset(FETCHERS)


@dataclass
class CompanyFetch:
    """The acquisition result for one company, retained in input order."""

    company: dict
    jobs: List[dict]
    method: str
    error: str | None = None


def _env_positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        logger.warning("Ignoring invalid %s value", name)
        return default


def _fetch_api_company(company: dict) -> CompanyFetch:
    ats = company.get("ats", "unknown")
    slug = company.get("slug")
    if not slug:
        return CompanyFetch(company, [], ats, "Missing ATS slug")
    try:
        jobs = FETCHERS[ats](slug)
        return CompanyFetch(company, jobs, ats)
    except Exception as exc:
        return CompanyFetch(company, [], ats, str(exc))


def fetch_companies(companies: Iterable[dict]) -> List[CompanyFetch]:
    """Fetch jobs for companies with bounded parallelism and stable ordering.

    Public ATS APIs are fetched concurrently with a small fixed worker pool.
    Custom sources then share the static-first/browser fallback in
    ``fetcher_custom``.  We launch both branches together so slow rendering
    cannot leave the API workers idle.
    """
    company_list = list(companies)
    results: Dict[int, CompanyFetch] = {}
    api_items = [
        (index, company)
        for index, company in enumerate(company_list)
        if company.get("ats") in API_ATS
    ]
    custom_items = [
        (index, company)
        for index, company in enumerate(company_list)
        if company.get("ats") not in API_ATS
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

        # Run static requests and, only when needed, the shared browser while
        # API requests are still in flight.
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
            except Exception as exc:  # Defensive: a worker should not stop the run.
                company = company_list[index]
                results[index] = CompanyFetch(company, [], company.get("ats", "unknown"), str(exc))

    # A malformed entry must not change the result order or terminate a digest.
    return [
        results.get(
            index,
            CompanyFetch(company, [], company.get("ats", "unknown"), "Unsupported ATS"),
        )
        for index, company in enumerate(company_list)
    ]

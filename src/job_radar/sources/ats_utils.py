"""Helper utilities for ATS source adapters with robust path resolution and concurrent execution."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from job_radar.models.job import Job

logger = logging.getLogger(__name__)


def extract_slug_from_url(url: str, ats_name: str) -> Optional[str]:
    """Extract company slug from career board URL for known ATS platforms."""
    if not url:
        return None
    url = url.strip()
    parsed = urlparse(url if "://" in url else f"https://{url}")
    netloc = parsed.netloc.lower()
    path = parsed.path.strip("/").split("/")

    if ats_name == "greenhouse":
        if "greenhouse.io" in netloc and path:
            return path[0] if path[0] not in ("embed", "v1") else (path[1] if len(path) > 1 else None)
    elif ats_name == "lever":
        if "lever.co" in netloc and path:
            return path[0]
    elif ats_name == "ashby":
        if "ashbyhq.com" in netloc and path:
            return path[0]
    elif ats_name == "workable":
        if "workable.com" in netloc and path:
            return path[0]
    elif ats_name == "smartrecruiters":
        if "smartrecruiters.com" in netloc and path:
            return path[0]
    elif ats_name == "personio":
        if "personio" in netloc:
            subdomain = netloc.split(".")[0]
            if subdomain not in ("www", "jobs", "careers"):
                return subdomain
            if path:
                return path[0]

    # Fallback: if single word passed as URL, treat as slug
    if "/" not in url and "." not in url:
        return url
    return None


def get_curated_companies_for_ats(ats_name: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Load curated companies for a given ATS from data files, resolving paths
    relative to __file__, cwd, and container roots.
    """
    pkg_dir = Path(__file__).resolve().parent  # src/job_radar/sources
    repo_root = pkg_dir.parent.parent.parent  # repo root

    search_roots = [
        repo_root,
        repo_root / "data",
        Path.cwd(),
        Path.cwd() / "data",
        Path("/app"),
        Path("/app/data"),
    ]

    filenames = ["ai_companies.json", "companies.json", "remote_companies.json"]
    seen_names: Set[str] = set()
    results: List[Dict[str, Any]] = []

    for root in search_roots:
        if not root.exists():
            continue
        for fname in filenames:
            file_path = root / fname
            if not file_path.is_file():
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries = data.get("scrapable", []) + data.get("custom_ats", [])
                for c in entries:
                    if not isinstance(c, dict):
                        continue
                    c_ats = c.get("ats", "").lower()
                    c_name = c.get("name", "").strip()
                    if not c_name or c_name in seen_names:
                        continue
                    if c_ats == ats_name.lower():
                        seen_names.add(c_name)
                        results.append(c)
                        if limit and len(results) >= limit:
                            break
            except Exception as e:
                logger.debug("Failed loading %s: %s", file_path, e)

    if results:
        logger.info("Loaded %d curated company slugs for ATS '%s'.", len(results), ats_name)
    else:
        logger.warning("No curated company slugs found for enabled ATS '%s'.", ats_name)

    return results


async def fetch_ats_companies_concurrently(
    slugs: List[str] | Set[str],
    fetch_fn: Callable[..., List[Job]],
    days_back: int,
    max_per_source: int = 500,
    company_timeout_secs: float = 12.0,
    concurrency: int = 5,
) -> List[Job]:
    """
    Fetch jobs across company slugs concurrently using asyncio.to_thread with
    bounded concurrency and per-company timeouts.
    """
    sem = asyncio.Semaphore(concurrency)
    all_jobs: List[Job] = []

    async def _fetch_single(slug: str) -> List[Job]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(fetch_fn, slug=slug, days_back=days_back),
                    timeout=company_timeout_secs,
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout (%.1fs) fetching company slug '%s'", company_timeout_secs, slug)
                return []
            except Exception as e:
                logger.debug("Error fetching company slug '%s': %s", slug, e)
                return []

    tasks = [_fetch_single(s) for s in slugs]
    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=False)
    for job_list in results:
        all_jobs.extend(job_list)
        if len(all_jobs) >= max_per_source:
            return all_jobs[:max_per_source]

    return all_jobs

"""Fast, conservative fallback fetching for non-standard careers pages.

The supported ATS APIs in :mod:`fetchers` are always preferred.  This module is
only for career sites that do not expose one of those APIs.  It deliberately
uses a two-stage strategy:

1. Fetch and parse static HTML concurrently.  This is inexpensive and works for
   server-rendered pages, JSON-LD, Next.js payloads, and conventional job links.
2. Render only the remaining pages in a *single*, bounded Playwright browser.
   Starting Chromium once per company was the dominant cost of the daily runs.

It is a fallback, not an attempt to bypass access controls.  Pages that refuse
normal public access are recorded as empty and can be revisited after their ATS
is added to ``fetchers.py``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10
NAVIGATION_TIMEOUT_MS = 12_000
DEFAULT_STATIC_WORKERS = 24
DEFAULT_BROWSER_WORKERS = 6
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "JobDiscoveryBot/2.0"
)

_thread_local = threading.local()
_JOB_COLLECTION_KEYS = {
    "jobs", "jobpostings", "postings", "positions", "openings",
    "listings", "vacancies",
}
_JOB_URL_FIELDS = (
    "url", "hostedUrl", "applyUrl", "externalUrl", "absoluteUrl",
    "jobUrl", "job_url", "detailUrl", "detail_url",
)
_JOB_TITLE_FIELDS = ("title", "name", "text", "positionTitle", "jobTitle")
_GENERIC_LINK_TEXT = {
    "apply", "apply now", "apply for this job", "careers", "career",
    "jobs", "job", "view jobs", "view all jobs", "open positions",
    "see all jobs", "learn more",
}
_GENERIC_LINK_PREFIXES = (
    "see ", "view ", "browse ", "explore ", "find ", "search ",
    "learn ", "read ", "subscribe", "grab ", "edit ",
)
_NON_DETAIL_URL_MARKERS = (
    ".xml", ".rss", "/feed", "/rss", "/accessibility", "/all-jobs",
    "/job-search", "/search-jobs",
)


def _env_positive_int(name: str, default: int) -> int:
    """Read a positive integer environment setting without breaking a run."""
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        logger.warning("Ignoring invalid %s value", name)
        return default


def _http_session() -> requests.Session:
    """Get a per-thread retrying session; requests.Session is not shared."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET",)),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _thread_local.session = session
    return session


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _location_text(value: Any) -> str:
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            return _clean_text(
                address.get("addressLocality") or address.get("addressRegion") or address.get("addressCountry")
            )
        return _clean_text(
            value.get("name") or value.get("city") or value.get("address") or value.get("label")
        )
    if isinstance(value, list):
        return ", ".join(filter(None, (_location_text(item) for item in value)))
    return _clean_text(value)


def _job_from_mapping(
    item: dict[str, Any], base_url: str, *, trust_structured_url: bool = False
) -> Dict[str, str] | None:
    """Convert a likely job object to the project job schema."""
    title = next((_clean_text(item.get(field)) for field in _JOB_TITLE_FIELDS if item.get(field)), "")
    raw_url = next((_clean_text(item.get(field)) for field in _JOB_URL_FIELDS if item.get(field)), "")
    if not title or not raw_url:
        return None

    url = urljoin(base_url, raw_url)
    if trust_structured_url:
        parsed = urlparse(url)
        valid_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
    else:
        valid_url = _is_candidate_job_url(url, base_url)
    if not valid_url:
        return None

    department = item.get("department") or item.get("team") or item.get("category") or ""
    if isinstance(department, dict):
        department = department.get("name") or department.get("label") or ""
    return {
        "title": title[:300],
        "url": url,
        "location": _location_text(item.get("location") or item.get("jobLocation") or item.get("office")),
        "department": _clean_text(department),
    }


def _is_candidate_job_url(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    path = parsed.path.lower().rstrip("/")
    if path in ("", "/jobs", "/job", "/careers", "/career", "/positions", "/openings"):
        return False
    if any(marker in path for marker in _NON_DETAIL_URL_MARKERS):
        return False
    # Some ATS pages use an external apply host, but a normal job URL should
    # still contain one of these path components.
    return any(token in path for token in ("job", "career", "position", "opening", "vacanc", "apply"))


def _append_unique(jobs: List[Dict[str, str]], candidate: Dict[str, str] | None, seen_urls: set[str]) -> None:
    if candidate and candidate["url"] not in seen_urls:
        seen_urls.add(candidate["url"])
        jobs.append(candidate)


def _jobs_from_json(data: Any, base_url: str, depth: int = 0) -> List[Dict[str, str]]:
    """Find job-like items in JSON-LD and framework payloads conservatively."""
    if depth > 10:
        return []

    jobs: List[Dict[str, str]] = []
    seen_urls: set[str] = set()

    def visit(value: Any, key_hint: str = "", current_depth: int = 0) -> None:
        if current_depth > 10:
            return
        if isinstance(value, list):
            for child in value:
                visit(child, key_hint, current_depth + 1)
            return
        if not isinstance(value, dict):
            return

        type_value = value.get("@type", "")
        is_job_posting = (
            "JobPosting" in type_value
            if isinstance(type_value, list)
            else type_value == "JobPosting"
        )
        is_collection_item = key_hint.lower() in _JOB_COLLECTION_KEYS
        has_job_shape = any(field in value for field in _JOB_TITLE_FIELDS) and any(
            field in value for field in _JOB_URL_FIELDS
        )
        if is_job_posting or (is_collection_item and has_job_shape):
            _append_unique(
                jobs,
                _job_from_mapping(value, base_url, trust_structured_url=True),
                seen_urls,
            )

        for key, child in value.items():
            if key not in {"description", "html", "content"}:
                visit(child, str(key), current_depth + 1)

    visit(data, current_depth=depth)
    return jobs


def extract_jobs_from_html(html: str, base_url: str) -> List[Dict[str, str]]:
    """Extract structured job entries and well-formed job links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: List[Dict[str, str]] = []
    seen_urls: set[str] = set()

    # JSON-LD is the most reliable generic format.  Next.js and application/json
    # payloads are also common on career pages, so inspect those where available.
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        script_id = (script.get("id") or "").lower()
        if script_type not in {"application/ld+json", "application/json"} and script_id != "__next_data__":
            continue
        payload = script.string or script.get_text()
        if not payload:
            continue
        try:
            extracted = _jobs_from_json(json.loads(payload), base_url)
        except json.JSONDecodeError:
            continue
        for job in extracted:
            _append_unique(jobs, job, seen_urls)

    # Conventional listing links cover server-rendered sites that have no JSON
    # payload.  Only retain detail links and non-generic visible labels.
    for anchor in soup.find_all("a", href=True):
        href = _clean_text(anchor.get("href"))
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        if not _is_candidate_job_url(url, base_url):
            continue
        title = _clean_text(anchor.get_text(" ", strip=True))
        title_lower = title.lower()
        if (
            not title
            or title_lower in _GENERIC_LINK_TEXT
            or title_lower.startswith(_GENERIC_LINK_PREFIXES)
            or len(title) > 300
        ):
            continue
        _append_unique(
            jobs,
            {"title": title, "url": url, "location": "", "department": ""},
            seen_urls,
        )

    return jobs


def _fetch_static(url: str) -> List[Dict[str, str]]:
    response = _http_session().get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return extract_jobs_from_html(response.text, url)


async def _fetch_dynamic_pages(urls: List[str], workers: int) -> dict[str, List[Dict[str, str]]]:
    """Render URLs concurrently in one isolated browser/context."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed; skipping %d dynamic pages", len(urls))
        return {url: [] for url in urls}

    results: dict[str, List[Dict[str, str]]] = {url: [] for url in urls}
    semaphore = asyncio.Semaphore(workers)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )

        async def skip_heavy_assets(route) -> None:
            if route.request.resource_type in {"image", "media", "font"}:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", skip_heavy_assets)

        async def render(url: str) -> None:
            async with semaphore:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                    # Allow immediate client-side hydration without waiting for
                    # long-lived analytics, chat, or tracking connections.
                    await page.wait_for_timeout(350)
                    results[url] = extract_jobs_from_html(await page.content(), url)
                except Exception as exc:
                    logger.debug("Dynamic fetch failed for %s: %s", url, exc)
                finally:
                    await page.close()

        try:
            await asyncio.gather(*(render(url) for url in urls))
        finally:
            await context.close()
            await browser.close()

    return results


def _run_async(coro):
    """Run an async helper even when a caller already owns an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # Propagate the original browser failure.
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def fetch_custom_many_sync(urls: Iterable[str]) -> dict[str, List[Dict[str, str]]]:
    """Fetch many custom career URLs with static-first, shared-browser fallback.

    Results are keyed by URL.  Empty lists mean the public page exposed no
    extractable postings; an individual site never aborts the daily scan.
    Tune the bounded concurrency with ``SCRAPER_STATIC_WORKERS`` and
    ``SCRAPER_BROWSER_WORKERS`` if a self-hosted runner has less capacity.
    """
    unique_urls = list(dict.fromkeys(url for url in urls if url))
    results: dict[str, List[Dict[str, str]]] = {url: [] for url in unique_urls}
    static_workers = _env_positive_int("SCRAPER_STATIC_WORKERS", DEFAULT_STATIC_WORKERS)

    if not unique_urls:
        return results

    static_failures = 0
    with ThreadPoolExecutor(max_workers=min(static_workers, len(unique_urls)), thread_name_prefix="static-careers") as executor:
        futures = {executor.submit(_fetch_static, url): url for url in unique_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except requests.RequestException as exc:
                static_failures += 1
                logger.debug("Static fetch failed for %s: %s", url, exc)
            except Exception as exc:
                static_failures += 1
                logger.debug("Static parsing failed for %s: %s", url, exc)

    needs_browser = [url for url in unique_urls if not results[url]]
    if needs_browser and os.environ.get("SCRAPER_DISABLE_BROWSER", "").lower() not in {"1", "true", "yes"}:
        browser_workers = _env_positive_int("SCRAPER_BROWSER_WORKERS", DEFAULT_BROWSER_WORKERS)
        logger.info(
            "Custom fetch: %d/%d static hits; rendering %d remaining pages with one Chromium process (%d pages at a time)",
            len(unique_urls) - len(needs_browser), len(unique_urls), len(needs_browser), browser_workers,
        )
        try:
            dynamic_results = _run_async(_fetch_dynamic_pages(needs_browser, browser_workers))
            for url, jobs in dynamic_results.items():
                if jobs:
                    results[url] = jobs
        except Exception as exc:
            logger.warning("Shared Playwright fallback failed: %s", exc)
    elif needs_browser:
        logger.info("Custom fetch: browser fallback disabled; %d pages left unrendered", len(needs_browser))

    found = sum(bool(jobs) for jobs in results.values())
    logger.info(
        "Custom fetch complete: %d/%d sources yielded jobs (%d static request failures)",
        found, len(unique_urls), static_failures,
    )
    return results


async def fetch_with_playwright(url: str) -> List[Dict[str, str]]:
    """Backward-compatible async single-page API used by external callers."""
    results = await _fetch_dynamic_pages([url], workers=1)
    return results.get(url, [])


def fetch_custom_sync(url: str) -> List[Dict[str, str]]:
    """Backward-compatible synchronous single-page API."""
    return fetch_custom_many_sync([url]).get(url, [])

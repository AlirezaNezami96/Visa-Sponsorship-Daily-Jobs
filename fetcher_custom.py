"""Playwright-based fetcher for Workday, custom ATS, and generic career pages.
Runs headless Chromium to extract job listings.
No paid services — uses playwright (free, open-source).
"""
import asyncio
import re
import json
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Try to extract jobs from common patterns in page source
JOB_PATTERNS = [
    # Greenhouse embedded JSON
    (r'\"jobs\":\s*(\[.*?\])\s*[,}]', 'json_embedded'),
    # Lever embedded data
    (r'__NEXT_DATA__.*?"postings":\s*(\[.*?\])', 'json_embedded'),
    # Common job link patterns
    (r'href=["\']([^"\'/]*?/jobs/[^"\' ]+)["\']', 'link_pattern'),
    (r'href=["\']([^"\'/]*?/careers/[^"\' ]+job[^"\' ]*)["\']', 'link_pattern'),
]


def extract_jobs_from_html(html: str, base_url: str) -> List[Dict]:
    """Try to extract jobs from raw HTML without full browser rendering.
    Many sites embed job data in JSON blobs or have static job listing pages.
    """
    jobs = []

    # Pattern 1: Look for JSON blobs with job data
    json_patterns = [
        r'window\.\w+\s*=\s*(\{[^<]*"jobs"\s*:\s*\[[^<]*\][^<]*\})\s*;',
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        r'__NEXT_DATA__[^>]*>(.*?)</script>',
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                job_list = _find_jobs_in_json(data)
                if job_list:
                    jobs.extend(job_list)
            except (json.JSONDecodeError, TypeError):
                continue

    # Pattern 2: Look for job listing links
    job_link_patterns = [
        r'href=["\']([^"\'/]*?/jobs/\d+[^"\' ]*)["\']\s*[^>]*>([^<]+)<',
        r'href=["\']([^"\'/]*?/job/[^"\' ]+)["\']\s*[^>]*>([^<]+)<',
        r'class=["\'][^"\'>]*job[-_]?(?:card|item|listing|posting)[^"\'>]*["\'][^>]*>.*?href=["\']([^"\' ]+)["\']',
    ]

    seen_urls = {j["url"] for j in jobs}
    for pattern in job_link_patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        for m in matches:
            if len(m) == 2:
                url, title = m
            else:
                url = m[0]
                title = ""
            if url.startswith("/"):
                from urllib.parse import urljoin
                url = urljoin(base_url, url)
            if url not in seen_urls and ("job" in url.lower() or "position" in url.lower()):
                seen_urls.add(url)
                jobs.append({
                    "title": title.strip(),
                    "url": url,
                    "location": "",
                    "department": "",
                })

    # Deduplicate
    unique = []
    seen = set()
    for j in jobs:
        key = j["url"]
        if key not in seen and j["title"]:
            seen.add(key)
            unique.append(j)
    return unique


def _find_jobs_in_json(data, depth=0) -> Optional[List[Dict]]:
    """Recursively search JSON structure for job listings."""
    if depth > 10:
        return None

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            first = data[0]
            if any(k in first for k in ["title", "name", "text", "positionTitle"]):
                results = []
                for item in data:
                    title = (item.get("title") or item.get("name") or
                             item.get("text") or item.get("positionTitle") or "")
                    url = (item.get("url") or item.get("hostedUrl") or
                           item.get("applyUrl") or item.get("externalUrl") or
                           item.get("absoluteUrl") or "")
                    loc = (item.get("location", {}) or {}).get("name", "") if isinstance(item.get("location"), dict) else str(item.get("location", ""))
                    if title and url:
                        results.append({
                            "title": str(title),
                            "url": str(url),
                            "location": str(loc) if loc else "",
                            "department": "",
                        })
                if results:
                    return results

    if isinstance(data, dict):
        for key, val in data.items():
            if key.lower() in ("jobs", "postings", "positions", "openings", "listings"):
                result = _find_jobs_in_json(val, depth + 1)
                if result:
                    return result

    return None


async def fetch_with_playwright(url: str) -> List[Dict]:
    """Use Playwright to render a page and extract jobs.
    Tries fast HTTP request pre-check first, then falls back to fast Chromium rendering.
    """
    # 1. Fast HTTP pre-check (0.5s - 2s) to avoid launching Playwright if static HTML has jobs
    try:
        r = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code == 200:
            quick_jobs = extract_jobs_from_html(r.text, url)
            if quick_jobs:
                return quick_jobs
    except Exception:
        pass

    # 2. Playwright rendering with optimized fast timeouts
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed.")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        jobs = []
        try:
            # Fast domcontentloaded navigation (8s timeout max)
            await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            await page.wait_for_timeout(1000)

            # Job listing selectors
            job_selectors = [
                "a[href*='/jobs/']",
                "a[href*='/job/']",
                "a[href*='/position/']",
                "[class*='job-card']",
                "[class*='job-item']",
                "[class*='job-listing']",
                "[data-testid*='job']",
                "li[class*='opening']",
            ]

            elements = []
            for selector in job_selectors:
                try:
                    found = await page.query_selector_all(selector)
                    if found:
                        elements.extend(found)
                        break
                except Exception:
                    continue

            seen_urls = set()
            for el in elements:
                try:
                    href = await el.get_attribute("href") or ""
                    text = (await el.inner_text()).strip()

                    if not href or not text:
                        continue

                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)

                    if not any(x in href.lower() for x in ["/job", "/position", "/opening", "/careers"]):
                        continue

                    if any(x in href.lower() for x in ["/jobs$", "/careers$", "?page="]):
                        continue

                    if href not in seen_urls and len(text) > 5:
                        seen_urls.add(href)
                        jobs.append({
                            "title": text.split("\n")[0][:200],
                            "url": href,
                            "location": "",
                            "department": "",
                        })
                except Exception:
                    continue

            if not jobs:
                html = await page.content()
                jobs = extract_jobs_from_html(html, url)

        except Exception as e:
            logger.warning(f"Playwright error for {url}: {e}")
            try:
                html = await page.content()
                jobs = extract_jobs_from_html(html, url)
            except Exception:
                pass
        finally:
            await browser.close()

    return jobs


def fetch_custom_sync(url: str) -> List[Dict]:
    """Synchronous wrapper for fetch_with_playwright."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
        return loop.run_until_complete(fetch_with_playwright(url))
    except RuntimeError:
        return asyncio.run(fetch_with_playwright(url))

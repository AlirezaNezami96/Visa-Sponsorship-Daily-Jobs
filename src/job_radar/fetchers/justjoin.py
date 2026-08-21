"""Fetcher for JustJoin.it job offers (AI/ML & Mobile tracks)."""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

JUSTJOIN_URLS = {
    "AI / ML": "https://justjoin.it/job-offers/all-locations/ai?published-date=1",
    "Mobile": "https://justjoin.it/job-offers/all-locations/mobile?published-date=1",
}


def extract_jobs_from_justjoin_html(raw_html: str, category_name: str) -> List[Dict[str, Any]]:
    """Extract job offers from JustJoin.it listing HTML."""
    if not raw_html:
        return []

    soup = BeautifulSoup(raw_html, "html.parser")
    jobs: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for li in soup.find_all("li"):
        a_card = li.find("a", href=re.compile(r"/job-offer/"))
        if not a_card:
            continue

        href = a_card.get("href", "").strip()
        if not href or href in seen_urls:
            continue

        full_url = href if href.startswith("http") else f"https://justjoin.it{href}"
        seen_urls.add(href)
        seen_urls.add(full_url)

        # Title: from a_card title or h2/h3/h4 or link text
        title = ""
        card_title_attr = a_card.get("title", "")
        if card_title_attr.startswith("View offer "):
            title = card_title_attr[len("View offer "):].strip()
        if not title:
            h_tag = li.find(["h2", "h3", "h4"])
            if h_tag:
                title = h_tag.get_text(strip=True)
        if not title:
            title = a_card.get_text(strip=True)

        title = html.unescape(title).strip()

        # Company: check lucide-building container or img alt
        company = ""
        building_svg = li.find("svg", class_=re.compile(r"lucide-building"))
        if building_svg and building_svg.find_parent("div"):
            company_p = building_svg.find_parent("div").find_parent("div")
            if company_p:
                company = company_p.get_text(strip=True)
        if not company:
            img = li.find("img", alt=True)
            if img and img.get("alt") and img.get("alt").lower() not in {"logo", "missing", "image"}:
                company = img.get("alt").strip()
        if not company:
            lines = [line.strip() for line in li.get_text(separator="\n").split("\n") if line.strip()]
            company = lines[0] if lines else "JustJoin"

        company = html.unescape(company).strip()

        # Location: check lucide-map-pin
        location = ""
        map_svg = li.find("svg", class_=re.compile(r"lucide-map-pin"))
        if map_svg and map_svg.find_parent("div"):
            loc_container = map_svg.find_parent("button") or map_svg.find_parent("div")
            if loc_container:
                location = loc_container.get_text(strip=True)
        if not location:
            location = "All Locations"

        location = html.unescape(location).strip()

        text_all = li.get_text()
        is_remote = "remote" in text_all.lower()

        # Salary detection
        salary = None
        for txt in [t.strip() for t in li.get_text(separator="\n").split("\n") if t.strip()]:
            if any(cur in txt for cur in ["PLN", "EUR", "USD", "GBP", "CHF", "/month", "/rok", "/hr", "/h", "/day"]):
                salary = txt
                break

        if title and full_url:
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": full_url,
                "salary": salary,
                "remote": is_remote,
                "category": category_name,
            })

    return jobs


def _fetch_justjoin_url_static(url: str, timeout: int = 15) -> str:
    """Fetch JustJoin page via requests."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _fetch_justjoin_url_playwright(url: str, timeout_ms: int = 12000) -> str:
    """Fallback fetch via Playwright in case static requests gets blocked."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed for JustJoin fallback.")
        return ""

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector("a[href*='/job-offer/']", timeout=4000)
            except Exception:
                pass
            content = page.content()
            browser.close()
            return content
    except Exception as exc:
        logger.warning("Playwright JustJoin fetch failed for %s: %s", url, exc)
        return ""


def fetch_justjoin_category_jobs(
    category: str,
    url: str,
    use_playwright_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch job offers for a single JustJoin.it category URL."""
    logger.info("Fetching JustJoin [%s] from %s", category, url)
    html_content = ""
    try:
        html_content = _fetch_justjoin_url_static(url)
    except Exception as exc:
        logger.warning("Static fetch failed for JustJoin [%s]: %s", category, exc)

    jobs = extract_jobs_from_justjoin_html(html_content, category)

    if not jobs and use_playwright_fallback:
        logger.info("Static fetch returned 0 jobs for [%s]. Trying Playwright fallback...", category)
        pw_html = _fetch_justjoin_url_playwright(url)
        if pw_html:
            jobs = extract_jobs_from_justjoin_html(pw_html, category)

    logger.info("Extracted %d jobs from JustJoin [%s]", len(jobs), category)
    return jobs


def fetch_justjoin_jobs() -> List[Dict[str, Any]]:
    """Fetch all configured JustJoin.it job offers (AI & Mobile)."""
    all_jobs: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for category, url in JUSTJOIN_URLS.items():
        try:
            cat_jobs = fetch_justjoin_category_jobs(category, url)
            for j in cat_jobs:
                url_key = j.get("url", "")
                if url_key and url_key not in seen_urls:
                    seen_urls.add(url_key)
                    all_jobs.append(j)
        except Exception as exc:
            logger.warning("Failed fetching JustJoin category %s: %s", category, exc)

    logger.info("Total JustJoin candidate jobs fetched: %d", len(all_jobs))
    return all_jobs

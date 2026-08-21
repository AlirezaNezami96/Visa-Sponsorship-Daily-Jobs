"""Enrichment module to discover and attach official Company LinkedIn pages to jobs."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_LINKEDIN_CACHE_PATH = "state/company_linkedin_cache.json"
EXCLUDED_LINKEDIN_SLUGS = {
    "jobs", "search", "home", "in", "showcase", "feed", "login",
    "share", "learning", "pulse", "school", "company", "help",
}


def load_linkedin_cache(cache_path: str = DEFAULT_LINKEDIN_CACHE_PATH) -> Dict[str, Optional[str]]:
    """Load cached company -> linkedin_url mappings from disk."""
    candidates = [
        cache_path,
        os.path.join("data", os.path.basename(cache_path)),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.debug("Failed to load linkedin cache from %s: %s", c, exc)
    return {}


def save_linkedin_cache(cache: Dict[str, Optional[str]], cache_path: str = DEFAULT_LINKEDIN_CACHE_PATH) -> None:
    """Save cached company -> linkedin_url mappings to disk."""
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as exc:
        logger.warning("Failed to save linkedin cache to %s: %s", cache_path, exc)


def is_slug_relevant(company_name: str, slug: str) -> bool:
    """Verify that a LinkedIn company slug is reasonably related to the company name."""
    if not company_name or not slug:
        return False
    clean_company = re.sub(
        r"\b(inc|corp|corporation|llc|ltd|gmbh|sp\s*z\s*o\s*o|technologies|technology|solutions|group|holdings|co|software|labs)\b",
        "",
        company_name.lower(),
    )
    clean_company = re.sub(r"[^a-z0-9]", "", clean_company)
    clean_slug = re.sub(r"[^a-z0-9]", "", slug.lower())

    if not clean_company or not clean_slug:
        return False
    if clean_slug in EXCLUDED_LINKEDIN_SLUGS:
        return False

    if clean_company in clean_slug or clean_slug in clean_company:
        return True
    if len(clean_company) >= 4 and clean_company[:4] in clean_slug:
        return True
    return False


def extract_linkedin_from_html(html_text: str, target_company: Optional[str] = None) -> Optional[str]:
    """Extract official company LinkedIn page URL from HTML content."""
    if not html_text:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    candidates = []

    # Priority 1: <footer> links
    footer = soup.find(["footer", "nav"])
    search_areas = [footer, soup] if footer else [soup]

    for area in search_areas:
        if not area:
            continue
        for a in area.find_all("a", href=True):
            href = a.get("href", "").strip()
            match = re.search(
                r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([a-zA-Z0-9_\-\.%]+)",
                href,
            )
            if match:
                slug = match.group(1).rstrip("/")
                if slug.lower() not in EXCLUDED_LINKEDIN_SLUGS:
                    canonical_url = f"https://www.linkedin.com/company/{slug}"
                    if not target_company or is_slug_relevant(target_company, slug):
                        return canonical_url
                    candidates.append(canonical_url)

    return candidates[0] if candidates else None


def _decode_bing_redirect(link: str) -> str:
    """Extract destination URL from Bing redirect link."""
    if not link or "bing.com/ck/a" not in link:
        return link or ""
    try:
        parsed = urlsplit(link)
        qs = parse_qs(parsed.query)
        u_val = qs.get("u", [""])[0]
        if u_val:
            b64_str = re.sub(r"^a[0-9]", "", u_val)
            b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
            return base64.b64decode(b64_str).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return link


def _fetch_page_html(url: str, timeout: float = 4.0) -> str:
    """Fetch raw HTML from a website URL safely."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def _search_website_and_footer(company_name: str) -> Optional[str]:
    """Search for the company's official homepage, fetch it, and extract LinkedIn link from footer."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    # Search for company website
    search_url = f"https://www.bing.com/search?q={company_name}+official+website"
    try:
        r = requests.get(search_url, headers=headers, timeout=3.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for li in soup.find_all("li", class_="b_algo")[:2]:
                a = li.find("a", href=True)
                if a:
                    hp_url = _decode_bing_redirect(a.get("href", ""))
                    if not hp_url or any(x in hp_url.lower() for x in ["wikipedia.org", "crunchbase.com", "glassdoor.com", "indeed.com", "linkedin.com"]):
                        continue
                    html_content = _fetch_page_html(hp_url, timeout=3.5)
                    if html_content:
                        extracted = extract_linkedin_from_html(html_content, target_company=company_name)
                        if extracted:
                            return extracted
    except Exception as exc:
        logger.debug("Website search failed for '%s': %s", company_name, exc)
    return None


def _search_linkedin_direct(company_name: str) -> Optional[str]:
    """Search directly for the company's LinkedIn profile page."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    search_url = f"https://www.bing.com/search?q={company_name}+linkedin+company"
    try:
        r = requests.get(search_url, headers=headers, timeout=3.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for li in soup.find_all("li", class_="b_algo")[:3]:
                a = li.find("a", href=True)
                if a:
                    real_url = _decode_bing_redirect(a.get("href", ""))
                    match = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([a-zA-Z0-9_\-\.%]+)", real_url)
                    if match:
                        slug = match.group(1).rstrip("/")
                        if is_slug_relevant(company_name, slug):
                            return f"https://www.linkedin.com/company/{slug}"
    except Exception as exc:
        logger.debug("Direct LinkedIn search failed for '%s': %s", company_name, exc)
    return None


def _resolve_via_gemini(company_name: str) -> Optional[str]:
    """Fallback resolution via Gemini if GEMINI_API_KEY is available."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = (
            f"What is the official LinkedIn company page URL for '{company_name}'? "
            "Return ONLY the URL in the format https://www.linkedin.com/company/<slug> or 'null' if not found."
        )
        model = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
        interaction = client.interactions.create(
            model=model,
            input=prompt,
        )
        text = (interaction.output_text or "").strip()
        match = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([a-zA-Z0-9_\-\.%]+)", text)
        if match:
            slug = match.group(1).rstrip("/")
            if slug.lower() not in EXCLUDED_LINKEDIN_SLUGS:
                return f"https://www.linkedin.com/company/{slug}"
    except Exception as exc:
        logger.debug("Gemini LinkedIn resolution failed for '%s': %s", company_name, exc)
    return None


def find_company_linkedin(company_name: str, cache: Optional[Dict[str, Optional[str]]] = None) -> Optional[str]:
    """Find the official LinkedIn company page URL for a given company name."""
    if not company_name or company_name.strip().lower() in {"indeed", "justjoin", "remote", "company", "unknown"}:
        return None

    name_clean = company_name.strip()
    cache_key = name_clean.lower()

    if cache is not None and cache_key in cache:
        return cache[cache_key]

    # Strategy 1: Direct search for company LinkedIn profile
    url = _search_linkedin_direct(name_clean)

    # Strategy 2: Official website search and footer scraping
    if not url:
        url = _search_website_and_footer(name_clean)

    # Strategy 3: Gemini Search Grounding fallback
    if not url and os.environ.get("GEMINI_API_KEY"):
        url = _resolve_via_gemini(name_clean)

    if cache is not None:
        cache[cache_key] = url

    return url


def enrich_jobs_with_linkedin(
    jobs: List[Dict[str, Any]],
    cache_path: str = DEFAULT_LINKEDIN_CACHE_PATH,
    max_workers: int = 8,
) -> None:
    """Enrich all jobs in-place with official company LinkedIn page URLs."""
    if not jobs:
        return

    cache = load_linkedin_cache(cache_path)
    unique_companies = sorted({
        j.get("company", "").strip()
        for j in jobs
        if j.get("company") and j.get("company").strip().lower() not in {"indeed", "justjoin", "remote", "company", "unknown"}
    })

    if not unique_companies:
        for j in jobs:
            j.setdefault("company_linkedin_url", None)
        return

    # Check which companies need lookup
    needed = [c for c in unique_companies if c.lower() not in cache]
    if needed:
        logger.info("Resolving LinkedIn company pages for %d unique companies (%d already cached)...", len(needed), len(unique_companies) - len(needed))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_company = {
                pool.submit(find_company_linkedin, c, cache): c
                for c in needed
            }
            for future in as_completed(future_to_company):
                c = future_to_company[future]
                try:
                    res = future.result()
                    cache[c.lower()] = res
                    if res:
                        logger.debug("Resolved LinkedIn for %s -> %s", c, res)
                except Exception as exc:
                    logger.debug("Error resolving LinkedIn for %s: %s", c, exc)
                    cache[c.lower()] = None

        save_linkedin_cache(cache, cache_path)
    else:
        logger.debug("All %d companies found in LinkedIn cache.", len(unique_companies))

    # Inject company_linkedin_url into all jobs
    for j in jobs:
        cname = j.get("company", "").strip().lower()
        j["company_linkedin_url"] = cache.get(cname)

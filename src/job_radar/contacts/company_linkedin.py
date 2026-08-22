"""Company LinkedIn Page & Company ID Discovery Service."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.enrichment.linkedin import find_company_linkedin, load_linkedin_cache, save_linkedin_cache

logger = logging.getLogger(__name__)

DEFAULT_LINKEDIN_ID_CACHE_PATH = "state/company_linkedin_id_cache.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def load_linkedin_id_cache(cache_path: str = DEFAULT_LINKEDIN_ID_CACHE_PATH) -> Dict[str, str]:
    """Load cached company -> linkedin_company_id mappings."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug("Failed to load linkedin ID cache from %s: %s", cache_path, e)
    return {}


def save_linkedin_id_cache(cache: Dict[str, str], cache_path: str = DEFAULT_LINKEDIN_ID_CACHE_PATH) -> None:
    """Save cached company -> linkedin_company_id mappings."""
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as e:
        logger.warning("Failed to save linkedin ID cache to %s: %s", cache_path, e)


def extract_linkedin_company_id_from_url(linkedin_url: str) -> Optional[str]:
    """Extract numeric company ID if the URL itself is numeric (e.g. /company/101649602/)."""
    if not linkedin_url:
        return None
    match = re.search(r"linkedin\.com/company/(\d+)/?", linkedin_url)
    if match:
        return match.group(1)
    return None


def fetch_linkedin_company_id_from_page(linkedin_url: str) -> Optional[str]:
    """
    Fetch public LinkedIn company page to extract organization URN/ID from page metadata or JSON-LD.
    """
    if not linkedin_url:
        return None

    # Check if URL already has numeric ID
    direct_id = extract_linkedin_company_id_from_url(linkedin_url)
    if direct_id:
        return direct_id

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(linkedin_url, headers=headers, timeout=5.0, allow_redirects=True)
        if r.status_code == 200:
            text = r.text

            # Pattern 1: urn:li:organization:12345 or urn:li:company:12345
            match = re.search(r"urn:li:(?:organization|company):(\d+)", text)
            if match:
                return match.group(1)

            # Pattern 2: "objectUrn":"urn:li:company:12345" or "entityUrn":"urn:li:company:12345"
            match = re.search(r'"(?:objectUrn|entityUrn)":\s*"urn:li:(?:organization|company):(\d+)"', text)
            if match:
                return match.group(1)

            # Pattern 3: currentCompany=["12345"] or currentCompany%22%3A%5B%2212345%22%5D
            match = re.search(r'currentCompany(?:%22%3A%5B%22|%5B%22|\["|"\["|:\[")(\d+)', text)
            if match:
                return match.group(1)

            # Pattern 4: fs_normalized_company:12345
            match = re.search(r"fs_normalized_company:(\d+)", text)
            if match:
                return match.group(1)

            # Pattern 5: meta tags
            soup = BeautifulSoup(text, "html.parser")
            for meta in soup.find_all("meta"):
                content = meta.get("content", "")
                m = re.search(r"linkedin\.com/company/(\d+)", content)
                if m:
                    return m.group(1)

    except Exception as e:
        logger.debug("Failed to fetch LinkedIn company page %s: %s", linkedin_url, e)

    return None


def find_company_linkedin_info(
    company_name: str,
    company_domain: str = "",
    cache_dir: str = "state",
) -> Optional[Dict[str, str]]:
    """
    Reuses existing job_radar.enrichment.linkedin service to find company LinkedIn URL
    and extracts numeric LinkedIn Company ID.
    """
    if not company_name:
        return None

    clean_name = company_name.strip()
    norm_key = clean_name.lower()

    url_cache = load_linkedin_cache(os.path.join(cache_dir, "company_linkedin_cache.json"))
    id_cache = load_linkedin_id_cache(os.path.join(cache_dir, "company_linkedin_id_cache.json"))

    # 1. Resolve LinkedIn Company URL (Reusing existing service)
    linkedin_url = find_company_linkedin(clean_name, cache=url_cache)
    if not linkedin_url and company_domain:
        # Try with domain name if raw company name returned null
        domain_name = company_domain.split(".")[0].capitalize()
        linkedin_url = find_company_linkedin(domain_name, cache=url_cache)

    if not linkedin_url:
        logger.info("[HiringContacts] LinkedIn company page not found for '%s'", clean_name)
        return None

    save_linkedin_cache(url_cache, os.path.join(cache_dir, "company_linkedin_cache.json"))
    logger.info("[HiringContacts] LinkedIn company found: %s", linkedin_url)

    # 2. Extract or Fetch LinkedIn Company ID
    company_id = id_cache.get(norm_key) or id_cache.get(linkedin_url.lower())
    if not company_id:
        company_id = extract_linkedin_company_id_from_url(linkedin_url)
        if not company_id:
            company_id = fetch_linkedin_company_id_from_page(linkedin_url)

        if company_id:
            id_cache[norm_key] = company_id
            id_cache[linkedin_url.lower()] = company_id
            save_linkedin_id_cache(id_cache, os.path.join(cache_dir, "company_linkedin_id_cache.json"))

    if not company_id:
        logger.warning("[HiringContacts] Could not extract numeric LinkedIn Company ID for %s (%s)", clean_name, linkedin_url)
        # Fallback: if slug is available, return info with slug as fallback identifier
        slug_match = re.search(r"linkedin\.com/company/([a-zA-Z0-9_\-\.%]+)", linkedin_url)
        slug = slug_match.group(1).rstrip("/") if slug_match else clean_name
        return {
            "companyName": clean_name,
            "linkedinUrl": linkedin_url,
            "linkedinCompanyId": slug,
        }

    logger.info("[HiringContacts] LinkedIn company ID: %s", company_id)
    return {
        "companyName": clean_name,
        "linkedinUrl": linkedin_url,
        "linkedinCompanyId": str(company_id),
    }

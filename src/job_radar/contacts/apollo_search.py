"""Apollo 0-Credit People Search Service for Hiring Contacts Discovery."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

APOLLO_API_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"

# Tier 1: Precise Technical & Engineering Recruiter / Talent Acquisition titles
TITLES_TIER_1 = [
    "Technical Recruiter",
    "Technical Talent Acquisition",
    "Technical Talent Acquisition Partner",
    "Talent Acquisition Partner",
    "Talent Acquisition Specialist",
    "Talent Acquisition Manager",
    "Talent Acquisition Lead",
    "Talent Acquisition",
    "Technical Recruiting",
    "Recruiter",
    "Recruiting Manager",
    "Recruiting Lead",
    "Recruitment Manager",
    "Talent Partner",
    "People Partner",
    "HR Manager",
    "Head of Talent",
    "Head of People",
    "Engineering Recruiter",
    "Engineering Talent Acquisition",
    "Engineering Manager",
    "Hiring Manager",
    "Head of Engineering",
    "Director of Engineering",
    "VP Engineering",
    "CTO",
]

# Tier 2: Broader recruiting, people, and HR titles
TITLES_TIER_2 = [
    "Recruiter",
    "Talent Acquisition",
    "Recruiting",
    "People",
    "HR",
    "Talent",
    "Engineering Manager",
    "Engineering Leadership",
]

# Tier 3: Broad Engineering & Product leadership titles
TITLES_TIER_3 = [
    "Engineering Manager",
    "Hiring Manager",
    "Head of Engineering",
    "Director of Engineering",
    "VP Engineering",
    "VP of Engineering",
    "CTO",
    "Chief Technology Officer",
    "Lead Software Engineer",
    "Staff Software Engineer",
]


def extract_job_keywords(job_title: str) -> List[str]:
    """Extract relevant search keywords from job title for q_organization_job_titles."""
    if not job_title:
        return ["Software Engineer", "Engineering"]

    raw = job_title.lower()
    keywords = set()

    if "android" in raw or "mobile" in raw or "flutter" in raw or "ios" in raw:
        keywords.update(["Android", "Mobile", "Software Engineer"])
    elif "frontend" in raw or "front-end" in raw or "react" in raw or "web" in raw:
        keywords.update(["Frontend", "Web", "Software Engineer"])
    elif "backend" in raw or "back-end" in raw or "server" in raw or "python" in raw or "java" in raw:
        keywords.update(["Backend", "Software Engineer", "Engineering"])
    elif "data" in raw or "ai" in raw or "ml" in raw or "machine learning" in raw:
        keywords.update(["Data", "AI", "Machine Learning", "Software Engineer"])
    else:
        # Default engineering keywords
        keywords.update(["Software Engineer", "Engineering"])

    return sorted(list(keywords))


def search_apollo_people(
    company_domain: str,
    job_title: str = "",
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search Apollo for relevant hiring contacts at the target company domain.
    Uses multi-tier fallback strategy to guarantee results without person enrichment.
    """
    key = api_key or os.environ.get("APOLLO_API_KEY")
    if not key:
        logger.warning("[HiringContacts] APOLLO_API_KEY is not configured.")
        return []

    if not company_domain:
        logger.warning("[HiringContacts] Missing company domain for Apollo People search.")
        return []

    clean_domain = company_domain.strip().lower()
    job_keywords = extract_job_keywords(job_title)

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": key,
    }

    logger.info("[HiringContacts] Apollo search started for domain '%s'", clean_domain)

    # Strategy Attempt 1: Precise titles + active job keywords
    payload_1 = {
        "api_key": key,
        "q_organization_domains_list": [clean_domain],
        "person_titles": TITLES_TIER_1,
        "q_organization_job_titles": job_keywords,
        "page": 1,
        "per_page": 25,
    }

    results = _execute_apollo_query(payload_1, headers)
    if len(results) >= 3:
        logger.info("[HiringContacts] Apollo returned %d candidates in Attempt 1 (precise)", len(results))
        return results

    # Strategy Attempt 2: Precise titles without restrictive job keyword filter
    payload_2 = {
        "api_key": key,
        "q_organization_domains_list": [clean_domain],
        "person_titles": TITLES_TIER_1,
        "page": 1,
        "per_page": 25,
    }

    results_2 = _execute_apollo_query(payload_2, headers)
    if len(results_2) >= 3:
        logger.info("[HiringContacts] Apollo returned %d candidates in Attempt 2 (broadened domain query)", len(results_2))
        return results_2

    # Strategy Attempt 3: Broader engineering and talent leadership titles
    payload_3 = {
        "api_key": key,
        "q_organization_domains_list": [clean_domain],
        "person_titles": TITLES_TIER_2 + TITLES_TIER_3,
        "page": 1,
        "per_page": 25,
    }

    results_3 = _execute_apollo_query(payload_3, headers)
    logger.info("[HiringContacts] Apollo returned %d candidates in Attempt 3 (leadership fallback)", len(results_3))
    return results_3 if results_3 else results_2 or results


def _execute_apollo_query(payload: Dict[str, Any], headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Execute a single HTTP request to Apollo People Search API."""
    try:
        r = requests.post(APOLLO_API_URL, json=payload, headers=headers, timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            people = data.get("people", [])
            return people
        elif r.status_code == 401:
            logger.error("[HiringContacts] Apollo authentication failed: invalid API key (HTTP 401)")
        elif r.status_code == 429:
            logger.warning("[HiringContacts] Apollo rate limit reached (HTTP 429)")
        else:
            logger.warning("[HiringContacts] Apollo API returned HTTP %d: %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[HiringContacts] Apollo search request failed: %s", e)
    return []

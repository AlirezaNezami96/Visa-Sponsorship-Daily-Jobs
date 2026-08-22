"""LinkedIn People Search URL Builder."""
from __future__ import annotations

import logging
from typing import List
from urllib.parse import quote

logger = logging.getLogger(__name__)

LINKEDIN_PEOPLE_SEARCH_BASE = "https://www.linkedin.com/search/results/people/"


def build_linkedin_people_search_url(
    names: List[str],
    company_linkedin_id: str,
) -> str:
    """
    Build a safe, properly encoded LinkedIn People Search URL scoped to the company
    containing all contact names combined with Boolean OR.

    Example URL:
    https://www.linkedin.com/search/results/people/?keywords=%22Ertan%20Bera%22%20OR%20%22Jane%20Smith%22&origin=GLOBAL_SEARCH_HEADER&currentCompany=%5B%22101649602%22%5D
    """
    if not names:
        return ""

    # Clean and wrap names in quotes
    cleaned_names = []
    for n in names:
        if not n:
            continue
        # Strip existing quotes if any
        clean = n.strip().strip('"').strip("'")
        if clean:
            cleaned_names.append(f'"{clean}"')

    if not cleaned_names:
        return ""

    # Combine with Boolean OR
    boolean_query = " OR ".join(cleaned_names)
    encoded_keywords = quote(boolean_query, safe="")

    # Build company parameter: ["companyId"] -> %5B%22companyId%22%5D
    clean_company_id = str(company_linkedin_id).strip()
    encoded_company = quote(f'["{clean_company_id}"]', safe="")

    search_url = (
        f"{LINKEDIN_PEOPLE_SEARCH_BASE}"
        f"?keywords={encoded_keywords}"
        f"&origin=GLOBAL_SEARCH_HEADER"
        f"&currentCompany={encoded_company}"
    )

    logger.info("[HiringContacts] LinkedIn search URL generated: %s", search_url)
    return search_url

"""LinkedIn search query and URL builder for recruiter and hiring manager discovery.

Generates safe, ToS-compliant LinkedIn deep links for candidates, recruiters, and managers.
"""
from __future__ import annotations

import urllib.parse
from typing import Dict, List, Optional


def build_linkedin_search_url(keywords: str) -> str:
    """Build a search URL for LinkedIn People Search."""
    encoded = urllib.parse.quote(keywords.strip())
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded}"


def generate_company_recruiter_search_links(
    company_name: str,
    job_title: str = "",
) -> Dict[str, str]:
    """Generate the 4 standard LinkedIn discovery queries for a job opening.

    Queries:
      1. Recruiter search: "{company} recruiter"
      2. Talent acquisition: "{company} talent acquisition"
      3. Role manager: "{company} {job_title} manager"
      4. Department lead: "{company} engineering manager" or department lead
    """
    clean_company = company_name.strip()
    if not clean_company:
        return {}

    dept_term = "engineering manager"
    if job_title:
        title_lower = job_title.lower()
        if "product" in title_lower:
            dept_term = "head of product"
        elif "design" in title_lower:
            dept_term = "design director"
        elif "market" in title_lower:
            dept_term = "marketing director"
        elif "sales" in title_lower:
            dept_term = "sales manager"
        elif "finance" in title_lower:
            dept_term = "finance manager"

    role_mgr = f"{clean_company} {job_title} manager" if job_title else f"{clean_company} hiring manager"

    return {
        "recruiter_search": build_linkedin_search_url(f"{clean_company} recruiter"),
        "talent_acquisition_search": build_linkedin_search_url(f"{clean_company} talent acquisition"),
        "hiring_manager_search": build_linkedin_search_url(role_mgr),
        "department_lead_search": build_linkedin_search_url(f"{clean_company} {dept_term}"),
    }

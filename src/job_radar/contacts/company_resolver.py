"""Company and Domain Resolver for Job Postings."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Known career platform hosts mapping to company subdomain/path
PLATFORM_HOSTS = {
    "greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "jobs.lever.co": "lever",
    "ashbyhq.com": "ashby",
    "jobs.ashbyhq.com": "ashby",
    "smartrecruiters.com": "smartrecruiters",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "workable.com": "workable",
    "apply.workable.com": "workable",
    "myworkdayjobs.com": "workday",
    "myworkdaysite.com": "workday",
    "bamboohr.com": "bamboohr",
    "recruitee.com": "recruitee",
    "teamtailor.com": "teamtailor",
    "personio.de": "personio",
    "personio.com": "personio",
}


def normalize_domain(raw_domain_or_url: str) -> str:
    """Normalize a domain string or URL to a clean lowercase domain (e.g., 'example.com')."""
    if not raw_domain_or_url:
        return ""

    text = str(raw_domain_or_url).strip()
    if not text:
        return ""

    # If scheme missing, prepend http:// to parse domain correctly
    if "://" not in text:
        text = "http://" + text

    try:
        parsed = urlparse(text)
        netloc = parsed.netloc or parsed.path
        # Remove port if present
        netloc = netloc.split(":")[0]
        # Remove leading www.
        netloc = re.sub(r"^www\.", "", netloc, flags=re.IGNORECASE)
        # Remove trailing slashes and lowercase
        domain = netloc.strip().lower().rstrip("/")
        # Filter invalid short domains
        if "." in domain and len(domain) > 3:
            return domain
    except Exception as e:
        logger.debug("Failed to parse domain from '%s': %s", raw_domain_or_url, e)

    return ""


def clean_company_name(raw_name: str) -> str:
    """Clean and normalize company name for search."""
    if not raw_name:
        return ""
    name = str(raw_name).strip()
    # Remove URL schemes if a URL was passed
    name = re.sub(r"https?://\S+", "", name)
    # Remove common filler labels
    name = re.sub(r"^(about|at|for|working at)\s+", "", name, flags=re.IGNORECASE)
    # Clean excessive whitespace
    name = re.sub(r"\s+", " ", name).strip()
    if name.lower() in {"company", "unknown company", "unknown", "n/a", "null", "none", "company name"}:
        return ""
    return name


def derive_company_and_domain_from_url(page_url: str) -> Tuple[str, str]:
    """Derive company name and domain from standard ATS or direct career page URLs."""
    if not page_url:
        return "", ""

    try:
        parsed = urlparse(page_url)
        host = parsed.netloc.lower()
        host = re.sub(r"^www\.", "", host)
        path = parsed.path.strip("/")
        parts = path.split("/")

        # 1. Greenhouse: boards.greenhouse.io/{company}/... or job-boards.greenhouse.io/{company}/...
        if "greenhouse.io" in host:
            if parts and parts[0] and parts[0] not in {"embed", "jobs"}:
                company = parts[0].replace("-", " ").title()
                return company, f"{parts[0]}.com"
            elif len(parts) > 1 and parts[0] == "jobs":
                company = parts[1].replace("-", " ").title()
                return company, f"{parts[1]}.com"

        # 2. Lever: jobs.lever.co/{company}/...
        if "lever.co" in host:
            if parts and parts[0]:
                company = parts[0].replace("-", " ").title()
                return company, f"{parts[0]}.com"

        # 3. Ashby: jobs.ashbyhq.com/{company}/...
        if "ashbyhq.com" in host:
            if parts and parts[0]:
                company = parts[0].replace("-", " ").title()
                return company, f"{parts[0]}.com"

        # 4. SmartRecruiters: jobs.smartrecruiters.com/{company}/...
        if "smartrecruiters.com" in host:
            if parts and parts[0]:
                company = parts[0].replace("-", " ").title()
                return company, f"{parts[0]}.com"

        # 5. Workday: {company}.wd3.myworkdayjobs.com or {company}.myworkdayjobs.com
        if "myworkdayjobs.com" in host or "myworkday.com" in host:
            sub = host.split(".")[0]
            company = sub.replace("-", " ").title()
            return company, f"{sub}.com"

        # 6. Direct company career sites: careers.allegro.eu or jobs.spotify.com
        host_parts = host.split(".")
        if len(host_parts) >= 2:
            if host_parts[0] in {"careers", "jobs", "career", "job"}:
                company = host_parts[1].capitalize()
                domain = ".".join(host_parts[1:])
                return company, domain
            else:
                # Direct domain e.g. allegro.eu or stripe.com
                company = host_parts[0].capitalize()
                domain = host
                return company, domain

    except Exception as e:
        logger.debug("Failed to derive company from url %s: %s", page_url, e)

    return "", ""


def resolve_company_and_domain(
    job_data: Optional[Dict[str, Any]] = None,
    page_url: str = "",
    jd_text: str = "",
) -> Tuple[str, str]:
    """
    Resolve company name and normalized domain using priority order:
    1. Structured job data
    2. Page URL / platform pattern
    3. Job description content
    """
    company_name = ""
    company_domain = ""

    # Priority 1: Structured Job Data
    if job_data:
        company_name = clean_company_name(
            job_data.get("company")
            or job_data.get("company_name")
            or job_data.get("employer")
            or job_data.get("hiring_organization")
            or job_data.get("organization")
            or ""
        )
        company_domain = normalize_domain(
            job_data.get("company_domain")
            or job_data.get("domain")
            or job_data.get("employer_domain")
            or job_data.get("company_url")
            or ""
        )

    # Priority 2: Current Page URL
    if not company_name or not company_domain:
        derived_name, derived_domain = derive_company_and_domain_from_url(page_url)
        if not company_name and derived_name:
            company_name = derived_name
        if not company_domain and derived_domain:
            company_domain = derived_domain

    # Priority 3: Fallback domain from company name
    if company_name and not company_domain:
        clean_slug = re.sub(r"[^a-zA-Z0-9]", "", company_name).lower()
        if clean_slug and clean_slug not in {"company", "unknown", "remote"}:
            company_domain = f"{clean_slug}.com"

    # Priority 4: Extract from JD text if company name still missing
    if not company_name and jd_text:
        match = re.search(r"\b(?:at|about|join)\s+([A-Z][a-zA-Z0-9\.\-]{2,25}(?:\s+[A-Z][a-zA-Z0-9\.\-]{2,25})?)(?:[:\s,]|$)", jd_text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in {"the team", "our team", "the company", "our company", "us"}:
                company_name = candidate
                if not company_domain:
                    company_domain = f"{re.sub(r'[^a-zA-Z0-9]', '', candidate).lower()}.com"

    return clean_company_name(company_name), normalize_domain(company_domain)

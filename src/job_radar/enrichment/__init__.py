"""Enrichment subpackage for job_radar."""
from job_radar.enrichment.company_scraper import CompanyWebsiteScraper
from job_radar.enrichment.contact_finder import ContactFinder, build_fallback_instructions, find_contacts
from job_radar.enrichment.email_finder import extract_emails_from_text, find_emails_for_contact
from job_radar.enrichment.linkedin import (
    enrich_jobs_with_linkedin,
    find_company_linkedin,
    load_linkedin_cache,
    save_linkedin_cache,
)
from job_radar.enrichment.linkedin_finder import (
    build_linkedin_search_url,
    generate_company_recruiter_search_links,
)
from job_radar.enrichment.pattern_matcher import (
    generate_email_patterns,
    get_generic_company_emails,
)

__all__ = [
    "enrich_jobs_with_linkedin",
    "find_company_linkedin",
    "load_linkedin_cache",
    "save_linkedin_cache",
    "ContactFinder",
    "find_contacts",
    "build_fallback_instructions",
    "CompanyWebsiteScraper",
    "extract_emails_from_text",
    "find_emails_for_contact",
    "build_linkedin_search_url",
    "generate_company_recruiter_search_links",
    "generate_email_patterns",
    "get_generic_company_emails",
]

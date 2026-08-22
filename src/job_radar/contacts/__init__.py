"""Hiring Contacts Discovery Package."""
from job_radar.contacts.service import HiringContactsService
from job_radar.contacts.company_resolver import resolve_company_and_domain
from job_radar.contacts.company_linkedin import find_company_linkedin_info
from job_radar.contacts.apollo_search import search_apollo_people
from job_radar.contacts.contact_ranker import rank_and_deduplicate_contacts
from job_radar.contacts.linkedin_search_builder import build_linkedin_people_search_url

__all__ = [
    "HiringContactsService",
    "resolve_company_and_domain",
    "find_company_linkedin_info",
    "search_apollo_people",
    "rank_and_deduplicate_contacts",
    "build_linkedin_people_search_url",
]

"""Contact information finder orchestrator for VisaLane.

Combines multiple free discovery methods:
  1. Company website team / leadership page scraping
  2. Job posting text explicit email & recruiter extraction
  3. Email pattern generation (marked as pattern_guess)
  4. Safe LinkedIn search deep-links for recruiters & hiring managers
  5. 4 Actionable fallback instructions when no direct contacts exist
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from .company_scraper import CompanyWebsiteScraper
from .email_finder import extract_emails_from_text, find_emails_for_contact
from .linkedin_finder import generate_company_recruiter_search_links
from .pattern_matcher import get_generic_company_emails

logger = logging.getLogger(__name__)


def build_fallback_instructions(
    company_name: str,
    company_domain: str,
    job_title: str,
    job_url: str = "",
) -> List[Dict[str, Any]]:
    """Build the 4 actionable fallback instructions specified in Phase 4 §5.2."""
    search_links = generate_company_recruiter_search_links(company_name, job_title)
    generic_emails = get_generic_company_emails(company_domain) if company_domain else []

    return [
        {
            "step": 1,
            "title": "Search LinkedIn for Recruiters",
            "instruction": f"Search for talent acquisition specialists and recruiters at {company_name}.",
            "action_url": search_links.get("recruiter_search", ""),
            "action_label": f"Find Recruiters at {company_name}",
        },
        {
            "step": 2,
            "title": "Search for Hiring Manager",
            "instruction": f"Search for the hiring manager or department lead for {job_title} at {company_name}.",
            "action_url": search_links.get("hiring_manager_search", ""),
            "action_label": f"Find {job_title} Managers",
        },
        {
            "step": 3,
            "title": "Check Original Job Posting",
            "instruction": "Review the full job listing on the company careers site for direct contact emails or application instructions.",
            "action_url": job_url,
            "action_label": "View Original Job Posting",
        },
        {
            "step": 4,
            "title": "Try General Department Mailboxes",
            "instruction": "If no personal contact is available, reach out directly to the company's hiring inbox.",
            "suggested_emails": generic_emails[:3],
            "action_label": "Copy Email Addresses",
        },
    ]


class ContactFinder:
    """Orchestrates multi-method contact information discovery."""

    def __init__(self, db_client: Optional[Any] = None):
        self.db_client = db_client
        self.scraper = CompanyWebsiteScraper()

    def find_contacts_for_job(
        self,
        job_id: str,
        company_name: str,
        company_domain: str = "",
        job_title: str = "",
        job_description: str = "",
        job_url: str = "",
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discover contact information for a job posting.

        Returns:
            Dict with contacts list, count, search links, and fallback instructions.
        """
        all_contacts: List[Dict[str, Any]] = []

        # 1. Extract from Job Description Text (Highest confidence)
        posting_emails = extract_emails_from_text(job_description)
        for em in posting_emails:
            all_contacts.append({
                "name": None,
                "title": "Job Posting Contact",
                "email": em["email"],
                "email_status": em["email_status"],
                "email_confidence": em["confidence"],
                "source_method": "job_posting_extraction",
                "confidence_score": em["confidence"],
            })

        # 2. Scrape Company Website
        if company_domain:
            scrape_res = self.scraper.scrape_company_team(company_domain)
            for member in scrape_res.get("contacts", []):
                # Try to pair with domain emails
                member_emails = find_emails_for_contact(
                    first_name=member["name"].split()[0],
                    last_name=member["name"].split()[-1] if len(member["name"].split()) > 1 else "",
                    company_domain=company_domain,
                )
                primary_email = member_emails[0]["email"] if member_emails else None
                primary_status = member_emails[0]["email_status"] if member_emails else "not_found"

                all_contacts.append({
                    "name": member["name"],
                    "title": member.get("title"),
                    "email": primary_email,
                    "email_status": primary_status,
                    "email_confidence": member_emails[0].get("confidence", 30) if member_emails else None,
                    "source_method": "company_website_scraping",
                    "confidence_score": member.get("confidence_score", 60),
                })

        # 3. Generate Search Links
        search_links = generate_company_recruiter_search_links(company_name, job_title)

        # 4. Generate Fallback Instructions
        fallback_instructions = build_fallback_instructions(
            company_name=company_name,
            company_domain=company_domain,
            job_title=job_title,
            job_url=job_url,
        )

        result = {
            "success": True,
            "job_id": job_id,
            "company_name": company_name,
            "company_domain": company_domain,
            "contacts": all_contacts,
            "count": len(all_contacts),
            "search_links": search_links,
            "fallback_instructions": fallback_instructions,
        }

        # 5. Persist to job_people if DB client provided
        if self.db_client and all_contacts:
            self._persist_contacts(job_id, company_id, all_contacts)

        return result

    def _persist_contacts(
        self,
        job_id: str,
        company_id: Optional[str],
        contacts: List[Dict[str, Any]],
    ) -> None:
        """Save discovered contacts to job_people table."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = []
        for c in contacts:
            rows.append({
                "job_id": job_id,
                "company_id": company_id,
                "name": c.get("name"),
                "title": c.get("title"),
                "email": c.get("email"),
                "email_status": c.get("email_status", "not_found"),
                "email_confidence": c.get("email_confidence"),
                "source_method": c.get("source_method"),
                "confidence_score": c.get("confidence_score", 50),
                "found_at": now_iso,
            })
        try:
            self.db_client.table("job_people").insert(rows).execute()
        except Exception as exc:
            logger.debug("Failed to persist job_people records: %s", exc)


def find_contacts(
    job_id: str,
    company_name: str,
    company_domain: str = "",
    job_title: str = "",
    job_description: str = "",
    job_url: str = "",
    db_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Convenience functional helper for contact discovery."""
    finder = ContactFinder(db_client=db_client)
    return finder.find_contacts_for_job(
        job_id=job_id,
        company_name=company_name,
        company_domain=company_domain,
        job_title=job_title,
        job_description=job_description,
        job_url=job_url,
    )

"""Hiring Contacts Orchestrator Service with Caching and Structured Logging."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from job_radar.contacts.company_resolver import resolve_company_and_domain
from job_radar.contacts.company_linkedin import find_company_linkedin_info
from job_radar.contacts.apollo_search import search_apollo_people
from job_radar.contacts.contact_ranker import rank_and_deduplicate_contacts
from job_radar.contacts.linkedin_search_builder import build_linkedin_people_search_url

logger = logging.getLogger(__name__)

DEFAULT_CONTACTS_CACHE_PATH = "state/hiring_contacts_cache.json"
CACHE_TTL_SECONDS = 24 * 3600  # 24 hours


class HiringContactsService:
    """Orchestrates end-to-end Hiring Contacts discovery workflow."""

    def __init__(self, cache_path: str = DEFAULT_CONTACTS_CACHE_PATH):
        self.cache_path = cache_path
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("Failed to load contacts cache: %s", e)
        return {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save contacts cache: %s", e)

    def _get_cache_key(self, domain_or_company: str, job_title: str) -> str:
        clean_target = domain_or_company.strip().lower()
        norm_title = re.sub(r"[^a-zA-Z0-9]", "", job_title.lower()) if job_title else "general"
        return f"{clean_target}:{norm_title}"

    def find_hiring_contacts(
        self,
        job_data: Optional[Dict[str, Any]] = None,
        company_name: str = "",
        company_domain: str = "",
        job_title: str = "",
        page_url: str = "",
        jd_text: str = "",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Main entry point for finding hiring contacts at the company for a job posting.
        """
        logger.info("[HiringContacts] Slider opened / Request received")

        # 1. Resolve Company and Domain
        resolved_company, resolved_domain = resolve_company_and_domain(
            job_data=job_data or ({"company": company_name, "company_domain": company_domain} if company_name else None),
            page_url=page_url,
            jd_text=jd_text,
        )

        if not resolved_company and not resolved_domain:
            logger.warning("[HiringContacts] Unable to identify company or domain")
            return {
                "success": False,
                "error": "Unable to identify company from job posting",
                "contacts": [],
                "count": 0,
            }

        logger.info("[HiringContacts] Company detected: %s", resolved_company or "Unknown")
        logger.info("[HiringContacts] Domain detected: %s", resolved_domain or "Unknown")

        # 2. Check 24-hour Cache
        cache_key = self._get_cache_key(resolved_domain or resolved_company, job_title)
        if not force_refresh and cache_key in self._cache:
            entry = self._cache[cache_key]
            if time.time() - entry.get("timestamp", 0) < CACHE_TTL_SECONDS:
                logger.info("[HiringContacts] Returning cached contacts for '%s'", cache_key)
                return entry.get("data", {})

        # 3. Discover Company LinkedIn Page & Company ID (best-effort)
        linkedin_url = ""
        linkedin_company_id = ""
        if resolved_company or resolved_domain:
            try:
                linkedin_info = find_company_linkedin_info(
                    company_name=resolved_company,
                    company_domain=resolved_domain,
                )
                if linkedin_info:
                    linkedin_url = linkedin_info.get("linkedinUrl") or ""
                    linkedin_company_id = linkedin_info.get("linkedinCompanyId") or ""
                    if linkedin_url:
                        logger.info("[HiringContacts] LinkedIn company found: %s", linkedin_url)
                    if linkedin_company_id:
                        logger.info("[HiringContacts] LinkedIn company ID: %s", linkedin_company_id)
            except Exception as e:
                logger.debug("[HiringContacts] LinkedIn discovery warning: %s", e)

        # 4. Search Apollo for Relevant Contacts (0 Credits)
        apollo_domain = resolved_domain or (f"{resolved_company.lower().replace(' ', '')}.com" if resolved_company else "")
        raw_people = []
        if apollo_domain:
            logger.info("[HiringContacts] Apollo search started for domain '%s'", apollo_domain)
            raw_people = search_apollo_people(
                company_domain=apollo_domain,
                job_title=job_title,
            )
            logger.info("[HiringContacts] Apollo returned %d candidates", len(raw_people))

        # 5. Rank and Deduplicate Contacts
        ranked_contacts = rank_and_deduplicate_contacts(
            people=raw_people,
            job_title=job_title,
            max_results=5,
        )
        logger.info("[HiringContacts] Ranked top %d candidates", len(ranked_contacts))

        # 6. Build LinkedIn People Search URL
        contact_names = [c["name"] for c in ranked_contacts if c.get("name")]
        linkedin_search_url = ""
        if contact_names:
            linkedin_search_url = build_linkedin_people_search_url(
                names=contact_names,
                company_linkedin_id=linkedin_company_id,
                company_name=resolved_company,
            )

        result_data = {
            "success": True,
            "company_name": resolved_company,
            "company_domain": resolved_domain,
            "linkedin_url": linkedin_url,
            "linkedin_company_id": linkedin_company_id,
            "contacts": [
                {
                    "name": c["name"],
                    "title": c["title"],
                    "score": c["score"],
                    "id": c["id"],
                }
                for c in ranked_contacts
            ],
            "linkedin_search_url": linkedin_search_url,
            "count": len(ranked_contacts),
        }

        # Save to Cache
        self._cache[cache_key] = {
            "timestamp": time.time(),
            "data": result_data,
        }
        self._save_cache()

        logger.info("[HiringContacts] Completed")
        return result_data

"""Contact enrichment stage for VisaLane jobs.

Primary path: the existing 0-credit Apollo People Search service
(job_radar.contacts.HiringContactsService) — ported intact from the
"Find Hiring Contacts with 0-credit Apollo People Search" work.

Safe fallback chain layered on top (master plan section 6.3):
  1. 0-credit Apollo People Search (name + title, no email spend)
  2. Job-posting email extraction (talent@/jobs@/careers@/recruiting@/hr@)
  3. Generic pattern emails from known person names — status='pattern_guess',
     confidence <= 40. NEVER presented as verified personal emails.
  4. LinkedIn search deep-links (always generated, zero ban risk)

Hard safety rules: LinkedIn personal profiles are never scraped, and no
fabricated email may ever carry email_status='verified'.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

GENERIC_EMAIL_RE = re.compile(
    r"\b(talent|jobs|careers|career|recruiting|recruitment|hr|people|hiring|join)\s*@\s*([a-z0-9.-]+\.[a-z]{2,})\b",
    re.IGNORECASE,
)

PATTERN_GUESS_CONFIDENCE = 35
GENERIC_EMAIL_CONFIDENCE = 80


def extract_posting_emails(text: str) -> list[str]:
    """Extract generic recruiting mailboxes from JD text."""
    if not text:
        return []
    found = {f"{m.group(1).lower()}@{m.group(2).lower()}" for m in GENERIC_EMAIL_RE.finditer(text)}
    return sorted(found)[:5]


def guess_pattern_emails(person_name: str, domain: str) -> list[str]:
    """First-name / first.last pattern guesses for a known person name.

    These are ALWAYS low-confidence guesses (status='pattern_guess'); the FE
    must label them as such and never claim verification.
    """
    if not person_name or not domain:
        return []
    parts = re.findall(r"[A-Za-z]+", person_name)
    if not parts:
        return []
    first = parts[0].lower()
    last = parts[-1].lower() if len(parts) > 1 else ""
    domain = domain.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0]
    if "." not in domain:
        return []
    guesses = [f"{first}@{domain}"]
    if last:
        guesses.append(f"{first}.{last}@{domain}")
    return guesses


def enrich_job_contacts(client, job: dict[str, Any], service=None) -> int:
    """Run the enrichment chain for one job; write job_people rows.

    Returns the number of contact rows written.
    """
    company = str(job.get("company") or "")
    if not company:
        return 0

    if service is None:
        from job_radar.contacts.service import HiringContactsService

        service = HiringContactsService()

    desc = str(job.get("description") or job.get("description_text") or job.get("snippet") or "")
    result = service.find_hiring_contacts(
        company_name=company,
        company_domain=str(job.get("company_domain") or ""),
        job_title=str(job.get("title") or ""),
        page_url=str(job.get("url") or ""),
        jd_text=desc[:4000],
    )

    rows: list[dict[str, Any]] = []
    domain = (result.get("company_domain") or job.get("company_domain") or "") if isinstance(result, dict) else ""
    if isinstance(domain, str):
        domain = domain.lower()

    linkedin_search_url = (result or {}).get("linkedin_search_url", "")
    contacts = (result or {}).get("contacts") or []

    for contact in contacts:
        name = contact.get("name") or ""
        person_row: dict[str, Any] = {
            "job_id": job.get("job_db_id"),
            "company_id": job.get("company_db_id"),
            "name": name,
            "title": contact.get("title"),
            "email": None,
            "email_status": "not_found",
            "linkedin_search_url": linkedin_search_url or None,
            "source_url": job.get("url"),
            "source_type": "apollo_zero_credit",
            "confidence": min(90, 40 + int(contact.get("score") or 0) // 2),
        }
        rows.append(person_row)

        for guess in guess_pattern_emails(name, domain):
            rows.append(
                {
                    "job_id": job.get("job_db_id"),
                    "company_id": job.get("company_db_id"),
                    "name": name,
                    "title": contact.get("title"),
                    "email": guess,
                    "email_status": "pattern_guess",
                    "email_confidence": PATTERN_GUESS_CONFIDENCE,
                    "linkedin_search_url": linkedin_search_url or None,
                    "source_url": job.get("url"),
                    "source_type": "pattern_guess",
                    "confidence": PATTERN_GUESS_CONFIDENCE,
                }
            )
            break  # one pattern guess per person keeps volume sane

    for email in extract_posting_emails(desc):
        rows.append(
            {
                "job_id": job.get("job_db_id"),
                "company_id": job.get("company_db_id"),
                "name": None,
                "title": "Recruiting mailbox",
                "email": email,
                "email_status": "generic",
                "email_confidence": GENERIC_EMAIL_CONFIDENCE,
                "linkedin_search_url": linkedin_search_url or None,
                "source_url": job.get("url"),
                "source_type": "job_posting",
                "confidence": GENERIC_EMAIL_CONFIDENCE,
            }
        )

    if not rows:
        return 0

    rows = [{k: v for k, v in r.items() if v is not None} for r in rows]
    try:
        client.table("job_people").insert(rows).execute()
        logger.info("Enrichment: wrote %d contact rows for '%s'", len(rows), company)
        return len(rows)
    except Exception as exc:
        logger.warning("job_people insert failed for '%s': %s", company, exc)
        return 0

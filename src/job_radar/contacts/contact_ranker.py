"""Contact Ranking and Deduplication Service."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def score_contact(person: Dict[str, Any], job_title: str = "") -> int:
    """Calculate deterministic relevance score for a contact."""
    title = (person.get("title") or "").lower().strip()
    seniority = (person.get("seniority") or "").lower().strip()
    departments = [d.lower() for d in person.get("departments") or []]
    subdepartments = [s.lower() for s in person.get("subdepartments") or []]

    score = 0

    # ── Recruiter & Talent Acquisition Base Scores ──
    if "technical recruiter" in title or "engineering recruiter" in title:
        score = 100
    elif "technical talent acquisition" in title or "engineering talent acquisition" in title:
        score = 100
    elif "talent acquisition partner" in title or "talent partner" in title:
        score = 90
    elif "talent acquisition manager" in title or "talent acquisition lead" in title:
        score = 85
    elif "recruiting manager" in title or "recruiting lead" in title or "technical recruiting" in title:
        score = 80
    # ── Engineering Leadership Base Scores ──
    elif "hiring manager" in title:
        score = 95
    elif "engineering manager" in title or "software engineering manager" in title:
        score = 90
    elif "head of engineering" in title or "head of software" in title:
        score = 85
    elif "director of engineering" in title or "engineering director" in title:
        score = 80
    elif "vp engineering" in title or "vp of engineering" in title or "vice president of engineering" in title:
        score = 75
    elif "cto" in title or "chief technology officer" in title:
        score = 70
    # ── General Recruiting / HR Base Scores ──
    elif "recruiter" in title:
        score = 70
    elif "recruiting" in title or "talent acquisition" in title:
        score = 65
    elif "hr manager" in title or "human resources manager" in title:
        score = 50
    elif "people partner" in title or "head of people" in title:
        score = 45
    elif "talent" in title or "people" in title or "human resources" in title:
        score = 40
    else:
        score = 30

    # ── Relevance Bonuses ──
    # +20 if job family matches (e.g. mobile/android/ios for mobile job)
    if job_title:
        job_lower = job_title.lower()
        if ("android" in job_lower or "mobile" in job_lower or "flutter" in job_lower) and ("mobile" in title or "android" in title):
            score += 20
        elif ("frontend" in job_lower or "web" in job_lower) and ("frontend" in title or "web" in title):
            score += 20
        elif "backend" in job_lower and "backend" in title:
            score += 20

    # +15 if person's title contains Engineering, Technical, Technology, or Talent Acquisition
    if any(k in title for k in ["engineering", "technical", "technology", "talent acquisition"]):
        score += 15

    # +10 if seniority is manager/director/head/vp/c-suite
    if any(s in seniority for s in ["manager", "director", "head", "vp", "c_suite", "executive"]):
        score += 10

    # +10 if person is specifically in recruiting subdepartment
    if "recruiting" in subdepartments or "recruiting" in departments or "talent" in title:
        score += 10

    # ── Deductions ──
    # -30 for obviously unrelated departments
    if any(d in departments for d in ["sales", "marketing", "accounting", "finance", "legal", "customer_support", "operations"]):
        score -= 30

    # -20 for generic HR roles with no recruiting relevance
    if "payroll" in title or "benefits" in title or "compensation" in title or "workplace" in title:
        score -= 20

    # -20 for sales/marketing/account executive titles
    if any(k in title for k in ["account executive", "sales manager", "marketing manager", "bdr", "sdr"]):
        score -= 20

    return max(0, score)


def deduplicate_contacts(people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate people by Apollo ID, normalized full name + company, and name + title."""
    seen_ids = set()
    seen_names = set()
    seen_name_titles = set()
    unique_list = []

    for p in people:
        pid = p.get("id") or p.get("_id")
        first = (p.get("first_name") or "").strip()
        last = (p.get("last_name") or "").strip()
        full_name = (p.get("name") or f"{first} {last}").strip()
        title = (p.get("title") or "").strip().lower()
        company = (p.get("organization", {}).get("name") or "").strip().lower()

        if not full_name:
            continue

        norm_name = re.sub(r"[^a-zA-Z0-9]", "", full_name.lower())
        norm_name_co = f"{norm_name}:{company}"
        norm_name_title = f"{norm_name}:{title}"

        if pid and pid in seen_ids:
            continue
        if norm_name_co in seen_names:
            continue
        if norm_name_title in seen_name_titles:
            continue

        if pid:
            seen_ids.add(pid)
        seen_names.add(norm_name_co)
        seen_name_titles.add(norm_name_title)

        unique_list.append(p)

    return unique_list


def rank_and_deduplicate_contacts(
    people: List[Dict[str, Any]],
    job_title: str = "",
    min_results: int = 3,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """
    Deduplicate, score, and rank contacts to return top 3 to 5 people.
    """
    if not people:
        return []

    unique_people = deduplicate_contacts(people)

    scored_contacts = []
    for p in unique_people:
        score = score_contact(p, job_title=job_title)
        first = (p.get("first_name") or "").strip()
        last = (p.get("last_name") or "").strip()
        name = (p.get("name") or f"{first} {last}").strip()
        title = (p.get("title") or "Hiring Contact").strip()
        pid = p.get("id") or ""

        scored_contacts.append({
            "id": pid,
            "name": name,
            "title": title,
            "score": score,
            "first_name": first,
            "last_name": last,
            "raw": p,
        })

    # Sort descending by score
    scored_contacts.sort(key=lambda c: c["score"], reverse=True)

    # Return top 3-5 contacts
    top_contacts = scored_contacts[:max_results]
    logger.info("[HiringContacts] Ranked top %d candidates from %d unique people", len(top_contacts), len(unique_people))
    return top_contacts

"""Writes pipeline jobs into the VisaLane `companies` / `jobs` tables.

Dedup guarantees (master plan section 2.3): the same job arriving from two
sources produces ONE row, because rows are keyed by:
  canonical_url_hash = sha256(extract_canonical_job_url(url))  [UNIQUE]
and the (company, title, location) fingerprint is stored for cross-checks.
Both helpers are imported from job_radar.filters.dedupe — the exact same
normalization the existing seen-store uses, so runners cannot double-insert.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_COUNTRY_CODE_FIELDS = ("country_code", "countryCode", "location_country_code")


def canonical_url_hash(url: str) -> str:
    """sha256 hex of the canonical (tracking-stripped) job URL."""
    from job_radar.filters.dedupe import extract_canonical_job_url

    canonical = extract_canonical_job_url(url or "")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_fingerprint(job: dict[str, Any]) -> str:
    from job_radar.filters.dedupe import job_fingerprint

    return job_fingerprint(
        job.get("company", "") or "",
        job.get("title", "") or "",
        job.get("location", "") or "",
    )


def extract_company_domain(job: dict[str, Any]) -> str | None:
    """Best-effort company website domain from the job payload."""
    domain = job.get("company_domain")
    if domain:
        return str(domain).lower().strip()
    for key in ("company_website", "website", "company_url"):
        url = job.get(key)
        if url:
            try:
                return urlsplit(str(url)).netloc.lower()
            except ValueError:
                continue
    return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _work_mode(job: dict[str, Any]) -> str | None:
    wt = job.get("workplace_type") or job.get("work_mode")
    if wt:
        return str(wt)
    if job.get("remote") or job.get("is_remote"):
        return "remote"
    if job.get("is_hybrid"):
        return "hybrid"
    return None


def job_to_row(job: dict[str, Any], company_id: str | None) -> dict[str, Any] | None:
    """Map an enriched pipeline job dict onto the `jobs` table schema.

    Returns None when the job lacks a usable URL (cannot dedup without one).
    """
    url = job.get("url") or job.get("job_url") or job.get("apply_url") or ""
    title = job.get("title") or ""
    if not url or not title:
        return None

    desc = job.get("description") or job.get("description_text") or job.get("snippet") or ""
    visa_types = job.get("visa_types") or []
    if not visa_types and job.get("visa_type"):
        visa_types = [str(job["visa_type"])]

    country_code = None
    for field in _COUNTRY_CODE_FIELDS:
        if job.get(field):
            country_code = str(job[field]).upper()[:8]
            break

    row: dict[str, Any] = {
        "company_id": company_id,
        "source_name": str(job.get("source", "pipeline")),
        "source_url": url,
        "canonical_url_hash": canonical_url_hash(url),
        "fingerprint": compute_fingerprint(job),
        "title": title[:500],
        "location_raw": (job.get("location_raw") or job.get("location") or "")[:500],
        "country": job.get("country"),
        "country_code": country_code,
        "work_mode": _work_mode(job),
        "contract_type": job.get("employment_type") or job.get("job_type"),
        "salary_raw": job.get("salary_raw"),
        "salary_min": _to_int(job.get("salary_min")),
        "salary_max": _to_int(job.get("salary_max")),
        "salary_currency": job.get("salary_currency"),
        "description_text": desc[:20000] if desc else None,
        "visa_sponsorship_confidence": _to_int(job.get("visa_sponsorship_confidence")),
        "visa_sponsorship_verified": bool(job.get("visa_sponsorship_verified", False)),
        "visa_types": [str(v) for v in visa_types][:20] or None,
        "apply_url": job.get("apply_url") or url,
        "raw_payload": {
            k: job.get(k)
            for k in (
                "relevance_score",
                "visa_status",
                "visa_score",
                "visa_evidence",
                "classified_track",
                "remote_scope",
                "resume_match_score",
                "why_matched",
            )
            if job.get(k) is not None
        }
        or None,
    }

    posted = job.get("posted_at")
    if posted is not None:
        row["posted_at"] = getattr(posted, "isoformat", lambda: str(posted))()

    return {k: v for k, v in row.items() if v is not None}


def get_or_create_company(client, job: dict[str, Any]) -> str | None:
    """Upsert the company row and return its UUID (None on failure)."""
    name = (job.get("company") or "").strip()
    if not name:
        return None
    try:
        match = client.table("companies").select("id").ilike("name", name).limit(1).execute()
        if match.data:
            return match.data[0]["id"]

        payload = {
            "name": name,
            "website": extract_company_domain(job),
            "ats_type": job.get("ats"),
        }
        payload = {k: v for k, v in payload.items() if v}
        inserted = client.table("companies").insert(payload).execute()
        if inserted.data:
            return inserted.data[0]["id"]
    except Exception as exc:
        logger.warning("get_or_create_company failed for '%s': %s", name, exc)
    return None


def sync_jobs(client, jobs: list[dict[str, Any]], source_name: str = "pipeline") -> tuple[int, int]:
    """Insert enriched jobs; skip duplicates by canonical_url_hash.

    Newly inserted jobs get `job_db_id` and `company_db_id` set in-place so
    downstream stages (alerts/social/enrichment) can reference them.
    Returns (inserted, duplicates_or_skipped).
    """
    inserted = 0
    skipped = 0
    for job in jobs:
        row = job_to_row(job, company_id=None)
        if row is None:
            skipped += 1
            continue
        company_id = get_or_create_company(client, job)
        row["company_id"] = company_id
        try:
            result = (
                client.table("jobs").upsert(row, on_conflict="canonical_url_hash", ignore_duplicates=True).execute()
            )
            if result.data:
                inserted += 1
                job["job_db_id"] = result.data[0].get("id")
                job["company_db_id"] = company_id
            else:
                skipped += 1
        except Exception as exc:
            logger.warning("jobs upsert failed for '%s': %s", row.get("title"), exc)
            skipped += 1
    logger.info("VisaLane jobs sync: %d inserted, %d skipped/duplicate (source=%s)", inserted, skipped, source_name)
    return inserted, skipped

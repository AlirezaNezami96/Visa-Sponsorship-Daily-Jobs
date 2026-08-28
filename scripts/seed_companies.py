"""Seed the VisaLane `companies` table from the existing company JSON registries.

Reuses (never rebuilds) the curated registries shipped with the repo:
  - companies.json / data/companies.json
  - ai_companies.json / data/ai_companies.json
  - remote_companies.json / data/remote_companies.json

Each registry has `scrapable` and `custom_ats` arrays with entries like:
  {"name": "Stripe", "careers_url": "https://boards.greenhouse.io/stripe",
   "ats": "greenhouse", "slug": "stripe"}

Idempotent: skips companies already present (matched on normalized name).
Requires SUPABASE_URL + SUPABASE_KEY (service-role) env vars.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_companies")

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_NAMES = ["companies.json", "ai_companies.json", "remote_companies.json"]

ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "apply.workable.com": "workable",
    "smartrecruiters.com": "smartrecruiters",
    "personio.com": "personio",
    "personio.de": "personio",
}


def _load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = []
    for section in ("scrapable", "custom_ats"):
        bucket = data.get(section) or []
        if isinstance(bucket, list):
            entries.extend(e for e in bucket if isinstance(e, dict) and e.get("name"))
    return entries


def _norm_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _infer_website(careers_url: str) -> str | None:
    """Extract a likely company website host from a careers URL.

    Known ATS board hosts are not company websites, so they return None.
    """
    if not careers_url:
        return None
    try:
        host = urlsplit(careers_url).netloc.lower()
    except ValueError:
        return None
    if any(host == ats or host.endswith("." + ats) for ats in ATS_HOSTS):
        return None
    host = host.removeprefix("www.")
    return f"https://{host}" if host else None


def collect_companies() -> dict[str, dict[str, Any]]:
    """Merge all registries into a de-duplicated dict keyed by normalized name."""
    merged: dict[str, dict[str, Any]] = {}
    for registry in REGISTRY_NAMES:
        for candidate in (REPO_ROOT / registry, REPO_ROOT / "data" / registry):
            for entry in _load_registry(candidate):
                key = _norm_name(entry["name"])
                record = merged.setdefault(
                    key,
                    {
                        "name": entry["name"].strip(),
                        "ats_type": entry.get("ats") or "custom",
                        "website": None,
                    },
                )
                website = _infer_website(entry.get("careers_url", ""))
                if website and not record["website"]:
                    record["website"] = website
                if entry.get("ats") and record["ats_type"] in (None, "custom"):
                    record["ats_type"] = entry["ats"]
    return merged


def seed(dry_run: bool = False) -> int:
    companies = collect_companies()
    logger.info("Collected %d unique companies from registries", len(companies))

    if dry_run:
        for name, rec in list(companies.items())[:10]:
            logger.info("  [dry-run] %s -> %s", name, rec)
        return len(companies)

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        logger.error("SUPABASE_URL / SUPABASE_KEY not set — cannot seed.")
        return 1

    from supabase import create_client

    client = create_client(url, key)
    existing = {_norm_name(row["name"]) for row in client.table("companies").select("name").execute().data}

    rows = [
        {"name": rec["name"], "website": rec["website"], "ats_type": rec["ats_type"]}
        for key_name, rec in companies.items()
        if key_name not in existing
    ]
    if not rows:
        logger.info("Nothing to insert — all %d companies already present.", len(existing))
        return 0

    batch_size = 200
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        client.table("companies").upsert(batch, on_conflict="name,website").execute()
        inserted += len(batch)
        logger.info("Inserted %d/%d companies", inserted, len(rows))

    logger.info("Seeding complete: %d new companies (skipped %d existing).", inserted, len(existing))
    return 0


if __name__ == "__main__":
    sys.exit(seed(dry_run="--dry-run" in sys.argv))

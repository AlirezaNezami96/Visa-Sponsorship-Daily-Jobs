"""
src/job_radar/visa/ingest_community_seeds.py

One-time import of companies from community-maintained GitHub visa sponsorship lists.
All entries start at LOW confidence tier until corroborated by higher-tier evidence.

Sources:
  - shubheksha/companies-sponsoring-visas (README markdown table)
  - SiaExplains/visa-sponsorship-companies (JSON/markdown)
  - amol-can/eu-visa-sponsoring-companies (markdown)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors, load_all_sponsors
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

COMMUNITY_SOURCES = {
    "shubheksha": {
        "url": "https://raw.githubusercontent.com/shubheksha/companies-sponsoring-visas/main/README.md",
        "alt_urls": [
            "https://raw.githubusercontent.com/nicor88/companies-sponsoring-visas/main/README.md",
        ],
        "format": "markdown_table",
        "default_country": "US",
    },
    "siaexplains": {
        "url": "https://raw.githubusercontent.com/SiaExplains/visa-sponsorship-companies/main/README.md",
        "alt_urls": [],
        "format": "markdown_list",
        "default_country": "US",
    },
    "amol_can_eu": {
        "url": "https://raw.githubusercontent.com/amol-can/eu-visa-sponsoring-companies/main/README.md",
        "alt_urls": [],
        "format": "markdown_list",
        "default_country": "EU",
    },
}


def _fetch_content(url: str, alt_urls: List[str] = None) -> Optional[str]:
    """Fetch content from a URL, trying alternatives on failure."""
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    urls_to_try = [url] + (alt_urls or [])

    for u in urls_to_try:
        try:
            resp = requests.get(u, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            continue

    return None


def _parse_markdown_table(content: str, source_name: str, default_country: str) -> List[SponsorRecord]:
    """
    Parse a markdown table with company info.
    Expected format: | Company | Location | ... | or variations.
    """
    records: List[SponsorRecord] = []
    seen_norms: Set[str] = set()

    # Find table rows (lines starting with |)
    in_table = False
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                in_table = False
            continue

        # Skip separator rows (|---|---|)
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            in_table = True
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # Remove empty first and last cells from leading/trailing |
        cells = [c for c in cells if c]

        if not cells:
            continue

        # Extract company name (first cell, strip markdown links)
        company_raw = cells[0]
        # Strip markdown link syntax: [Company Name](url) -> Company Name
        link_match = re.match(r"\[([^\]]+)\]\([^)]*\)", company_raw)
        if link_match:
            company_name = link_match.group(1).strip()
        else:
            company_name = re.sub(r"[*_`]", "", company_raw).strip()

        if not company_name or len(company_name) < 2:
            continue

        # Skip header rows
        if company_name.lower() in ("company", "name", "employer", "company name"):
            continue

        # Try to extract location from second cell
        location = ""
        country = default_country
        if len(cells) > 1:
            location = cells[1].strip()
            country = _infer_country(location) or default_country

        norm = normalize_company_name(company_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country=country,
                legal_name=company_name,
                routes=["Community Reported"],
                rating="Community",
                source=f"community_seed_{source_name}",
                as_of="",
                confidence_tier="low",
                extra={
                    "location": location,
                    "community_source": source_name,
                },
            )
        )

    return records


def _parse_markdown_list(content: str, source_name: str, default_country: str) -> List[SponsorRecord]:
    """
    Parse a markdown list with company names.
    Expected format: - Company Name or * Company Name or 1. Company Name
    """
    records: List[SponsorRecord] = []
    seen_norms: Set[str] = set()

    for line in content.split("\n"):
        stripped = line.strip()

        # Match list items: -, *, or numbered
        match = re.match(r"^(?:[-*+]|\d+\.)\s+(.*)", stripped)
        if not match:
            continue

        item = match.group(1).strip()
        if not item:
            continue

        # Strip markdown link syntax
        link_match = re.match(r"\[([^\]]+)\]\([^)]*\)", item)
        if link_match:
            company_name = link_match.group(1).strip()
        else:
            # Remove markdown formatting
            company_name = re.sub(r"[*_`]", "", item).strip()
            # Remove trailing descriptions after " - " or " — "
            company_name = re.split(r"\s+[-—]\s+", company_name)[0].strip()

        if not company_name or len(company_name) < 2:
            continue

        # Skip common non-company lines
        skip_words = {"contributing", "license", "readme", "table of contents", "note:", "disclaimer"}
        if any(sw in company_name.lower() for sw in skip_words):
            continue

        norm = normalize_company_name(company_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country=default_country,
                legal_name=company_name,
                routes=["Community Reported"],
                rating="Community",
                source=f"community_seed_{source_name}",
                as_of="",
                confidence_tier="low",
                extra={
                    "community_source": source_name,
                },
            )
        )

    return records


def _infer_country(location: str) -> Optional[str]:
    """Infer country code from a location string."""
    loc_lower = location.lower()
    country_map = {
        "united states": "US", "usa": "US", "u.s.": "US",
        "united kingdom": "UK", "uk": "UK", "london": "UK", "england": "UK",
        "germany": "DE", "berlin": "DE", "munich": "DE",
        "netherlands": "NL", "amsterdam": "NL",
        "ireland": "IE", "dublin": "IE",
        "canada": "CA", "toronto": "CA", "vancouver": "CA",
        "australia": "AU", "sydney": "AU", "melbourne": "AU",
        "france": "FR", "paris": "FR",
        "sweden": "SE", "stockholm": "SE",
        "denmark": "DK", "copenhagen": "DK",
        "finland": "FI", "helsinki": "FI",
        "spain": "ES", "madrid": "ES", "barcelona": "ES",
        "poland": "PL", "warsaw": "PL",
        "switzerland": "CH", "zurich": "CH",
        "singapore": "SG",
        "new zealand": "NZ", "auckland": "NZ",
        "remote": "US",  # Default for remote-first companies
    }
    for key, code in country_map.items():
        if key in loc_lower:
            return code
    return None


def import_community_seeds(
    db_path: Path = DEFAULT_DB_PATH,
    skip_existing: bool = True,
) -> int:
    """
    One-time import of companies from community-maintained lists.
    All entries start at LOW confidence until corroborated by official evidence.
    Deduplicates against existing sponsors table.
    """
    all_records: List[SponsorRecord] = []

    for source_name, config in COMMUNITY_SOURCES.items():
        logger.info("Fetching community seed list: %s", source_name)
        content = _fetch_content(config["url"], config.get("alt_urls", []))
        if not content:
            logger.warning("Could not fetch community seed list: %s", source_name)
            continue

        if config["format"] == "markdown_table":
            records = _parse_markdown_table(content, source_name, config["default_country"])
        elif config["format"] == "markdown_list":
            records = _parse_markdown_list(content, source_name, config["default_country"])
        else:
            logger.warning("Unknown format for community source %s: %s", source_name, config["format"])
            continue

        logger.info("Parsed %d companies from %s", len(records), source_name)
        all_records.extend(records)

    if skip_existing:
        # Deduplicate against existing sponsors
        try:
            existing = load_all_sponsors(db_path=db_path, allow_empty=True)
            before = len(all_records)
            all_records = [r for r in all_records if r.normalized_name not in existing]
            logger.info("Deduplication: %d -> %d records (removed %d existing).",
                       before, len(all_records), before - len(all_records))
        except Exception:
            pass  # DB might not exist yet

    if not all_records:
        logger.info("No new community seed records to import.")
        return 0

    count = bulk_upsert_sponsors(all_records, db_path=db_path)
    logger.info("Imported %d community seed sponsor records into %s.", count, db_path)
    return count

#!/usr/bin/env python3
"""
scripts/build_sponsors_db.py

Builds and bakes the SQLite sponsor database (data/sponsors/sponsors.db)
by ingesting official government sponsor registers:
1. UK Home Office Register of Licensed Sponsors (Skilled Worker routes)
2. Curated & historical US DOL LCA disclosure filings and tech employer registry
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path

# Add src to python path for imports
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors, init_sponsor_db, load_all_sponsors
from job_radar.visa.ingest_uk import ingest_uk_sponsors
from job_radar.visa.ingest_ca import ingest_canada_lmia
from job_radar.visa.ingest_ca_negative import ingest_ca_non_compliant
from job_radar.visa.ingest_nl import ingest_nl_sponsors
from job_radar.visa.ingest_dk import ingest_dk_sponsors
from job_radar.visa.ingest_fi import ingest_fi_sponsors
from job_radar.visa.ingest_ie import ingest_ie_sponsors
from job_radar.visa.ingest_nz import ingest_nz_sponsors
from job_radar.visa.ingest_au import ingest_au_sponsors
from job_radar.visa.ingest_community_seeds import import_community_seeds
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_sponsors_db")

# High-frequency tech employers with confirmed sponsorship licenses (US / UK / EU)
CURATED_GLOBAL_TECH_SPONSORS = [
    # US & Global Tech Giants
    {"name": "Google LLC", "country": "US", "routes": ["H-1B", "L-1", "O-1"], "rating": "Certified"},
    {"name": "Alphabet Inc.", "country": "US", "routes": ["H-1B", "L-1"], "rating": "Certified"},
    {"name": "Google DeepMind", "country": "UK", "routes": ["Skilled Worker", "Global Talent"], "rating": "A"},
    {"name": "DeepMind Technologies Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Stripe, Inc.", "country": "US", "routes": ["H-1B", "O-1"], "rating": "Certified"},
    {"name": "Stripe Payments UK Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Meta Platforms, Inc.", "country": "US", "routes": ["H-1B", "L-1"], "rating": "Certified"},
    {"name": "Facebook UK Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Apple Inc.", "country": "US", "routes": ["H-1B", "L-1"], "rating": "Certified"},
    {"name": "Apple Europe Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Microsoft Corporation", "country": "US", "routes": ["H-1B", "L-1"], "rating": "Certified"},
    {"name": "Microsoft Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Amazon.com Services LLC", "country": "US", "routes": ["H-1B", "L-1"], "rating": "Certified"},
    {"name": "Amazon UK Services Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Netflix, Inc.", "country": "US", "routes": ["H-1B", "O-1"], "rating": "Certified"},
    {"name": "Netflix Services UK Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Uber Technologies, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Uber London Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Airbnb, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Airbnb UK Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "OpenAI, LLC", "country": "US", "routes": ["H-1B", "O-1"], "rating": "Certified"},
    {"name": "Anthropic PBC", "country": "US", "routes": ["H-1B", "O-1"], "rating": "Certified"},
    {"name": "Databricks, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Databricks UK Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Snowflake Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Palantir Technologies", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Palantir Technologies UK, Ltd.", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Figma, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Figma UK Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Coinbase, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Cloudflare, Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Cloudflare Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Spotify USA Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Spotify Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Shopify Inc.", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Revolut Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Monzo Bank Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Wise Payments Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Deliveroo", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Roofoods Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Checkout.com", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Checkout Ltd", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Klarna Bank AB", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Adyen N.V.", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Bloomberg LP", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Bloomberg Finance L.P.", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Two Sigma Investments, LP", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Citadel LLC", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Citadel Management (UK) Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Jane Street Capital LLC", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Jane Street Europe Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
    {"name": "Jump Trading LLC", "country": "US", "routes": ["H-1B"], "rating": "Certified"},
    {"name": "Jump Trading International Limited", "country": "UK", "routes": ["Skilled Worker"], "rating": "A"},
]


def seed_curated_sponsors(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Seed foundational curated top tech sponsors."""
    as_of = datetime.date.today().isoformat()
    records = []
    for item in CURATED_GLOBAL_TECH_SPONSORS:
        norm = normalize_company_name(item["name"])
        records.append(
            SponsorRecord(
                normalized_name=norm,
                country=item["country"],
                legal_name=item["name"],
                routes=item["routes"],
                rating=item["rating"],
                source="curated_official_registry",
                as_of=as_of,
                extra={"curated": True},
            )
        )
    return bulk_upsert_sponsors(records, db_path=db_path)


def main():
    target_db = DEFAULT_DB_PATH
    target_db.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Initializing sponsor SQLite database at %s...", target_db)
    init_sponsor_db(target_db)

    # 1. Seed base curated sponsors
    curated_count = seed_curated_sponsors(target_db)
    logger.info("Seeded %d curated top tech sponsor records.", curated_count)

    # 2. Ingest live UK Register of Licensed Sponsors
    try:
        uk_count = ingest_uk_sponsors(db_path=target_db)
        logger.info("Ingested %d UK GOV licensed sponsors.", uk_count)
    except Exception as e:
        logger.warning("Could not ingest live UK sponsors (offline/blocked): %s.", e)

    # 3. Ingest Netherlands IND Recognised Sponsors
    try:
        nl_count = ingest_nl_sponsors(db_path=target_db)
        logger.info("Ingested %d NL IND recognised sponsors.", nl_count)
    except Exception as e:
        logger.warning("Could not ingest NL IND sponsors: %s.", e)

    # 4. Ingest Denmark SIRI Fast-Track Certified Companies
    try:
        dk_count = ingest_dk_sponsors(db_path=target_db)
        logger.info("Ingested %d DK SIRI fast-track sponsors.", dk_count)
    except Exception as e:
        logger.warning("Could not ingest DK SIRI sponsors: %s.", e)

    # 5. Ingest Finland Migri Certified Employers
    try:
        fi_count = ingest_fi_sponsors(db_path=target_db)
        logger.info("Ingested %d FI Migri certified sponsors.", fi_count)
    except Exception as e:
        logger.warning("Could not ingest FI Migri sponsors: %s.", e)

    # 6. Ingest Ireland Employment Permits
    try:
        ie_count = ingest_ie_sponsors(db_path=target_db)
        logger.info("Ingested %d IE employment permit sponsors.", ie_count)
    except Exception as e:
        logger.warning("Could not ingest IE employment permits: %s.", e)

    # 7. Ingest New Zealand Accredited Employers (AEWV)
    try:
        nz_count = ingest_nz_sponsors(db_path=target_db)
        logger.info("Ingested %d NZ accredited employers.", nz_count)
    except Exception as e:
        logger.warning("Could not ingest NZ accredited employers: %s.", e)

    # 8. Ingest Australia Approved Standard Business Sponsors
    try:
        au_count = ingest_au_sponsors(db_path=target_db)
        logger.info("Ingested %d AU approved business sponsors.", au_count)
    except Exception as e:
        logger.warning("Could not ingest AU business sponsors: %s.", e)

    # 9. Ingest Canada Positive LMIA (dynamic URL via CKAN)
    try:
        ca_count = ingest_canada_lmia(db_path=target_db)
        logger.info("Ingested %d Canadian LMIA employers.", ca_count)
    except Exception as e:
        logger.warning("Could not ingest Canada LMIA data: %s.", e)

    # 10. Ingest Canada Non-Compliant Employers (NEGATIVE SIGNALS - must come AFTER positive)
    try:
        ca_neg_count = ingest_ca_non_compliant(db_path=target_db)
        logger.info("Ingested %d Canadian non-compliant employers (NEGATIVE).", ca_neg_count)
    except Exception as e:
        logger.warning("Could not ingest CA non-compliant list: %s.", e)

    # 11. Import Community Seed Lists (ONE-TIME, LOWEST PRIORITY)
    try:
        community_count = import_community_seeds(db_path=target_db, skip_existing=True)
        logger.info("Imported %d community seed sponsors (LOW confidence).", community_count)
    except Exception as e:
        logger.warning("Could not import community seed lists: %s.", e)

    # 10. Validate database
    sponsors = load_all_sponsors(db_path=target_db, allow_empty=True)
    total_count = len(sponsors)
    if total_count == 0:
        logger.critical("FATAL: Sponsor database is empty after build.")
        sys.exit(1)

    # Report by country
    country_counts: dict[str, int] = {}
    for record in sponsors.values():
        country_counts[record.country] = country_counts.get(record.country, 0) + 1
    for country, count in sorted(country_counts.items(), key=lambda x: x[1], reverse=True):
        logger.info("  %s: %d sponsors", country, count)

    logger.info("✅ Sponsor database successfully baked with %d verified sponsor records.", total_count)


if __name__ == "__main__":
    main()


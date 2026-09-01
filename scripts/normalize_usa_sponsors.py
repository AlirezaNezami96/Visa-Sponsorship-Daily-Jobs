#!/usr/bin/env python3
"""
scripts/normalize_usa_sponsors.py

Normalizes raw USA visa disclosure records from staging_usa_visa.db,
standardizes employer entities, deduplicates, aggregates filing counts,
and merges into the master sponsors database (data/sponsors/sponsors.db).
"""
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add src to path for normalizer
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_radar.visa.normalizer import normalize_company_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

STAGING_DB_PATH = ROOT_DIR / "data" / "sponsors" / "staging_usa_visa.db"
MASTER_SPONSORS_DB_PATH = ROOT_DIR / "data" / "sponsors" / "sponsors.db"


def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("none", "null", "nan", "n/a", "") else None


def clean_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        if isinstance(val, (int, float)):
            return int(val)
        s = str(val).replace(",", "").strip()
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0


def normalize_visa_class(visa_raw: Optional[str], filename: str) -> str:
    if visa_raw:
        v = visa_raw.upper().strip()
        if "H-1B1" in v or "CHILE" in v or "SINGAPORE" in v:
            return "H-1B1"
        if "H-1B" in v:
            return "H-1B"
        if "E-3" in v:
            return "E-3"
        if "PERM" in v or "PERMANENT" in v:
            return "PERM"
        if "H-2A" in v:
            return "H-2A"
        if "H-2B" in v:
            return "H-2B"
        if "CW-1" in v:
            return "CW-1"
        if "L-1" in v:
            return "L-1"
        if "O-1" in v:
            return "O-1"

    fname_upper = filename.upper()
    if "PERM" in fname_upper:
        return "PERM"
    if "LCA" in fname_upper:
        return "H-1B"
    if "H-2A" in fname_upper:
        return "H-2A"
    if "H-2B" in fname_upper:
        return "H-2B"
    if "CW-1" in fname_upper:
        return "CW-1"
    if "PW_" in fname_upper:
        return "Prevailing Wage"
    return "US Visa"


def is_certified_status(status_raw: Optional[str]) -> bool:
    if not status_raw:
        return True  # default to positive if status omitted in addenda/recruiter lists
    s = status_raw.upper().strip()
    return any(term in s for term in ("CERTIFIED", "APPROVED", "DETERMINATION ISSUED", "FINAL"))


GENERIC_PLACEHOLDERS = {
    "unknown", "none", "null", "n a", "na", "tbd", "various", "various employers",
    "unspecified", "tba", "confidential", "undisclosed", "anonymous", "test", "demo"
}


def run_normalization():
    if not STAGING_DB_PATH.exists():
        logger.error("Staging database not found at %s", STAGING_DB_PATH)
        return

    logger.info("Connecting to staging DB: %s", STAGING_DB_PATH)
    staging_conn = sqlite3.connect(str(STAGING_DB_PATH))
    staging_conn.row_factory = sqlite3.Row
    s_cursor = staging_conn.cursor()

    # Get source file map
    s_cursor.execute("SELECT id, filename, publisher FROM source_files")
    file_map = {row["id"]: (row["filename"], row["publisher"]) for row in s_cursor.fetchall()}

    # Check total rows
    s_cursor.execute("SELECT count(*) FROM raw_records")
    total_raw_rows = s_cursor.fetchone()[0]
    logger.info("Found %d total raw records in staging database.", total_raw_rows)

    rows_extracted = total_raw_rows
    rows_normalized = 0
    rows_skipped = 0
    errors = 0

    schema_issues: List[str] = []
    data_quality_issues: List[str] = []

    # Aggregated company store
    # key: normalized_name -> dict
    companies: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "legal_names": Counter(),
        "routes": set(),
        "certified_filings": 0,
        "total_filings": 0,
        "certified_positions": 0,
        "job_titles": Counter(),
        "soc_codes": Counter(),
        "cities": Counter(),
        "states": Counter(),
        "source_files": set(),
        "publishers": set(),
        "latest_decision_date": None,
    })

    logger.info("Streaming and parsing raw_records in batches...")
    s_cursor.execute("SELECT source_file_id, sheet_name, data FROM raw_records")

    batch_size = 50000
    processed_count = 0

    while True:
        rows = s_cursor.fetchmany(batch_size)
        if not rows:
            break

        for row in rows:
            file_id = row["source_file_id"]
            filename, publisher = file_map.get(file_id, ("unknown.xlsx", "US DOL OFLC"))
            
            try:
                data = json.loads(row["data"])
            except Exception as e:
                errors += 1
                continue

            # Extract employer name across various DOL schemas
            raw_emp_name = (
                data.get("employer_legal_business_name")
                or data.get("employer_name")
                or data.get("standardized_employer_name")
                or data.get("full_name")
                or data.get("trade_name_dba")
                or data.get("employer_poc_legal_business_name")
            )

            emp_name = clean_str(raw_emp_name)
            if not emp_name:
                rows_skipped += 1
                continue

            norm_name = normalize_company_name(emp_name)
            if not norm_name or len(norm_name) < 2 or norm_name in GENERIC_PLACEHOLDERS:
                rows_skipped += 1
                continue

            # Extract case status
            case_status = (
                data.get("case_status")
                or data.get("status")
                or data.get("determination")
            )
            certified = is_certified_status(case_status)

            # Extract visa class
            raw_visa = (
                data.get("visa_class")
                or data.get("visa_type")
                or data.get("program_type")
            )
            visa_route = normalize_visa_class(raw_visa, filename)

            # Extract worker positions
            positions = (
                clean_int(data.get("total_worker_positions"))
                or clean_int(data.get("nbr_workers_certified"))
                or clean_int(data.get("nbr_workers_requested"))
                or clean_int(data.get("total_workers"))
                or (1 if certified else 0)
            )

            # Extract job title / SOC
            job_title = clean_str(
                data.get("job_title")
                or data.get("pw_soc_title")
                or data.get("soc_title")
                or data.get("suggested_soc_title")
                or data.get("emp_soc_titles")
            )
            soc_code = clean_str(
                data.get("soc_code")
                or data.get("pw_soc_code")
                or data.get("emp_soc_codes")
            )

            # Location
            city = clean_str(
                data.get("employer_city")
                or data.get("primary_worksite_city")
                or data.get("worksite_city")
                or data.get("city")
            )
            state = clean_str(
                data.get("employer_state")
                or data.get("primary_worksite_state")
                or data.get("worksite_state")
                or data.get("state")
            )

            # Date
            decision_date = clean_str(
                data.get("decision_date")
                or data.get("determination_date")
                or data.get("received_date")
                or data.get("prevail_wage_determ_date")
            )

            # Aggregate
            comp = companies[norm_name]
            comp["legal_names"][emp_name] += 1
            if visa_route:
                comp["routes"].add(visa_route)
            comp["total_filings"] += 1
            if certified:
                comp["certified_filings"] += 1
                comp["certified_positions"] += positions

            if job_title:
                comp["job_titles"][job_title] += 1
            if soc_code:
                comp["soc_codes"][soc_code] += 1
            if city:
                comp["cities"][city] += 1
            if state and len(state) <= 4:
                comp["states"][state.upper()] += 1

            comp["source_files"].add(filename)
            comp["publishers"].add(publisher)

            if decision_date:
                if not comp["latest_decision_date"] or decision_date > comp["latest_decision_date"]:
                    comp["latest_decision_date"] = decision_date

            rows_normalized += 1

        processed_count += len(rows)
        if processed_count % 100000 == 0:
            logger.info("Processed %d / %d records...", processed_count, total_raw_rows)

    staging_conn.close()
    logger.info("Finished aggregation: %d distinct standardized employers identified.", len(companies))

    # Connect to Master Sponsors DB
    logger.info("Connecting to Master Sponsors DB: %s", MASTER_SPONSORS_DB_PATH)
    master_conn = sqlite3.connect(str(MASTER_SPONSORS_DB_PATH))
    master_conn.row_factory = sqlite3.Row
    m_cursor = master_conn.cursor()

    # Load existing sponsors
    m_cursor.execute("SELECT normalized_name, country, legal_name, routes_json, rating, source, extra_json FROM sponsors")
    existing_sponsors = {row["normalized_name"]: dict(row) for row in m_cursor.fetchall()}
    logger.info("Loaded %d existing sponsor records from master DB.", len(existing_sponsors))

    records_matched = 0
    records_updated = 0
    records_inserted = 0

    as_of_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for norm_name, comp in companies.items():
        # Pick most prominent legal name
        best_legal_name = comp["legal_names"].most_common(1)[0][0]
        
        # Determine rating
        if comp["certified_filings"] > 0:
            rating = "Certified"
        elif comp["total_filings"] > 0:
            rating = "Historical Filing"
        else:
            rating = "Registered"

        routes_list = sorted(list(comp["routes"]))
        top_titles = [t for t, _ in comp["job_titles"].most_common(10)]
        top_cities = [c for c, _ in comp["cities"].most_common(5)]
        top_states = [s for s, _ in comp["states"].most_common(5)]
        top_socs = [s for s, _ in comp["soc_codes"].most_common(5)]

        extra = {
            "certified_filings": comp["certified_filings"],
            "total_filings": comp["total_filings"],
            "certified_positions": comp["certified_positions"],
            "top_titles": top_titles,
            "top_socs": top_socs,
            "cities": top_cities,
            "states": top_states,
            "sources": sorted(list(comp["source_files"])),
            "latest_filing_date": comp["latest_decision_date"],
        }

        if norm_name in existing_sponsors:
            records_matched += 1
            existing = existing_sponsors[norm_name]
            
            # Merge routes
            try:
                existing_routes = set(json.loads(existing.get("routes_json") or "[]"))
            except Exception:
                existing_routes = set()
            merged_routes = sorted(list(existing_routes.union(comp["routes"])))

            # Merge extra
            try:
                existing_extra = json.loads(existing.get("extra_json") or "{}")
            except Exception:
                existing_extra = {}
            
            # If existing is already a multi-country company (e.g. UK/CA/NL), keep country or make multi-country note
            merged_extra = {**existing_extra, "us_filings_fy2026": extra}

            # Update master record
            m_cursor.execute(
                """
                UPDATE sponsors
                SET routes_json = ?,
                    extra_json = ?,
                    as_of = ?
                WHERE normalized_name = ?
                """,
                (
                    json.dumps(merged_routes),
                    json.dumps(merged_extra),
                    as_of_date,
                    norm_name,
                ),
            )
            records_updated += 1
        else:
            # Insert new record
            m_cursor.execute(
                """
                INSERT INTO sponsors (
                    normalized_name,
                    country,
                    legal_name,
                    routes_json,
                    rating,
                    source,
                    as_of,
                    extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm_name,
                    "US",
                    best_legal_name,
                    json.dumps(routes_list),
                    rating,
                    "US DOL OFLC Disclosure FY2026 Q3",
                    as_of_date,
                    json.dumps(extra),
                ),
            )
            records_inserted += 1

    master_conn.commit()
    master_conn.close()

    logger.info("Normalization & Database Upsert Completed Successfully!")
    logger.info("Summary Statistics:")
    logger.info("  Rows Extracted        : %d", rows_extracted)
    logger.info("  Rows Normalized       : %d", rows_normalized)
    logger.info("  Companies Matched     : %d", records_matched)
    logger.info("  Records Updated       : %d", records_updated)
    logger.info("  Records Inserted      : %d", records_inserted)
    logger.info("  Rows Skipped          : %d", rows_skipped)
    logger.info("  Errors                : %d", errors)

    return {
        "rows_extracted": rows_extracted,
        "rows_normalized": rows_normalized,
        "companies_matched": records_matched,
        "records_updated": records_updated,
        "records_inserted": records_inserted,
        "records_skipped": rows_skipped,
        "errors": errors,
        "schema_issues": schema_issues,
        "data_quality_issues": data_quality_issues,
    }


if __name__ == "__main__":
    run_normalization()

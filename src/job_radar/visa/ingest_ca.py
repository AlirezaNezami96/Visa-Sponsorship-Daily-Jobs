"""
src/job_radar/visa/ingest_ca.py

Ingests Canada Employment and Social Development Canada (ESDC) Positive LMIA disclosure data.
Aggregates employer approved positions count, primary NOC codes, and provinces.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

CKAN_LMIA_PACKAGE_ID = "90fed587-1364-4f33-a9ee-208181dc0b97"
CKAN_API_URL = f"https://open.canada.ca/data/api/3/action/package_show?id={CKAN_LMIA_PACKAGE_ID}"
CKAN_SEARCH_URL = "https://open.canada.ca/data/api/3/action/package_search?q=positive+lmia+employer&rows=3"


def _extract_csv_urls_from_package(package_data: dict, english_only: bool = True) -> List[str]:
    """Extract CSV URLs from a CKAN package result, optionally filtering for English."""
    resources = package_data.get("resources", [])
    csv_resources = [
        r for r in resources
        if r.get("format", "").upper() == "CSV"
        and r.get("url")
    ]
    if not csv_resources:
        return []

    urls = []
    for r in csv_resources:
        url = r["url"]
        if url.startswith("/"):
            url = f"https://open.canada.ca{url}"
        # Filter for English only (skip French '_fr' files)
        if english_only:
            url_lower = url.lower()
            # If there are _en variants, only include those; if no _en/_fr pattern, include all
            if "_fr" in url_lower or url_lower.endswith("_fr.csv"):
                continue
        urls.append(url)

    # Sort by URL to get most recent quarters first
    urls.sort(reverse=True)
    return urls


def resolve_lmia_csv_urls() -> List[str]:
    """
    Dynamically resolve Positive LMIA CSV URLs from Canada's
    open data CKAN API. Returns multiple quarterly English CSVs.
    """
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}

    # Strategy 1: Direct package lookup by ID
    try:
        resp = requests.get(CKAN_API_URL, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                urls = _extract_csv_urls_from_package(data.get("result", {}), english_only=True)
                if urls:
                    logger.info("Resolved %d LMIA CSV URLs via direct lookup.", len(urls))
                    return urls
    except Exception as e:
        logger.debug("Direct CKAN lookup failed: %s", e)

    # Strategy 2: Search-based discovery (fallback)
    try:
        resp = requests.get(CKAN_SEARCH_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            for result in data.get("result", {}).get("results", []):
                title = result.get("title", "")
                if isinstance(title, dict):
                    title = title.get("en", "")
                if "positive" in title.lower() and "lmia" in title.lower():
                    urls = _extract_csv_urls_from_package(result, english_only=True)
                    if urls:
                        logger.info("Resolved %d LMIA CSV URLs via search.", len(urls))
                        return urls
    except Exception as e:
        logger.warning("CKAN search fallback failed: %s", e)

    logger.warning("Could not resolve LMIA CSV URLs from CKAN API.")
    return []


def aggregate_lmia_records(rows: List[Dict[str, Any]], as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Aggregates Canadian ESDC Positive LMIA filing rows into SponsorRecord entries.
    """
    as_of = as_of_date or datetime.date.today().isoformat()
    employers: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "legal_name": "",
        "approved_positions": 0,
        "provinces": set(),
        "noc_titles": defaultdict(int),
        "streams": set(),
    })

    for row in rows:
        # Match case-insensitive keys
        row_norm = {k.strip().lower(): str(v).strip() for k, v in row.items() if k and v}

        raw_name = (
            row_norm.get("employer")
            or row_norm.get("employer_name")
            or row_norm.get("employer legal name")
            or row_norm.get("operating name")
            or ""
        )
        if not raw_name:
            continue

        norm = normalize_company_name(raw_name)
        if not norm:
            continue

        emp = employers[norm]
        if not emp["legal_name"] or len(raw_name) > len(emp["legal_name"]):
            emp["legal_name"] = raw_name

        # Approved positions count
        pos_str = row_norm.get("approved positions") or row_norm.get("approved_positions") or row_norm.get("positions") or "1"
        try:
            emp["approved_positions"] += int(float(pos_str))
        except ValueError:
            emp["approved_positions"] += 1

        # Province
        prov = row_norm.get("province") or row_norm.get("province/territory") or row_norm.get("location")
        if prov:
            emp["provinces"].add(prov.upper())

        # Stream
        stream = row_norm.get("stream") or row_norm.get("program stream") or "TFWP - High Wage"
        emp["streams"].add(stream)

        # NOC Title
        noc = row_norm.get("occupation") or row_norm.get("noc title") or row_norm.get("noc")
        if noc:
            emp["noc_titles"][noc] += 1

    records: List[SponsorRecord] = []
    for norm, data in employers.items():
        top_nocs = [t for t, _ in sorted(data["noc_titles"].items(), key=lambda x: x[1], reverse=True)[:5]]
        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="CA",
                legal_name=data["legal_name"],
                routes=list(data["streams"]) or ["Positive LMIA"],
                rating="Approved",
                source="esdc_lmia",
                as_of=as_of,
                extra={
                    "approved_positions": data["approved_positions"],
                    "provinces": list(data["provinces"]),
                    "top_noc_titles": top_nocs,
                },
            )
        )

    logger.info("Aggregated %d Canadian LMIA employers.", len(records))
    return records


def _parse_esdc_csv_rows(text: str) -> List[Dict[str, str]]:
    """Parse ESDC CSV text with automatic header row detection."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []

    header_idx = 0
    for i, r in enumerate(rows[:6]):
        cols = [c.strip().lower() for c in r if c.strip()]
        if len(cols) >= 3 and any("employer" in c or "province" in c or "business" in c for c in cols):
            header_idx = i
            break

    header = [c.strip() for c in rows[header_idx]]
    data_rows = []
    for r in rows[header_idx + 1:]:
        d = {}
        for idx, h in enumerate(header):
            if idx < len(r):
                d[h] = r[idx].strip()
        if any(d.values()):
            data_rows.append(d)
    return data_rows


def ingest_canada_lmia_csv(csv_path_or_url: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Ingest Canada ESDC Positive LMIA disclosure CSV into SQLite."""
    if csv_path_or_url.startswith("http://") or csv_path_or_url.startswith("https://"):
        resp = requests.get(csv_path_or_url, timeout=90, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text
    else:
        with open(csv_path_or_url, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    rows = _parse_esdc_csv_rows(text)
    records = aggregate_lmia_records(rows)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d Canadian LMIA employers into %s.", count, db_path)
    return count


def ingest_canada_lmia(db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    Convenience wrapper: dynamically resolve LMIA CSV URLs via CKAN API,
    then ingest multiple quarterly files and aggregate across all of them.
    """
    urls = resolve_lmia_csv_urls()
    if not urls:
        logger.warning("Could not resolve LMIA CSV URL. Canada LMIA ingestion skipped.")
        return 0

    # Download and aggregate across multiple quarterly CSVs
    all_rows: List[Dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    for url in urls[:8]:  # Process up to 8 most recent quarters
        try:
            resp = requests.get(url, headers=headers, timeout=90, allow_redirects=True)
            if resp.status_code != 200:
                continue
            batch = _parse_esdc_csv_rows(resp.text)
            all_rows.extend(batch)
            logger.debug("Fetched %d rows from %s", len(batch), url.split('/')[-1])
        except Exception as e:
            logger.debug("Failed to fetch LMIA CSV %s: %s", url, e)
            continue

    if not all_rows:
        logger.warning("No LMIA CSV data could be parsed.")
        return 0

    logger.info("Downloaded %d total LMIA rows from %d quarterly files.", len(all_rows), min(len(urls), 8))
    records = aggregate_lmia_records(all_rows)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d Canadian LMIA employers into %s.", count, db_path)
    return count


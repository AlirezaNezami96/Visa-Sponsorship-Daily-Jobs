"""
src/job_radar/visa/ingest_ca_negative.py

Ingests Canada's ESDC Non-Compliant Employers list as NEGATIVE sponsorship evidence.

Source: https://www.canada.ca/en/employment-social-development/services/foreign-workers/employer-compliance/employers-non-compliant.html

These are force-override negative signals: if a company matches a non-compliant
record, it must suppress any positive Canada sponsorship evidence.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

IRCC_NON_COMPLIANT_JSON_URL = (
    "https://www.canada.ca/content/dam/ircc/documents/json/non_compliant.json"
)
IRCC_NON_COMPLIANT_HTML_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "work-canada/employers-non-compliant.html"
)
ESDC_NON_COMPLIANT_URL = IRCC_NON_COMPLIANT_HTML_URL
CKAN_NEGATIVE_PACKAGE_ID = "f82f66f2-a22b-4511-bccf-e1d74db39ae5"
CKAN_NEGATIVE_API_URL = f"https://open.canada.ca/data/api/3/action/package_show?id={CKAN_NEGATIVE_PACKAGE_ID}"


def _resolve_negative_csv_urls() -> List[str]:
    """Resolve negative LMIA CSV URLs from CKAN (multiple quarterly files)."""
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    try:
        resp = requests.get(CKAN_NEGATIVE_API_URL, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data.get("success"):
            return []

        resources = data.get("result", {}).get("resources", [])
        # Get English CSV resources only (filter out French '_fr')
        csv_urls = []
        for r in resources:
            if r.get("format", "").upper() != "CSV":
                continue
            url = r.get("url", "")
            if not url:
                continue
            # Skip French translations
            if "_fr" in url.lower() or url.lower().endswith("_fr.csv"):
                continue
            if url.startswith("/"):
                url = f"https://open.canada.ca{url}"
            csv_urls.append(url)

        # Sort by URL name to get latest quarters first
        csv_urls.sort(reverse=True)
        return csv_urls
    except Exception as e:
        logger.debug("Failed to resolve negative LMIA CSVs from CKAN: %s", e)
        return []


def _parse_negative_lmia_csv(csv_content: str, as_of: str) -> List[SponsorRecord]:
    """Parse a negative LMIA CSV file into SponsorRecords with robust header detection."""
    records = []
    seen_norms = set()

    reader = csv.reader(io.StringIO(csv_content))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []

    header_idx = 0
    for i, r in enumerate(rows[:6]):
        cols = [c.strip().lower() for c in r if c.strip()]
        if len(cols) >= 3 and any("employer" in c or "province" in c or "business" in c for c in cols):
            header_idx = i
            break

    header = [c.strip().lower() for c in rows[header_idx]]
    col_name = -1
    col_prov = -1
    col_city = -1

    for idx, h in enumerate(header):
        if h in ("employer", "employer name", "business name", "operating name", "legal name") or (
            "employer" in h and "occupations" not in h
        ):
            col_name = idx
        elif "province" in h:
            col_prov = idx
        elif "address" in h or "location" in h or "city" in h:
            col_city = idx

    if col_name == -1:
        col_name = 0

    for r in rows[header_idx + 1:]:
        if len(r) <= col_name:
            continue
        legal_name = r[col_name].strip()
        if not legal_name or len(legal_name) < 2:
            continue

        province = r[col_prov].strip() if col_prov >= 0 and len(r) > col_prov else ""
        city = r[col_city].strip() if col_city >= 0 and len(r) > col_city else ""

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="CA",
                legal_name=legal_name,
                routes=[],
                rating="NON_COMPLIANT",
                source="esdc_negative_lmia",
                as_of=as_of,
                confidence_tier="negative",
                extra={
                    "compliance_status": "negative_lmia",
                    "negative_signal": True,
                    "province": province,
                    "city": city,
                },
            )
        )

    return records


def _parse_non_compliant_json(json_data: Any, as_of: str) -> List[SponsorRecord]:
    """Parse official IRCC non-compliant JSON data feed."""
    items = []
    if isinstance(json_data, dict):
        items = json_data.get("list", [])
    elif isinstance(json_data, list):
        items = json_data

    records = []
    seen_norms = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("bn_operating") or item.get("bn_legal") or "").strip()
        if not name or len(name) < 2:
            continue

        norm = normalize_company_name(name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="CA",
                legal_name=item.get("bn_legal") or name,
                routes=[],
                rating="NON_COMPLIANT",
                source="ircc_non_compliant",
                as_of=as_of,
                confidence_tier="negative",
                extra={
                    "compliance_status": "non_compliant",
                    "negative_signal": True,
                    "penalty": item.get("penalty_en", ""),
                    "decision_date": item.get("date", ""),
                    "status": item.get("status_en", ""),
                },
            )
        )

    return records


def parse_non_compliant_html(html_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse the ESDC/IRCC non-compliant employers page from HTML table.
    Used as fallback when JSON feed is unavailable.
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    soup = BeautifulSoup(html_content, "html.parser")

    seen_norms = set()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [cell.get_text(strip=True).lower() for cell in header_cells]

        col_name = -1
        col_province = -1
        col_consequence = -1
        col_date = -1

        for idx, text in enumerate(header_texts):
            if any(k in text for k in ("employer", "business", "company", "name")):
                col_name = idx
            elif any(k in text for k in ("province", "territory", "location")):
                col_province = idx
            elif any(k in text for k in ("consequence", "penalty", "sanction", "action")):
                col_consequence = idx
            elif any(k in text for k in ("date", "effective")):
                col_date = idx

        if col_name == -1:
            col_name = 0

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= col_name:
                continue

            legal_name = cells[col_name].get_text(strip=True)
            if not legal_name or len(legal_name) < 2:
                continue

            province = ""
            if col_province >= 0 and len(cells) > col_province:
                province = cells[col_province].get_text(strip=True)

            consequence = ""
            if col_consequence >= 0 and len(cells) > col_consequence:
                consequence = cells[col_consequence].get_text(strip=True)

            effective_date = ""
            if col_date >= 0 and len(cells) > col_date:
                effective_date = cells[col_date].get_text(strip=True)

            norm = normalize_company_name(legal_name)
            if not norm or norm in seen_norms:
                continue
            seen_norms.add(norm)

            records.append(
                SponsorRecord(
                    normalized_name=norm,
                    country="CA",
                    legal_name=legal_name,
                    routes=[],
                    rating="NON_COMPLIANT",
                    source="esdc_non_compliant",
                    as_of=as_of,
                    confidence_tier="negative",
                    extra={
                        "compliance_status": "non_compliant",
                        "negative_signal": True,
                        "province": province,
                        "consequence": consequence,
                        "effective_date": effective_date,
                    },
                )
            )

    logger.info("Parsed %d CA non-compliant employer records from HTML.", len(records))
    return records


def ingest_ca_non_compliant(
    source_path_or_url: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Download and ingest Canada non-compliant employers as NEGATIVE evidence into SQLite."""
    all_records: List[SponsorRecord] = []
    as_of = datetime.date.today().isoformat()
    seen_norms = set()
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}

    # Strategy 1: Official IRCC JSON data feed
    if not source_path_or_url:
        try:
            resp = requests.get(IRCC_NON_COMPLIANT_JSON_URL, headers=headers, timeout=30)
            if resp.status_code == 200:
                json_records = _parse_non_compliant_json(resp.json(), as_of)
                for r in json_records:
                    if r.normalized_name not in seen_norms:
                        seen_norms.add(r.normalized_name)
                        all_records.append(r)
                logger.info("Fetched %d non-compliant records from IRCC JSON feed.", len(json_records))
        except Exception as e:
            logger.debug("Failed to fetch IRCC non-compliant JSON: %s", e)

    # Strategy 2: CKAN negative LMIA dataset (CSV files)
    if not source_path_or_url:
        csv_urls = _resolve_negative_csv_urls()
        if csv_urls:
            logger.info("Found %d negative LMIA CSV files from CKAN.", len(csv_urls))
            for url in csv_urls[:6]:  # Process up to 6 most recent quarters
                try:
                    resp = requests.get(url, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        batch = _parse_negative_lmia_csv(resp.text, as_of)
                        for r in batch:
                            if r.normalized_name not in seen_norms:
                                seen_norms.add(r.normalized_name)
                                all_records.append(r)
                except Exception as e:
                    logger.debug("Failed to fetch negative LMIA CSV %s: %s", url, e)
                    continue

    # Strategy 3: HTML page scraping (fallback if explicit source or no records)
    if source_path_or_url or not all_records:
        url = source_path_or_url or IRCC_NON_COMPLIANT_HTML_URL
        if url.startswith("http://") or url.startswith("https://"):
            logger.info("Downloading CA non-compliant employers from %s...", url)
            try:
                resp = requests.get(url, headers=headers, timeout=60)
                resp.raise_for_status()
                html_content = resp.text
            except Exception as e:
                logger.warning("Could not fetch CA non-compliant page: %s", e)
                html_content = ""
        else:
            with open(url, "r", encoding="utf-8", errors="ignore") as f:
                html_content = f.read()

        if html_content:
            records = parse_non_compliant_html(html_content)
            for r in records:
                if r.normalized_name not in seen_norms:
                    seen_norms.add(r.normalized_name)
                    all_records.append(r)

    count = bulk_upsert_sponsors(all_records, db_path=db_path)
    logger.info("Upserted %d CA non-compliant employers (NEGATIVE) into %s.", count, db_path)
    return count



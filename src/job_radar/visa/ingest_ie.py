"""
src/job_radar/visa/ingest_ie.py

Ingests Ireland Employment Permits data from Enterprise Ireland / DETE.

Source: https://enterprise.gov.ie/ employment permits XLSX
The URL contains the year, e.g., /2026/. Implements year-forward resolution:
tries current year, falls back to previous year if 404.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

# Template URL patterns — the year portion is resolved dynamically
IE_PERMITS_STATS_URL = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-{year}.html"
IE_PERMITS_XLSX_URL = "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-{year}.xlsx"


def resolve_ie_permits_url(year: Optional[int] = None) -> Optional[str]:
    """
    Resolve the latest available Irish employment permits XLSX URL.
    Tries current year first, falls back to previous year(s).
    """
    current_year = year or datetime.date.today().year
    years_to_try = [current_year, current_year - 1, current_year - 2]
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}

    for yr in years_to_try:
        # 1. Try direct XLSX download URL
        url = IE_PERMITS_XLSX_URL.format(year=yr)
        try:
            resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                logger.info("Found IE permits XLSX for %d: %s", yr, url)
                return url
        except Exception:
            pass

        # 2. Try stats page and scrape for download links
        page_url = IE_PERMITS_STATS_URL.format(year=yr)
        try:
            resp = requests.head(page_url, headers=headers, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                xlsx_url = find_ie_xlsx_download(page_url)
                if xlsx_url:
                    return xlsx_url
        except Exception:
            pass

    logger.warning("Could not resolve IE employment permits URL for years %s.", years_to_try)
    return None


def find_ie_xlsx_download(page_url: str) -> Optional[str]:
    """Scrape the resolved page for a downloadable XLSX/CSV link, prioritizing company lists."""
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    try:
        resp = requests.get(page_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            if any(ext in href.lower() for ext in (".xlsx", ".xls", ".csv")):
                if href.startswith("http"):
                    full_url = href
                elif href.startswith("/"):
                    full_url = f"https://enterprise.gov.ie{href}"
                else:
                    base = page_url.rsplit("/", 1)[0]
                    full_url = f"{base}/{href}"
                links.append((full_url, text, href.lower()))

        # Prioritize company listings
        for full_url, text, href_l in links:
            if any(k in text or k in href_l for k in ("company", "companies", "employer")):
                return full_url

        if links:
            return links[0][0]
    except Exception as e:
        logger.warning("Error finding IE permits download: %s", e)

    return None


def parse_ie_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse CSV text of Irish employment permits data.

    Expected columns may include:
      Company Name, Permit Type, Nationality, Sector, County
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    col_name = 0
    col_type = -1
    col_sector = -1
    col_county = -1
    col_total = -1  # Grand Total column from XLSX

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if any(k in c for k in ("company", "employer", "organisation", "organization")):
            col_name = idx
        elif any(k in c for k in ("permit type", "type of permit")):
            col_type = idx
        elif any(k in c for k in ("sector", "industry", "nace")):
            col_sector = idx
        elif any(k in c for k in ("county", "location", "region")):
            col_county = idx
        elif "grand total" in c or (c == "total"):
            col_total = idx

    # Aggregate by employer (multiple permits per employer)
    employers: Dict[str, Dict[str, Any]] = {}
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name or len(legal_name) < 2:
            continue

        permit_type = row[col_type].strip() if col_type >= 0 and len(row) > col_type else ""
        sector = row[col_sector].strip() if col_sector >= 0 and len(row) > col_sector else ""
        county = row[col_county].strip() if col_county >= 0 and len(row) > col_county else ""

        norm = normalize_company_name(legal_name)
        if not norm:
            continue

        if norm not in employers:
            employers[norm] = {
                "legal_name": legal_name,
                "permit_types": set(),
                "sectors": set(),
                "county": county,
                "permit_count": 0,
            }

        emp = employers[norm]
        # Use Grand Total column if available, otherwise count rows
        if col_total >= 0 and len(row) > col_total:
            try:
                total_str = row[col_total].strip()
                if total_str:
                    emp["permit_count"] += int(float(total_str))
                else:
                    emp["permit_count"] += 1
            except (ValueError, TypeError):
                emp["permit_count"] += 1
        else:
            emp["permit_count"] += 1
        if permit_type:
            emp["permit_types"].add(permit_type)
        if sector:
            emp["sectors"].add(sector)
        if not emp["legal_name"] or len(legal_name) > len(emp["legal_name"]):
            emp["legal_name"] = legal_name

    for norm, data in employers.items():
        permit_types = list(data["permit_types"])
        routes = []
        for pt in permit_types:
            pt_lower = pt.lower()
            if "critical" in pt_lower:
                routes.append("Critical Skills Employment Permit")
            elif "general" in pt_lower:
                routes.append("General Employment Permit")
            elif "intra" in pt_lower:
                routes.append("Intra-Company Transfer")
            else:
                routes.append(pt)
        if not routes:
            routes = ["Employment Permit"]

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="IE",
                legal_name=data["legal_name"],
                routes=routes,
                rating="Granted",
                source="enterprise_gov_ie_permits",
                as_of=as_of,
                extra={
                    "permit_count": data["permit_count"],
                    "permit_types": permit_types,
                    "sectors": list(data["sectors"]),
                    "county": data["county"],
                },
            )
        )

    logger.info("Parsed %d IE employment permit employers.", len(records))
    return records


def ingest_ie_sponsors(csv_path_or_url: Optional[str] = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Ireland employment permit data into SQLite."""
    url = csv_path_or_url
    if not url:
        url = resolve_ie_permits_url()

    if not url:
        logger.warning("No IE employment permits data URL found. Ingestion skipped.")
        return 0

    csv_text = ""
    if url.startswith("http://") or url.startswith("https://"):
        logger.info("Downloading IE employment permits from %s...", url)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()

        if url.endswith(".xlsx") or url.endswith(".xls"):
            # Convert XLSX to CSV-like records using openpyxl
            try:
                import openpyxl
                from io import BytesIO
                wb = openpyxl.load_workbook(BytesIO(resp.content), read_only=True)
                ws = wb.active
                rows_list = list(ws.iter_rows(values_only=True))
                wb.close()

                if not rows_list:
                    return 0

                output = io.StringIO()
                writer = csv.writer(output)
                for row in rows_list:
                    writer.writerow([str(cell) if cell is not None else "" for cell in row])
                csv_text = output.getvalue()
            except ImportError:
                logger.warning("openpyxl not installed; cannot parse XLSX. Install with: pip install openpyxl")
                return 0
        else:
            csv_text = resp.text
    else:
        with open(url, "r", encoding="utf-8", errors="ignore") as f:
            csv_text = f.read()

    records = parse_ie_csv_stream(csv_text)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d IE sponsors into %s.", count, db_path)
    return count

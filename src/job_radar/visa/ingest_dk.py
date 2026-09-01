"""
src/job_radar/visa/ingest_dk.py

Ingests the Denmark SIRI (Danish Agency for International Recruitment and Integration)
Fast-Track certified employer list.

Source: https://nyidanmark.dk/ (fast-track scheme companies)
CVR number (Central Business Register) is the primary identity key for Danish employers.
"""
from __future__ import annotations

import csv
import datetime
import io
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

SIRI_FASTTRACK_URL = "https://nyidanmark.dk/en-GB/You-want-to-apply/Work/Fast-track"
SIRI_CERTIFIED_URL = "https://nyidanmark.dk/en-GB/Words-and-concepts/SIRI/Certified-companies/"


def find_siri_download_url(page_url: str = SIRI_FASTTRACK_URL) -> Optional[str]:
    """Attempt to find a downloadable data file from the SIRI fast-track page."""
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    try:
        resp = requests.get(page_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning("Failed to fetch SIRI fast-track page (%d)", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        # Look for CSV/XLSX/PDF download links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(ext in href.lower() for ext in (".csv", ".xlsx", ".xls", ".pdf")):
                if href.startswith("http"):
                    return href
                return f"https://nyidanmark.dk{href}"
    except Exception as e:
        logger.warning("Error finding SIRI download link: %s", e)

    return None


def parse_siri_html_table(html_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse SIRI fast-track company list from HTML table on the page.
    Falls back to this when no downloadable file is available.

    Expected table columns: Company Name, CVR Number, (sometimes) Address
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    soup = BeautifulSoup(html_content, "html.parser")

    # Find tables that likely contain company data
    seen_norms = set()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Try to parse header
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [cell.get_text(strip=True).lower() for cell in header_cells]

        col_name = -1
        col_cvr = -1
        col_city = -1

        for idx, text in enumerate(header_texts):
            if any(k in text for k in ("company", "virksomhed", "name", "navn")):
                col_name = idx
            elif any(k in text for k in ("cvr", "business register", "registration")):
                col_cvr = idx
            elif any(k in text for k in ("city", "by", "address", "adresse")):
                col_city = idx

        # If we couldn't identify columns from header, assume first=name, second=CVR
        if col_name == -1:
            col_name = 0
        if col_cvr == -1 and len(header_texts) > 1:
            col_cvr = 1

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= col_name:
                continue

            legal_name = cells[col_name].get_text(strip=True)
            if not legal_name or len(legal_name) < 2:
                continue

            cvr = ""
            if col_cvr >= 0 and len(cells) > col_cvr:
                cvr_raw = cells[col_cvr].get_text(strip=True)
                # Extract numeric CVR (8 digits)
                cvr_match = re.search(r"\d{6,8}", cvr_raw)
                cvr = cvr_match.group(0) if cvr_match else cvr_raw

            city = ""
            if col_city >= 0 and len(cells) > col_city:
                city = cells[col_city].get_text(strip=True)

            norm = normalize_company_name(legal_name)
            if not norm or norm in seen_norms:
                continue
            seen_norms.add(norm)

            records.append(
                SponsorRecord(
                    normalized_name=norm,
                    country="DK",
                    legal_name=legal_name,
                    routes=["Fast-track (Skilled Worker)"],
                    rating="Certified",
                    source="siri_fasttrack",
                    as_of=as_of,
                    extra={
                        "cvr_number": cvr,
                        "city": city,
                    },
                )
            )

    logger.info("Parsed %d DK SIRI fast-track certified sponsors.", len(records))
    return records


def parse_dk_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """Parse CSV text of Danish SIRI fast-track certified companies."""
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    col_name = 0
    col_cvr = -1
    col_city = -1

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if any(k in c for k in ("company", "virksomhed", "name", "navn")):
            col_name = idx
        elif any(k in c for k in ("cvr", "business register")):
            col_cvr = idx
        elif any(k in c for k in ("city", "by")):
            col_city = idx

    seen_norms = set()
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        cvr = row[col_cvr].strip() if col_cvr >= 0 and len(row) > col_cvr else ""
        city = row[col_city].strip() if col_city >= 0 and len(row) > col_city else ""

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="DK",
                legal_name=legal_name,
                routes=["Fast-track (Skilled Worker)"],
                rating="Certified",
                source="siri_fasttrack",
                as_of=as_of,
                extra={
                    "cvr_number": cvr,
                    "city": city,
                },
            )
        )

    logger.info("Parsed %d DK SIRI fast-track sponsors from CSV.", len(records))
    return records


def ingest_dk_sponsors(source_path_or_url: Optional[str] = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Denmark SIRI fast-track sponsors into SQLite."""
    # Try the dedicated certified companies page first (has the actual table)
    urls_to_try = []
    if source_path_or_url:
        urls_to_try = [source_path_or_url]
    else:
        urls_to_try = [SIRI_CERTIFIED_URL, SIRI_FASTTRACK_URL]

    for url in urls_to_try:
        if url.startswith("http://") or url.startswith("https://"):
            logger.info("Downloading DK SIRI fast-track data from %s...", url)
            headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
            try:
                resp = requests.get(url, headers=headers, timeout=60)
                resp.raise_for_status()
            except Exception as e:
                logger.warning("Could not fetch DK SIRI page %s: %s", url, e)
                continue

            content_type = resp.headers.get("Content-Type", "").lower()
            if "csv" in content_type or url.endswith(".csv"):
                records = parse_dk_csv_stream(resp.text)
            else:
                records = parse_siri_html_table(resp.text)
        else:
            with open(url, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if url.endswith(".csv"):
                records = parse_dk_csv_stream(content)
            else:
                records = parse_siri_html_table(content)

        if records:
            count = bulk_upsert_sponsors(records, db_path=db_path)
            logger.info("Upserted %d DK sponsors into %s.", count, db_path)
            return count

    logger.warning("Could not find DK SIRI certified companies from any source.")
    return 0

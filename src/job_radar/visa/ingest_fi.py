"""
src/job_radar/visa/ingest_fi.py

Ingests the Finland Migri (Finnish Immigration Service) Certified Employers list.

Source: https://migri.fi/en/certified-employers
Important: Respects expiry dates. Expired entries are kept with rating="Expired"
so the evaluator can show "was previously certified" caveats.
Caveat: Presence on the list does NOT equal open vacancies.
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

MIGRI_CERTIFIED_URL = "https://migri.fi/en/certified-employers"


def parse_migri_html(html_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse the Migri certified employers page (HTML table or list).

    Expected data: Employer name, Certification number, Validity period/Expiry date
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()
    today = datetime.date.today()

    soup = BeautifulSoup(html_content, "html.parser")

    seen_norms = set()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Parse header
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [cell.get_text(strip=True).lower() for cell in header_cells]

        col_name = -1
        col_cert = -1
        col_expiry = -1
        col_city = -1

        for idx, text in enumerate(header_texts):
            if any(k in text for k in ("employer", "company", "yritys", "name", "nimi")):
                col_name = idx
            elif any(k in text for k in ("certificate", "sertifikaatti", "certification", "number")):
                col_cert = idx
            elif any(k in text for k in ("expir", "valid", "voimassa", "end", "päättyy")):
                col_expiry = idx
            elif any(k in text for k in ("city", "kaupunki", "location")):
                col_city = idx

        if col_name == -1:
            col_name = 0

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= col_name:
                continue

            legal_name = cells[col_name].get_text(strip=True)
            if not legal_name or len(legal_name) < 2:
                continue

            cert_number = ""
            if col_cert >= 0 and len(cells) > col_cert:
                cert_number = cells[col_cert].get_text(strip=True)

            expiry_str = ""
            is_expired = False
            if col_expiry >= 0 and len(cells) > col_expiry:
                expiry_raw = cells[col_expiry].get_text(strip=True)
                # Try to parse date in various formats
                expiry_date = _parse_date(expiry_raw)
                if expiry_date:
                    expiry_str = expiry_date.isoformat()
                    is_expired = expiry_date < today
                else:
                    expiry_str = expiry_raw

            city = ""
            if col_city >= 0 and len(cells) > col_city:
                city = cells[col_city].get_text(strip=True)

            norm = normalize_company_name(legal_name)
            if not norm or norm in seen_norms:
                continue
            seen_norms.add(norm)

            # Keep expired entries but mark them
            rating = "Expired" if is_expired else "Certified"

            records.append(
                SponsorRecord(
                    normalized_name=norm,
                    country="FI",
                    legal_name=legal_name,
                    routes=["Specialist (D-visa)"],
                    rating=rating,
                    source="migri_certified",
                    as_of=as_of,
                    extra={
                        "certification_number": cert_number,
                        "expiry_date": expiry_str,
                        "is_expired": is_expired,
                        "city": city,
                        "caveat": "Presence on certified employer list does not equal open vacancies",
                    },
                )
            )

    logger.info("Parsed %d FI Migri certified employers (%d expired).",
                len(records), sum(1 for r in records if r.rating == "Expired"))
    return records


def parse_fi_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """Parse CSV format of Finnish Migri certified employers."""
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()
    today = datetime.date.today()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    col_name = 0
    col_cert = -1
    col_expiry = -1

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if any(k in c for k in ("employer", "company", "yritys", "name", "nimi")):
            col_name = idx
        elif any(k in c for k in ("certificate", "sertifikaatti", "number")):
            col_cert = idx
        elif any(k in c for k in ("expir", "valid", "end", "päättyy")):
            col_expiry = idx

    seen_norms = set()
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        cert_number = row[col_cert].strip() if col_cert >= 0 and len(row) > col_cert else ""

        expiry_str = ""
        is_expired = False
        if col_expiry >= 0 and len(row) > col_expiry:
            expiry_raw = row[col_expiry].strip()
            expiry_date = _parse_date(expiry_raw)
            if expiry_date:
                expiry_str = expiry_date.isoformat()
                is_expired = expiry_date < today
            else:
                expiry_str = expiry_raw

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        rating = "Expired" if is_expired else "Certified"

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="FI",
                legal_name=legal_name,
                routes=["Specialist (D-visa)"],
                rating=rating,
                source="migri_certified",
                as_of=as_of,
                extra={
                    "certification_number": cert_number,
                    "expiry_date": expiry_str,
                    "is_expired": is_expired,
                    "caveat": "Presence on certified employer list does not equal open vacancies",
                },
            )
        )

    logger.info("Parsed %d FI Migri certified sponsors from CSV.", len(records))
    return records


def _parse_date(date_str: str) -> Optional[datetime.date]:
    """Try to parse a date string in common European formats."""
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%y",
        "%Y%m%d",
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def ingest_fi_sponsors(source_path_or_url: Optional[str] = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Finland Migri certified employers into SQLite."""
    url = source_path_or_url or MIGRI_CERTIFIED_URL

    if url.startswith("http://") or url.startswith("https://"):
        logger.info("Downloading FI Migri certified employers from %s...", url)
        headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").lower()
        if "csv" in content_type or url.endswith(".csv"):
            records = parse_fi_csv_stream(resp.text)
        else:
            records = parse_migri_html(resp.text)
    else:
        with open(url, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if url.endswith(".csv"):
            records = parse_fi_csv_stream(content)
        else:
            records = parse_migri_html(content)

    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d FI sponsors into %s.", count, db_path)
    return count

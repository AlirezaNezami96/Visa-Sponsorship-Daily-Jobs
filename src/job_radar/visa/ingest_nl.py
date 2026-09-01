"""
src/job_radar/visa/ingest_nl.py

Ingests the Netherlands IND (Immigration and Naturalisation Service)
Recognised Sponsor Register.

Source: https://ind.nl/en/public-register-recognised-sponsors/
The register is published as a downloadable CSV/PDF.
KVK (Kamer van Koophandel) number is the primary identity key for Dutch employers.
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

IND_REGISTER_PAGE = "https://ind.nl/en/public-register-recognised-sponsors/"

# Sponsor types that indicate external hiring
HIRING_SPONSOR_TYPES = {
    "kennismigrant",
    "highly skilled migrant",
    "arbeid regulier",
    "regular labour",
    "european blue card",
    "research",
    "onderzoeker",
}


def find_ind_csv_url(page_url: str = IND_REGISTER_PAGE) -> Optional[str]:
    """Attempt to find the CSV/XLSX download link from the IND register page."""
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    try:
        resp = requests.get(page_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning("Failed to fetch IND register page (%d)", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(ext in href.lower() for ext in (".csv", ".xlsx", ".xls")):
                if href.startswith("http"):
                    return href
                return f"https://ind.nl{href}"
    except Exception as e:
        logger.warning("Error finding IND register download link: %s", e)

    return None


def parse_nl_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse the CSV text of the Netherlands IND Recognised Sponsors register.

    Expected columns may include:
      Organisation Name, KVK Number, Sponsor Type, City, Status
    Column names vary; we detect them dynamically.
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    # Detect column indices dynamically
    col_name = 0
    col_kvk = -1
    col_type = -1
    col_city = -1
    col_status = -1

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if any(k in c for k in ("organisation", "organization", "naam", "name", "bedrijfsnaam")):
            col_name = idx
        elif "kvk" in c or "kamer van koophandel" in c or "chamber" in c:
            col_kvk = idx
        elif any(k in c for k in ("type", "categorie", "category", "sponsor type")):
            col_type = idx
        elif any(k in c for k in ("city", "plaats", "vestigingsplaats", "town")):
            col_city = idx
        elif any(k in c for k in ("status", "actief")):
            col_status = idx

    seen_norms = set()
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        kvk = row[col_kvk].strip() if col_kvk >= 0 and len(row) > col_kvk else ""
        sponsor_type = row[col_type].strip() if col_type >= 0 and len(row) > col_type else ""
        city = row[col_city].strip() if col_city >= 0 and len(row) > col_city else ""
        status = row[col_status].strip() if col_status >= 0 and len(row) > col_status else ""

        # Skip if status indicates inactive/revoked (if status column exists)
        if status and any(neg in status.lower() for neg in ("revoked", "ingetrokken", "inactive")):
            continue

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        # Determine routes from sponsor type
        routes = []
        type_lower = sponsor_type.lower()
        if any(k in type_lower for k in ("kennismigrant", "highly skilled", "hsm")):
            routes.append("Kennismigrant (Highly Skilled Migrant)")
        if any(k in type_lower for k in ("blue card", "blauwe kaart")):
            routes.append("European Blue Card")
        if any(k in type_lower for k in ("research", "onderzoek")):
            routes.append("Research")
        if any(k in type_lower for k in ("regulier", "regular labour")):
            routes.append("Regular Labour")
        if not routes:
            routes = ["Kennismigrant (Highly Skilled Migrant)"]  # Default

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="NL",
                legal_name=legal_name,
                routes=routes,
                rating="Recognised",
                source="ind_recognised_register",
                as_of=as_of,
                extra={
                    "kvk_number": kvk,
                    "sponsor_type": sponsor_type,
                    "city": city,
                },
            )
        )

    logger.info("Parsed %d NL recognised sponsor records.", len(records))
    return records


IND_REGISTER_WORK_URL = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"


def parse_nl_html_table(html_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """Parse NL IND recognised sponsors from the HTML table on the work register page."""
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()
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
        col_kvk = -1
        col_city = -1

        for idx, text in enumerate(header_texts):
            if any(k in text for k in ("name", "naam", "organisation", "bedrijfsnaam")):
                col_name = idx
            elif any(k in text for k in ("kvk", "chamber", "kamer")):
                col_kvk = idx
            elif any(k in text for k in ("city", "plaats", "vestiging", "town")):
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

            kvk = ""
            if col_kvk >= 0 and len(cells) > col_kvk:
                kvk_raw = cells[col_kvk].get_text(strip=True)
                kvk_match = re.search(r"\d{6,8}", kvk_raw)
                kvk = kvk_match.group(0) if kvk_match else kvk_raw

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
                    country="NL",
                    legal_name=legal_name,
                    routes=["Kennismigrant (Highly Skilled Migrant)"],
                    rating="Recognised",
                    source="ind_recognised_register",
                    as_of=as_of,
                    extra={
                        "kvk_number": kvk,
                        "city": city,
                    },
                )
            )

    logger.info("Parsed %d NL IND recognised sponsors from HTML.", len(records))
    return records


def ingest_nl_sponsors(csv_path_or_url: Optional[str] = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Netherlands IND recognised sponsors into SQLite."""
    url = csv_path_or_url

    # Try to find a CSV download link first
    if not url:
        url = find_ind_csv_url()

    if url:
        csv_text = ""
        if url.startswith("http://") or url.startswith("https://"):
            logger.info("Downloading NL IND sponsors from %s...", url)
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            csv_text = resp.text
        else:
            with open(url, "r", encoding="utf-8", errors="ignore") as f:
                csv_text = f.read()

        records = parse_nl_csv_stream(csv_text)
        count = bulk_upsert_sponsors(records, db_path=db_path)
        logger.info("Upserted %d NL sponsors into %s.", count, db_path)
        return count

    # Fallback: scrape the HTML table directly from the work register page
    logger.info("No NL CSV found. Falling back to HTML table scraping from %s...", IND_REGISTER_WORK_URL)
    headers = {"User-Agent": "Mozilla/5.0 (VisaLane/1.0; +https://github.com)"}
    try:
        resp = requests.get(IND_REGISTER_WORK_URL, headers=headers, timeout=60)
        resp.raise_for_status()
        records = parse_nl_html_table(resp.text)
        if not records:
            logger.warning("No sponsors found in NL IND HTML table. Ingestion skipped.")
            return 0
        count = bulk_upsert_sponsors(records, db_path=db_path)
        logger.info("Upserted %d NL sponsors (HTML scrape) into %s.", count, db_path)
        return count
    except Exception as e:
        logger.warning("Could not scrape NL IND HTML table: %s", e)
        return 0


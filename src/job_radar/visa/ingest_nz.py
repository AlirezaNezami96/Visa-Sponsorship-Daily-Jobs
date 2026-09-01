"""
src/job_radar/visa/ingest_nz.py

Ingests Immigration New Zealand (INZ) Accredited Employer Register (AEWV).
Parses accredited employer legal names, trading names, NZBNs, and accreditation status.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from job_radar.visa.db import DEFAULT_DB_PATH, bulk_upsert_sponsors
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)


def parse_nz_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """Parse CSV text of Immigration New Zealand Accredited Employers."""
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    col_name = 0
    col_nzbn = 1
    col_trading = 2

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if "employer" in c or "legal name" in c or "organisation" in c:
            col_name = idx
        elif "nzbn" in c or "business number" in c:
            col_nzbn = idx
        elif "trading" in c or "trading name" in c:
            col_trading = idx

    seen_norms = set()
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        trading_name = row[col_trading].strip() if len(row) > col_trading else ""
        nzbn = row[col_nzbn].strip() if len(row) > col_nzbn else ""

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="NZ",
                legal_name=legal_name,
                routes=["AEWV (Accredited Employer Work Visa)"],
                rating="Accredited",
                source="inz_accredited_register",
                as_of=as_of,
                extra={"trading_name": trading_name, "nzbn": nzbn},
            )
        )

    logger.info("Parsed %d NZ accredited sponsor records.", len(records))
    return records


def ingest_nz_sponsors(csv_path_or_url: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Immigration New Zealand accredited employers into SQLite."""
    csv_text = ""
    if csv_path_or_url.startswith("http://") or csv_path_or_url.startswith("https://"):
        resp = requests.get(csv_path_or_url, timeout=60)
        resp.raise_for_status()
        csv_text = resp.text
    else:
        with open(csv_path_or_url, "r", encoding="utf-8", errors="ignore") as f:
            csv_text = f.read()

    records = parse_nz_csv_stream(csv_text)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d NZ accredited employers into %s.", count, db_path)
    return count

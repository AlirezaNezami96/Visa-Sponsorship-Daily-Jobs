"""
src/job_radar/visa/ingest_au.py

Ingests Australia Department of Home Affairs Standard Business Sponsors and Accredited Sponsors list.
Parses sponsor legal name, trading name, ABN, state/territory, and visa subclasses (482, 494, 186).
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


def parse_au_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """Parse CSV of Australian Approved Standard Business Sponsors."""
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    col_name = 0
    col_abn = 1
    col_state = 2

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if "sponsor" in c or "organisation" in c or "legal name" in c or "business name" in c:
            col_name = idx
        elif "abn" in c:
            col_abn = idx
        elif "state" in c or "location" in c:
            col_state = idx

    seen_norms = set()
    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        abn = row[col_abn].strip() if len(row) > col_abn else ""
        state = row[col_state].strip() if len(row) > col_state else ""

        norm = normalize_company_name(legal_name)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="AU",
                legal_name=legal_name,
                routes=["Subclass 482 (TSS)", "Subclass 494", "Subclass 186 (ENS)"],
                rating="Approved Standard Business Sponsor",
                source="home_affairs_sponsors",
                as_of=as_of,
                extra={"abn": abn, "state": state},
            )
        )

    logger.info("Parsed %d Australian approved sponsor records.", len(records))
    return records


def ingest_au_sponsors(csv_path_or_url: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest Australian sponsors into SQLite."""
    csv_text = ""
    if csv_path_or_url.startswith("http://") or csv_path_or_url.startswith("https://"):
        resp = requests.get(csv_path_or_url, timeout=60)
        resp.raise_for_status()
        csv_text = resp.text
    else:
        with open(csv_path_or_url, "r", encoding="utf-8", errors="ignore") as f:
            csv_text = f.read()

    records = parse_au_csv_stream(csv_text)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d Australian sponsors into %s.", count, db_path)
    return count

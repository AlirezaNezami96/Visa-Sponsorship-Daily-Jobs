"""
src/job_radar/visa/ingest_us.py

Ingests US Department of Labor (DOL) OFLC LCA disclosure data (H-1B / H-1B1 / E-3).
Aggregates employer certified case volume, median wage, and top titles.
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

from job_radar.visa.db import bulk_upsert_sponsors, DEFAULT_DB_PATH
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)


def aggregate_lca_records(rows: List[Dict[str, Any]], as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Aggregates raw LCA filing rows into SponsorRecord entries by normalized employer name.
    """
    as_of = as_of_date or datetime.date.today().isoformat()
    employers: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "legal_name": "",
        "certified_count": 0,
        "wages": [],
        "titles": defaultdict(int),
        "visa_classes": set(),
    })

    for row in rows:
        status = (row.get("CASE_STATUS") or row.get("case_status") or "").strip().lower()
        if "certified" not in status:
            continue

        raw_name = (
            row.get("EMPLOYER_NAME")
            or row.get("EMPLOYER_LEGAL_BUSINESS_NAME")
            or row.get("employer_name")
            or ""
        ).strip()
        if not raw_name:
            continue

        norm = normalize_company_name(raw_name)
        if not norm:
            continue

        emp = employers[norm]
        if not emp["legal_name"] or len(raw_name) > len(emp["legal_name"]):
            emp["legal_name"] = raw_name

        emp["certified_count"] += 1

        # Wage
        wage_str = str(row.get("WAGE_RATE_OF_PAY_FROM") or row.get("wage_rate_from") or "").replace("$", "").replace(",", "").strip()
        try:
            wage = float(wage_str)
            if 30000 <= wage <= 1000000:
                emp["wages"].append(wage)
        except ValueError:
            pass

        # Job title / SOC
        title = (row.get("JOB_TITLE") or row.get("SOC_TITLE") or "").strip()
        if title:
            emp["titles"][title] += 1

        # Visa class
        v_class = (row.get("VISA_CLASS") or "H-1B").strip()
        if v_class:
            emp["visa_classes"].add(v_class)

    records: List[SponsorRecord] = []
    for norm, data in employers.items():
        wages = data["wages"]
        median_wage = sorted(wages)[len(wages) // 2] if wages else None
        top_titles = [t for t, _ in sorted(data["titles"].items(), key=lambda x: x[1], reverse=True)[:5]]

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="US",
                legal_name=data["legal_name"],
                routes=list(data["visa_classes"]) or ["H-1B"],
                rating="Certified",
                source="dol_lca",
                as_of=as_of,
                extra={
                    "lca_count_12m": data["certified_count"],
                    "median_wage": median_wage,
                    "top_titles": top_titles,
                },
            )
        )

    logger.info("Aggregated %d US employers from LCA records.", len(records))
    return records


def ingest_us_lca_csv(csv_path_or_url: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Ingest US LCA disclosure CSV into SQLite."""
    rows: List[Dict[str, Any]] = []

    if csv_path_or_url.startswith("http://") or csv_path_or_url.startswith("https://"):
        resp = requests.get(csv_path_or_url, timeout=90)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
    else:
        with open(csv_path_or_url, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    records = aggregate_lca_records(rows)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Upserted %d US LCA employers into %s.", count, db_path)
    return count

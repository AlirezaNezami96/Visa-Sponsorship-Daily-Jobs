"""
src/job_radar/visa/ingest_uk.py

Ingests the official UK Register of Licensed Sponsors from GOV.UK.
Parses the live index page for the latest dynamic CSV URL.
Filters for 'Worker' / 'Skilled Worker' routes and indexes by normalized company name.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from job_radar.visa.db import bulk_upsert_sponsors, DEFAULT_DB_PATH
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)

GOVUK_SPONSORS_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"


def find_latest_uk_sponsor_csv_url(page_url: str = GOVUK_SPONSORS_PAGE) -> Optional[str]:
    """Scrapes the GOV.UK register page to dynamically find the active CSV asset link."""
    headers = {"User-Agent": "Mozilla/5.0 (JobOS/1.0; +https://github.com)"}
    try:
        resp = requests.get(page_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning("Failed to fetch GOV.UK sponsors page (%d)", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        # Look for links ending in .csv or containing .csv
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".csv" in href.lower():
                if href.startswith("http"):
                    return href
                return f"https://www.gov.uk{href}"
    except Exception as e:
        logger.warning("Error finding latest UK sponsor CSV link: %s", e)

    return None


def parse_uk_csv_stream(csv_content: str, as_of_date: Optional[str] = None) -> List[SponsorRecord]:
    """
    Parse the CSV text of UK licensed sponsors.
    Header columns typically:
      Organisation Name, Town/City, County, Type & Rating, Route
    """
    records: List[SponsorRecord] = []
    as_of = as_of_date or datetime.date.today().isoformat()

    f = io.StringIO(csv_content)
    reader = csv.reader(f)

    header = next(reader, None)
    if not header:
        return []

    # Detect column indices
    col_name = 0
    col_city = 1
    col_rating = 3
    col_route = 4

    for idx, col in enumerate(header):
        c = col.strip().lower()
        if "organisation" in c or "organization" in c:
            col_name = idx
        elif "town" in c or "city" in c:
            col_city = idx
        elif "rating" in c:
            col_rating = idx
        elif "route" in c:
            col_route = idx

    for row in reader:
        if not row or len(row) <= col_name:
            continue

        legal_name = row[col_name].strip()
        if not legal_name:
            continue

        rating_raw = row[col_rating].strip() if len(row) > col_rating else ""
        route_raw = row[col_route].strip() if len(row) > col_route else ""
        city_raw = row[col_city].strip() if len(row) > col_city else ""

        # Check for Skilled Worker route (exclude Temporary Worker)
        combined = f"{rating_raw} {route_raw}".lower()
        if "temporary worker" in combined:
            continue
        if "skilled worker" not in combined and not combined.startswith("worker"):
            continue

        rating = "A"
        if "b rating" in rating_raw.lower() or "(b rating)" in combined:
            rating = "B (licence_warning)"

        routes = ["Skilled Worker"]
        if "global business mobility" in combined:
            routes.append("Global Business Mobility")

        norm = normalize_company_name(legal_name)
        if not norm:
            continue

        records.append(
            SponsorRecord(
                normalized_name=norm,
                country="UK",
                legal_name=legal_name,
                routes=routes,
                rating=rating,
                source="govuk_register",
                as_of=as_of,
                extra={"city": city_raw, "raw_route": route_raw},
            )
        )

    logger.info("Parsed %d UK sponsor records from CSV stream.", len(records))
    return records


def ingest_uk_sponsors(csv_url_or_path: Optional[str] = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Download and ingest latest UK sponsors into SQLite."""
    url = csv_url_or_path or find_latest_uk_sponsor_csv_url()
    if not url:
        logger.warning("No UK sponsor CSV URL found. Ingestion skipped.")
        return 0

    csv_text = ""
    if url.startswith("http://") or url.startswith("https://"):
        logger.info("Downloading UK sponsors from %s...", url)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        csv_text = resp.text
    else:
        # Local file path
        with open(url, "r", encoding="utf-8", errors="ignore") as f:
            csv_text = f.read()

    records = parse_uk_csv_stream(csv_text)
    count = bulk_upsert_sponsors(records, db_path=db_path)
    logger.info("Successfully upserted %d UK sponsors into %s.", count, db_path)
    return count

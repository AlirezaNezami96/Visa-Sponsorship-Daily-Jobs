"""
src/job_radar/visa/db.py

SQLite storage for official government sponsor registers, LCA historical filings, and aliases.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_radar.visa.models import SponsorRecord

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/sponsors/sponsors.db")
DEFAULT_GZ_PATH = Path("data/sponsors/sponsors.db.gz")


def ensure_db_extracted(db_path: Path = DEFAULT_DB_PATH) -> Path:
    """
    Ensure the SQLite database file exists on disk.
    If the uncompressed .db does not exist, but .db.gz exists, automatically decompress it.
    """
    if db_path.exists():
        return db_path

    gz_path = Path(str(db_path) + ".gz") if not str(db_path).endswith(".gz") else None
    if gz_path and gz_path.exists():
        logger.info("Auto-decompressing sponsor database: %s -> %s...", gz_path, db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        import gzip
        import shutil

        temp_path = db_path.with_suffix(".tmp")
        try:
            with gzip.open(gz_path, "rb") as f_in, temp_path.open("wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            temp_path.replace(db_path)
            logger.info(
                "Sponsor database successfully extracted: %s (%.2f MB)",
                db_path,
                db_path.stat().st_size / (1024 * 1024),
            )
        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink()
            logger.error("Failed to auto-decompress sponsor database %s: %s", gz_path, exc)
            raise

    return db_path


def compress_sponsor_db(db_path: Path = DEFAULT_DB_PATH, gz_path: Optional[Path] = None) -> Path:
    """
    Compress SQLite database into .db.gz for Git tracking and efficient CI distribution.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Cannot compress non-existent database: {db_path}")

    target_gz = gz_path or Path(str(db_path) + ".gz")
    target_gz.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    import shutil

    temp_gz = target_gz.with_suffix(".tmp")
    with db_path.open("rb") as f_in, gzip.open(temp_gz, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)

    temp_gz.replace(target_gz)
    logger.info(
        "Compressed sponsor database: %s -> %s (%.2f MB -> %.2f MB)",
        db_path,
        target_gz,
        db_path.stat().st_size / (1024 * 1024),
        target_gz.stat().st_size / (1024 * 1024),
    )
    return target_gz


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    ensure_db_extracted(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_sponsor_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Initialize sponsors schema and index structures."""
    ensure_db_extracted(db_path)
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sponsors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_name TEXT UNIQUE NOT NULL,
                country TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                routes_json TEXT NOT NULL,
                rating TEXT NOT NULL,
                source TEXT NOT NULL,
                as_of TEXT NOT NULL,
                extra_json TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sponsor_aliases (
                alias TEXT PRIMARY KEY,
                sponsor_normalized TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_norm ON sponsors(normalized_name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_country ON sponsors(country);")
        conn.commit()


def bulk_upsert_sponsors(records: List[SponsorRecord], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Bulk insert or replace sponsor records."""
    if not records:
        return 0

    init_sponsor_db(db_path)
    with get_connection(db_path) as conn:
        data = [
            (
                r.normalized_name,
                r.country,
                r.legal_name,
                json.dumps(r.routes, ensure_ascii=False),
                r.rating,
                r.source,
                r.as_of,
                json.dumps(r.extra, ensure_ascii=False),
            )
            for r in records
        ]
        conn.executemany("""
            INSERT INTO sponsors (normalized_name, country, legal_name, routes_json, rating, source, as_of, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                country=excluded.country,
                legal_name=excluded.legal_name,
                routes_json=excluded.routes_json,
                rating=excluded.rating,
                source=excluded.source,
                as_of=excluded.as_of,
                extra_json=excluded.extra_json;
        """, data)
        conn.commit()

    return len(records)


def load_all_sponsors(
    country: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
    allow_empty: bool = False,
) -> Dict[str, SponsorRecord]:
    """Load sponsor records from SQLite into a fast normalized-lookup dictionary."""
    db_path = ensure_db_extracted(db_path)
    if not db_path.exists():
        if not allow_empty:
            logger.critical("Sponsor database missing at path: %s. Run scripts/build_sponsors_db.py to generate it.", db_path)
            raise RuntimeError(f"Sponsor database missing at path: {db_path}. Run scripts/build_sponsors_db.py to generate it.")
        return {}

    init_sponsor_db(db_path)
    sponsors: Dict[str, SponsorRecord] = {}

    with get_connection(db_path) as conn:
        if country:
            cursor = conn.execute("SELECT * FROM sponsors WHERE country = ?", (country.upper(),))
        else:
            cursor = conn.execute("SELECT * FROM sponsors")

        for row in cursor:
            record = SponsorRecord(
                normalized_name=row["normalized_name"],
                country=row["country"],
                legal_name=row["legal_name"],
                routes=json.loads(row["routes_json"]),
                rating=row["rating"],
                source=row["source"],
                as_of=row["as_of"],
                extra=json.loads(row["extra_json"]),
            )
            sponsors[record.normalized_name] = record

    if not sponsors and not allow_empty:
        logger.critical("Sponsor database at %s is empty. Official registries are required for accurate visa matching.", db_path)
        raise RuntimeError(f"Sponsor database at {db_path} is empty. Run scripts/build_sponsors_db.py to populate it.")

    return sponsors


def load_all_aliases(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, str]:
    """Load alias table into a dictionary mapping alias -> sponsor_normalized."""
    db_path = ensure_db_extracted(db_path)
    if not db_path.exists():
        return {}

    init_sponsor_db(db_path)
    aliases: Dict[str, str] = {}
    with get_connection(db_path) as conn:
        cursor = conn.execute("SELECT alias, sponsor_normalized FROM sponsor_aliases")
        for row in cursor:
            aliases[row["alias"]] = row["sponsor_normalized"]

    return aliases

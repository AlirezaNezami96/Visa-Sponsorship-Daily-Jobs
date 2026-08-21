"""
SQLite database for persistent memory of tailored jobs, resumes, and cover letters.
Stores historical records keyed by normalized job posting URLs.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DB_DIR / "jobs.db"


def normalize_job_url(url: str) -> str:
    """
    Clean and normalize job posting URLs by stripping tracking parameters,
    session tokens, and anchors.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        # Filter out common tracking query params
        tracking_prefixes = ("utm_", "ref", "source", "trk", "tracking", "gh_jid", "linkedin_jid", "midToken", "trkInfo")
        clean_params = [
            (k, v) for k, v in parse_qsl(parsed.query)
            if not any(k.lower().startswith(p) for p in tracking_prefixes)
        ]
        # Sort params for consistency
        clean_query = urlencode(sorted(clean_params))
        # Remove trailing slash from path
        clean_path = parsed.path.rstrip("/")
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            clean_query,
            "",
        ))
        return normalized
    except Exception:
        return url.strip().split("?")[0].rstrip("/")


def init_db() -> None:
    """Initialize the SQLite database schema if not already present."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tailored_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_url TEXT NOT NULL,
                normalized_url TEXT NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                job_title TEXT NOT NULL,
                ats_score INTEGER DEFAULT 0,
                matched_keywords TEXT DEFAULT '[]',
                missing_keywords TEXT DEFAULT '[]',
                google_doc_url TEXT DEFAULT '',
                resume_doc_id TEXT DEFAULT '',
                cover_letter_doc_id TEXT DEFAULT '',
                cover_letter_body TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_normalized_url ON tailored_jobs(normalized_url);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_updated_at ON tailored_jobs(updated_at DESC);")
        conn.commit()
    logger.info("Initialized Job database at %s", _DB_PATH)


def get_job_by_url(url: str) -> Optional[Dict[str, Any]]:
    """Look up a previously tailored job record by its URL."""
    norm_url = normalize_job_url(url)
    if not norm_url:
        return None

    init_db()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tailored_jobs WHERE normalized_url = ? OR job_url = ? LIMIT 1",
            (norm_url, url),
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["matched_keywords"] = json.loads(data.get("matched_keywords") or "[]")
        data["missing_keywords"] = json.loads(data.get("missing_keywords") or "[]")
        return data


def save_tailored_resume(
    job_url: str,
    company_name: str,
    job_title: str,
    ats_score: int,
    matched_keywords: List[str],
    missing_keywords: List[str],
    resume_doc_id: str,
    google_doc_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Save or update a tailored resume record."""
    norm_url = normalize_job_url(job_url)
    now = time.time()
    init_db()

    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tailored_jobs (
                job_url, normalized_url, company_name, job_title,
                ats_score, matched_keywords, missing_keywords,
                google_doc_url, resume_doc_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO UPDATE SET
                job_url = excluded.job_url,
                company_name = excluded.company_name,
                job_title = excluded.job_title,
                ats_score = excluded.ats_score,
                matched_keywords = excluded.matched_keywords,
                missing_keywords = excluded.missing_keywords,
                google_doc_url = CASE WHEN excluded.google_doc_url != '' THEN excluded.google_doc_url ELSE tailored_jobs.google_doc_url END,
                resume_doc_id = excluded.resume_doc_id,
                updated_at = excluded.updated_at
        """, (
            job_url,
            norm_url,
            company_name,
            job_title,
            ats_score,
            json.dumps(matched_keywords),
            json.dumps(missing_keywords),
            google_doc_url or "",
            resume_doc_id,
            now,
            now,
        ))
        conn.commit()

    return get_job_by_url(job_url) or {}


def save_tailored_cover_letter(
    job_url: str,
    company_name: str,
    job_title: str,
    cover_letter_doc_id: str,
    cover_letter_body: str,
) -> Dict[str, Any]:
    """Save or update a tailored cover letter record."""
    norm_url = normalize_job_url(job_url)
    now = time.time()
    init_db()

    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tailored_jobs (
                job_url, normalized_url, company_name, job_title,
                cover_letter_doc_id, cover_letter_body, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO UPDATE SET
                job_url = excluded.job_url,
                company_name = excluded.company_name,
                job_title = excluded.job_title,
                cover_letter_doc_id = excluded.cover_letter_doc_id,
                cover_letter_body = excluded.cover_letter_body,
                updated_at = excluded.updated_at
        """, (
            job_url,
            norm_url,
            company_name,
            job_title,
            cover_letter_doc_id,
            cover_letter_body,
            now,
            now,
        ))
        conn.commit()

    return get_job_by_url(job_url) or {}


def get_all_job_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve list of all tailored jobs sorted by most recently updated."""
    init_db()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tailored_jobs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["matched_keywords"] = json.loads(d.get("matched_keywords") or "[]")
            d["missing_keywords"] = json.loads(d.get("missing_keywords") or "[]")
            result.append(d)
        return result

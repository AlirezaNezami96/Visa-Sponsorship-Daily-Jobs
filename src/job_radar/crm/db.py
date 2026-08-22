"""
src/job_radar/crm/db.py

SQLite-backed Job CRM storage, status transitions, and follow-up tracker.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_radar.crm.models import CRMJobRecord, JobStatus

logger = logging.getLogger(__name__)

DEFAULT_CRM_DB_PATH = Path("state/crm.db")


def get_crm_connection(db_path: Path = DEFAULT_CRM_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_crm_db(db_path: Path = DEFAULT_CRM_DB_PATH) -> None:
    """Initialize CRM database table schema and indexes."""
    with get_crm_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crm_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                normalized_url TEXT,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                source TEXT,
                remote_scope TEXT,
                visa_confidence TEXT,
                auth_fit TEXT,
                ats_score INTEGER,
                composite REAL,
                status TEXT NOT NULL DEFAULT 'new',
                resume_doc_id TEXT,
                cover_doc_id TEXT,
                google_doc_url TEXT,
                first_seen_at REAL,
                posted_at TEXT,
                applied_at REAL,
                followup_at REAL,
                next_action TEXT,
                notes TEXT,
                jd_hash TEXT,
                raw_json TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_status ON crm_jobs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_fingerprint ON crm_jobs(fingerprint);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_url ON crm_jobs(url);")
        conn.commit()


def upsert_crm_job(job: Dict[str, Any], db_path: Path = DEFAULT_CRM_DB_PATH) -> CRMJobRecord:
    """Insert or update a job in the CRM."""
    init_crm_db(db_path)
    fp = job.get("_fingerprint") or job.get("fingerprint") or job.get("url") or ""
    now = time.time()

    with get_crm_connection(db_path) as conn:
        # Check if exists
        cursor = conn.execute("SELECT * FROM crm_jobs WHERE fingerprint = ? OR url = ?", (fp, job.get("url", "")))
        row = cursor.fetchone()

        if row:
            # Update fields if new details arrive without overriding user status
            conn.execute("""
                UPDATE crm_jobs SET
                    composite = COALESCE(?, composite),
                    ats_score = COALESCE(?, ats_score),
                    visa_confidence = COALESCE(?, visa_confidence),
                    auth_fit = COALESCE(?, auth_fit),
                    resume_doc_id = COALESCE(?, resume_doc_id),
                    cover_doc_id = COALESCE(?, cover_doc_id),
                    google_doc_url = COALESCE(?, google_doc_url),
                    jd_hash = COALESCE(?, jd_hash),
                    raw_json = COALESCE(?, raw_json)
                WHERE id = ?;
            """, (
                job.get("composite"),
                job.get("ats_score"),
                str(job.get("visa_confidence", "")),
                str(job.get("auth_fit", "")),
                job.get("resume_doc_id"),
                job.get("cover_doc_id"),
                job.get("google_doc_url"),
                job.get("jd_hash"),
                json.dumps(job, ensure_ascii=False) if isinstance(job, dict) else None,
                row["id"]
            ))
            conn.commit()
            return get_job_by_id(row["id"], db_path=db_path)  # type: ignore

        # Insert new
        cursor = conn.execute("""
            INSERT INTO crm_jobs (
                fingerprint, url, normalized_url, company, title, location, source,
                remote_scope, visa_confidence, auth_fit, ats_score, composite, status,
                resume_doc_id, cover_doc_id, google_doc_url, first_seen_at, posted_at,
                notes, jd_hash, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fp,
            job.get("url", ""),
            job.get("normalized_url", job.get("url", "")),
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("source", ""),
            job.get("remote_scope", "unclear"),
            str(job.get("visa_confidence", "unknown")),
            str(job.get("auth_fit", "sponsor_unknown")),
            job.get("ats_score"),
            job.get("composite"),
            JobStatus.NEW.value,
            job.get("resume_doc_id"),
            job.get("cover_doc_id"),
            job.get("google_doc_url"),
            job.get("first_seen_at", now),
            job.get("date_posted"),
            job.get("notes"),
            job.get("jd_hash"),
            json.dumps(job, ensure_ascii=False) if isinstance(job, dict) else None,
        ))
        conn.commit()
        return get_job_by_id(cursor.lastrowid, db_path=db_path)  # type: ignore


def update_job_status(
    job_id_or_url: int | str,
    status: JobStatus | str,
    notes: Optional[str] = None,
    db_path: Path = DEFAULT_CRM_DB_PATH,
) -> Optional[CRMJobRecord]:
    """Transition a job's status along the application lifecycle state machine."""
    init_crm_db(db_path)
    status_str = status.value if isinstance(status, JobStatus) else str(status).lower()
    now = time.time()

    with get_crm_connection(db_path) as conn:
        if isinstance(job_id_or_url, int):
            row = conn.execute("SELECT * FROM crm_jobs WHERE id = ?", (job_id_or_url,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM crm_jobs WHERE url = ? OR fingerprint = ?", (job_id_or_url, job_id_or_url)).fetchone()

        if not row:
            logger.warning("CRM job not found for update: %s", job_id_or_url)
            return None

        job_id = row["id"]
        applied_at = row["applied_at"]
        followup_at = row["followup_at"]
        next_action = row["next_action"]

        # Handle lifecycle triggers
        if status_str == JobStatus.APPLIED.value and not applied_at:
            applied_at = now
            # Suggest follow-up in 3 days (3 * 86400)
            followup_at = now + (3 * 86400)
            next_action = "Send 3-line bump follow-up if no response"
        elif status_str == JobStatus.INTERVIEW.value:
            next_action = "Prepare STAR interview stories and company brief"
        elif status_str in (JobStatus.REJECTED.value, JobStatus.CLOSED.value, JobStatus.SKIPPED.value):
            followup_at = None
            next_action = None

        conn.execute("""
            UPDATE crm_jobs SET
                status = ?,
                applied_at = ?,
                followup_at = ?,
                next_action = ?,
                notes = COALESCE(?, notes)
            WHERE id = ?;
        """, (status_str, applied_at, followup_at, next_action, notes, job_id))
        conn.commit()

        return get_job_by_id(job_id, db_path=db_path)


def list_crm_jobs(
    status: Optional[JobStatus | str] = None,
    limit: int = 50,
    db_path: Path = DEFAULT_CRM_DB_PATH,
) -> List[CRMJobRecord]:
    """List jobs filtered by status, ordered by composite score desc."""
    init_crm_db(db_path)
    records: List[CRMJobRecord] = []

    with get_crm_connection(db_path) as conn:
        if status:
            s_val = status.value if isinstance(status, JobStatus) else str(status).lower()
            cursor = conn.execute("SELECT * FROM crm_jobs WHERE status = ? ORDER BY composite DESC LIMIT ?", (s_val, limit))
        else:
            cursor = conn.execute("SELECT * FROM crm_jobs ORDER BY composite DESC LIMIT ?", (limit,))

        for r in cursor:
            records.append(CRMJobRecord(**dict(r)))

    return records


def get_job_by_id(job_id: int, db_path: Path = DEFAULT_CRM_DB_PATH) -> Optional[CRMJobRecord]:
    init_crm_db(db_path)
    with get_crm_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM crm_jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            return CRMJobRecord(**dict(row))
    return None


def get_due_followups(db_path: Path = DEFAULT_CRM_DB_PATH) -> List[CRMJobRecord]:
    """Retrieve jobs in 'applied' status where followup_at <= now."""
    init_crm_db(db_path)
    now = time.time()
    due: List[CRMJobRecord] = []

    with get_crm_connection(db_path) as conn:
        cursor = conn.execute("""
            SELECT * FROM crm_jobs
            WHERE status = 'applied' AND followup_at IS NOT NULL AND followup_at <= ?
            ORDER BY followup_at ASC;
        """, (now,))
        for r in cursor:
            due.append(CRMJobRecord(**dict(r)))

    return due

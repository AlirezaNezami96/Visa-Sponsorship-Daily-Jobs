"""
src/job_radar/crm/models.py

Data models and status enum for the Job CRM state machine.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "new"
    MAYBE = "maybe"
    APPLYING = "applying"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"
    SKIPPED = "skipped"
    CLOSED = "closed"


class CRMJobRecord(BaseModel):
    id: Optional[int] = None
    fingerprint: str
    url: str
    normalized_url: str = ""
    company: str
    title: str
    location: str = ""
    source: str = ""
    remote_scope: str = "unclear"
    visa_confidence: str = "unknown"
    auth_fit: str = "sponsor_unknown"
    ats_score: Optional[int] = None
    composite: Optional[float] = None
    status: JobStatus = JobStatus.NEW
    resume_doc_id: Optional[str] = None
    cover_doc_id: Optional[str] = None
    google_doc_url: Optional[str] = None
    first_seen_at: float = Field(default_factory=time.time)
    posted_at: Optional[str] = None
    applied_at: Optional[float] = None
    followup_at: Optional[float] = None
    next_action: Optional[str] = None
    notes: Optional[str] = None
    jd_hash: Optional[str] = None
    raw_json: Optional[str] = None

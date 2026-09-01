"""
src/job_radar/visa/models.py

Data models and Enums for Visa Intelligence, Work Authorization, and Sponsor Database.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VisaConfidence(str, Enum):
    """
    Authoritative visa confidence levels.
    Priority: EXPLICIT_NO > KNOWN_SPONSOR > STATED_IN_JD > ON_SPONSOR_LIST > EMPLOYER_SPONSORED_REGION > HISTORICAL_FILINGS > UNKNOWN
    """
    EXPLICIT_NO = "explicit_no"
    KNOWN_SPONSOR = "known_sponsor"
    STATED_IN_JD = "stated_in_jd"
    ON_SPONSOR_LIST = "on_sponsor_list"
    EMPLOYER_SPONSORED_REGION = "employer_sponsored_region"
    HISTORICAL_FILINGS = "historical_filings"
    UNKNOWN = "unknown"


class AuthFit(str, Enum):
    """
    Candidate work-authorization compatibility.
    """
    INELIGIBLE = "ineligible"
    REMOTE_OK = "remote_ok"
    SPONSOR_REQUIRED_AND_PLAUSIBLE = "sponsor_required_and_plausible"
    SPONSOR_UNKNOWN = "sponsor_unknown"
    ALREADY_AUTHORIZED = "already_authorized"


class SponsorRecord(BaseModel):
    normalized_name: str
    country: str
    legal_name: str
    routes: List[str] = Field(default_factory=list)
    rating: str = "A"
    source: str = "govuk_register"
    as_of: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)
    confidence_tier: Optional[str] = None  # Pre-tag: "verified", "low", "negative"

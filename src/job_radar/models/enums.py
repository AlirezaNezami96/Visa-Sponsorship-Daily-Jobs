"""Enums for the canonical Job model, Visa Intelligence, and Radar pipeline."""
from __future__ import annotations

from enum import Enum


class TrackType(str, Enum):
    INTERNSHIP = "internship"
    ENGINEER = "engineer"
    BORDERLINE = "borderline"
    REJECT = "reject"
    OTHER = "other"


class WorkplaceType(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNSPECIFIED = "unspecified"


class RemoteScope(str, Enum):
    WORLDWIDE = "worldwide"
    REGION_RESTRICTED = "region_restricted"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    ONSITE_ONLY = "onsite_only"
    UNCLEAR = "unclear"
    UNKNOWN = "unknown"


class VisaConfidence(str, Enum):
    """Authoritative visa confidence levels.
    Priority rule: EXPLICIT_NO > STATED_IN_JD > ON_SPONSOR_LIST > HISTORICAL_FILINGS > UNKNOWN
    """
    EXPLICIT_NO = "explicit_no"           # JD says "no sponsorship" / "must have right to work"
    STATED_IN_JD = "stated_in_jd"         # JD explicitly offers visa/relocation/sponsorship
    ON_SPONSOR_LIST = "on_sponsor_list"   # Company matches official government registry
    HISTORICAL_FILINGS = "historical_filings"  # US LCA data shows past sponsorship
    UNKNOWN = "unknown"                    # Default, no signal either way


class AuthFit(str, Enum):
    """Candidate work-authorization compatibility."""
    INELIGIBLE = "ineligible"
    REMOTE_OK = "remote_ok"
    SPONSOR_REQUIRED_AND_PLAUSIBLE = "sponsor_required_and_plausible"
    SPONSOR_UNKNOWN = "sponsor_unknown"
    ALREADY_AUTHORIZED = "already_authorized"


class Seniority(str, Enum):
    INTERN = "intern"
    NEW_GRAD = "new_grad"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    EXECUTIVE = "executive"


class VisaStatus(str, Enum):
    SPONSORS = "sponsors"
    LIKELY = "likely"
    OPT_FRIENDLY = "opt_friendly"
    UNKNOWN = "unknown"
    NO = "no"

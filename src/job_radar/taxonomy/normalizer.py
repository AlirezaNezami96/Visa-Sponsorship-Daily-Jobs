"""
src/job_radar/taxonomy/normalizer.py

Comprehensive, occupation-agnostic normalization pipeline for:
  - Job title -> ISCO-08 Unit Group -> Major Group
  - Seniority level (intern, junior, mid, senior, lead, executive, unspecified)
  - Remote scope (worldwide, region_restricted, hybrid, onsite, unspecified)
  - Employment type (permanent, contract, temporary, seasonal, apprenticeship, unspecified)
  - Location & canonical country code
  - Industry inference
  - Sponsorship language signals
  - Uncertainty attribution (tracks why any field is unknown)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from job_radar.taxonomy.isco import (
    ISCO_MAJOR_GROUPS,
    ISCOUnitGroup,
    get_country_specific_occupation_code,
    lookup_isco_by_code,
    search_isco_by_keywords,
)
from job_radar.taxonomy.skills import extract_skills_from_text


@dataclass
class NormalizedJobFields:
    """Standard container for all normalized attributes with explicit uncertainty tracking."""
    # Title & Taxonomy
    raw_title: str
    normalized_title: str
    isco_code: Optional[str] = None
    isco_title: Optional[str] = None
    isco_major_group_code: Optional[str] = None
    isco_major_group_title: Optional[str] = None
    country_specific_occupation: Optional[Dict[str, Any]] = None

    # Seniority
    seniority: str = "unspecified"  # intern | junior | mid | senior | lead | executive | unspecified
    seniority_confidence: float = 1.0

    # Remote & Location
    remote_scope: str = "unspecified"  # worldwide | region_restricted | hybrid | onsite | unspecified
    is_remote: bool = False
    is_hybrid: bool = False
    canonical_country: Optional[str] = None
    canonical_city: Optional[str] = None
    allowed_regions: List[str] = field(default_factory=list)

    # Employment & Industry
    employment_type: str = "unspecified"  # permanent | contract | temporary | seasonal | apprenticeship | unspecified
    industry: str = "unspecified"

    # Skills & Credentials
    skills: List[str] = field(default_factory=list)
    credentials: List[str] = field(default_factory=list)

    # Sponsorship Language (Completely independent of occupation)
    sponsorship_mentioned: bool = False
    sponsorship_mention_type: str = "unspecified"  # offers_sponsorship | opt_stem | explicit_refusal | unspecified
    sponsorship_quotes: List[str] = field(default_factory=list)

    # Uncertainty attribution: reason for any unspecified/unknown field
    uncertainty_reasons: Dict[str, str] = field(default_factory=dict)


# Seniority detection patterns
SENIORITY_PATTERNS = {
    "intern": [
        r"\b(intern|internship|trainee|praktikant|stagiaire|fellow|fellowship|student|co-?op)\b",
    ],
    "junior": [
        r"\b(junior|jr\.?|associate|entry[- ]level|graduate|starter|early[- ]career|0-2\s*(?:yrs|years))\b",
    ],
    "senior": [
        r"\b(senior|sr\.?|principal|staff|expert|experienced|3\+\s*(?:yrs|years)|5\+\s*(?:yrs|years))\b",
    ],
    "lead": [
        r"\b(lead|team\s+lead|tech\s+lead|head\s+of|manager|director|vp|vice\s+president|chief|architect)\b",
    ],
    "executive": [
        r"\b(executive|c-level|cto|cfo|cmo|ceo|managing\s+director|partner)\b",
    ],
}

# Remote scope patterns
REMOTE_WORLDWIDE_PATTERNS = [
    r"\b(worldwide|anywhere|global\s+remote|remote\s+worldwide|work\s+from\s+anywhere|wfa|100%\s+remote\s+global)\b",
]
REMOTE_RESTRICTED_PATTERNS = [
    r"\b(remote\s+in\s+[A-Za-z]+|remote\s*\([A-Za-z\s,]+\)|us\s+remote|uk\s+remote|eu\s+remote|canada\s+remote)\b",
]
HYBRID_PATTERNS = [
    r"\b(hybrid|flexible|2-3\s+days\s+in\s+office|partially\s+remote|mixed\s+remote)\b",
]
ONSITE_PATTERNS = [
    r"\b(on-?site|in-?office|in-?person|office-?based|relocation\s+required)\b",
]

# Employment type patterns
EMPLOYMENT_PATTERNS = {
    "permanent": [r"\b(permanent|full[- ]time|indefinite|cdi|festanstellung)\b"],
    "contract": [r"\b(contract|contractor|freelance|c2c|consultant|fixed[- ]term|cdd)\b"],
    "temporary": [r"\b(temporary|temp|casual|seasonal|interim)\b"],
    "apprenticeship": [r"\b(apprenticeship|apprentice|ausbildung|dual\s+study)\b"],
    "internship": [r"\b(internship|intern|stage|praktikum)\b"],
}

# ISO Country Code mapping helper
COUNTRY_CODE_MAP = {
    "united states": "US", "usa": "US", "us": "US",
    "united kingdom": "UK", "great britain": "UK", "england": "UK", "scotland": "UK", "wales": "UK", "uk": "UK", "gb": "UK",
    "canada": "CA", "ca": "CA",
    "australia": "AU", "au": "AU",
    "new zealand": "NZ", "nz": "NZ",
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "netherlands": "NL", "holland": "NL", "nl": "NL",
    "ireland": "IE", "eire": "IE", "ie": "IE",
    "singapore": "SG", "sg": "SG",
    "united arab emirates": "AE", "uae": "AE", "dubai": "AE", "abu dhabi": "AE", "ae": "AE",
    "saudi arabia": "SA", "ksa": "SA", "riyadh": "SA", "sa": "SA",
    "qatar": "QA", "doha": "QA", "qa": "QA",
    "france": "FR", "fr": "FR",
    "switzerland": "CH", "ch": "CH",
    "sweden": "SE", "se": "SE",
    "spain": "ES", "es": "ES",
    "italy": "IT", "it": "IT",
    "japan": "JP", "jp": "JP",
    "south korea": "KR", "korea": "KR", "kr": "KR",
    "india": "IN", "in": "IN",
}


def normalize_title_string(raw_title: str) -> str:
    """Clean raw title string of artifacts, tags, requisition IDs, and punctuation."""
    if not raw_title:
        return "Untitled"

    t = raw_title.strip()
    # Strip requisition IDs like (REQ-12345), [12345], #998877
    t = re.sub(r"\((?:REQ[- ]?)?[0-9A-Za-z-]+\)", "", t)
    t = re.sub(r"\[(?:REQ[- ]?)?[0-9A-Za-z-]+\]", "", t)
    t = re.sub(r"#\d+", "", t)
    # Strip trailing location or remote tags in title like " - Remote", " (Worldwide)"
    t = re.sub(r"[-–—|/]\s*(?:Remote|Hybrid|Onsite|Worldwide|Full[- ]Time|Part[- ]Time).*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" -–—|/.,:;")
    return t or raw_title.strip()


def extract_seniority(title: str, text: str = "") -> Tuple[str, float]:
    """
    Extract standardized seniority level.
    Returns (seniority, confidence).
    """
    title_lower = title.lower()

    # Check title first (highest priority)
    for level, patterns in SENIORITY_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, title_lower, re.IGNORECASE):
                return level, 1.0

    # If not in title, scan job description text
    if text:
        text_lower = text.lower()[:1500]
        for level, patterns in SENIORITY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text_lower, re.IGNORECASE):
                    return level, 0.8

    # Default to unspecified rather than guessing
    return "unspecified", 0.0


def extract_remote_scope(
    location: str = "",
    description: str = "",
    remote_flag: Optional[bool] = None,
) -> Tuple[str, bool, bool, List[str]]:
    """
    Extract canonical remote scope: worldwide | region_restricted | hybrid | onsite | unspecified.
    Returns (remote_scope, is_remote, is_hybrid, allowed_regions).
    """
    combined = f"{location} {description[:600]}".lower()

    for pat in REMOTE_WORLDWIDE_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return "worldwide", True, False, ["Worldwide"]

    for pat in HYBRID_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return "hybrid", False, True, []

    for pat in REMOTE_RESTRICTED_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_restricted", True, False, [location] if location else []

    for pat in ONSITE_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return "onsite", False, False, []

    if remote_flag is True or "remote" in location.lower():
        # General remote without explicit worldwide qualifier
        return "region_restricted", True, False, [location] if location else []

    if location:
        return "onsite", False, False, []

    return "unspecified", False, False, []


def extract_employment_type(text: str) -> str:
    """Extract standard employment type."""
    t = text.lower()
    for emp_type, patterns in EMPLOYMENT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                return emp_type
    return "unspecified"


def normalize_location(raw_location: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize location string to (canonical_country_code, city_or_region).
    """
    if not raw_location:
        return None, None

    loc_clean = raw_location.strip()
    loc_lower = loc_clean.lower()

    matched_country = None
    for name, code in COUNTRY_CODE_MAP.items():
        if re.search(r"\b" + re.escape(name) + r"\b", loc_lower):
            matched_country = code
            break

    # Extract city (first token or before comma)
    city = None
    if "," in loc_clean:
        city = loc_clean.split(",")[0].strip()
    elif "/" in loc_clean:
        city = loc_clean.split("/")[0].strip()
    elif loc_clean and loc_clean.lower() not in COUNTRY_CODE_MAP:
        city = loc_clean

    return matched_country, city


def detect_sponsorship_language(text: str) -> Tuple[bool, str, List[str]]:
    """
    Evaluate sponsorship language independently from occupational relevance.
    Returns (sponsorship_mentioned, mention_type, quotes).
    """
    if not text:
        return False, "unspecified", []

    t = text.lower()
    quotes = []

    # 1. Explicit Refusal
    refusal_patterns = [
        r"(?:no|unable to|will not|cannot)\s+(?:provide\s+)?(?:visa\s+)?sponsorship",
        r"must\s+(?:already\s+)?have\s+(?:the\s+)?right\s+to\s+work",
        r"authorized\s+to\s+work\s+(?:in\s+[A-Za-z\s]+)?without\s+sponsorship",
        r"citizens\s+(?:or|and)\s+permanent\s+residents\s+only",
        r"security\s+clearance\s+required",
    ]
    for pat in refusal_patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            quotes.append(text[start:end].strip())
            return True, "explicit_refusal", quotes

    # 2. Positive Offer
    positive_patterns = [
        r"(?:provide|offer|support|grant|available)\s+(?:full\s+|complete\s+)?(?:visa\s+)?sponsorship",
        r"visa\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered|supported)",
        r"(?:can|willing\s+to)\s+sponsor\s+(?:visas?|work\s+permits?)",
        r"relocation\s+(?:assistance|package|support|allowance)\s+(?:is\s+)?(?:provided|available|offered)",
        r"(?:eu\s+blue\s+card|skilled\s+worker\s+visa|health\s+and\s+care\s+worker\s+visa|h-1b)\s*(?:sponsorship|support|available|is\s+available)?",
        r"lmia\s+support",
        r"open\s+to\s+relocation",
    ]
    for pat in positive_patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            quotes.append(text[start:end].strip())
            return True, "offers_sponsorship", quotes

    # 3. OPT / Student Authorization
    opt_patterns = [
        r"\b(?:opt|stem[- ]opt|cpt)\s+(?:friendly|accepted|eligible)\b",
    ]
    for pat in opt_patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            quotes.append(text[start:end].strip())
            return True, "opt_stem", quotes

    return False, "unspecified", []


def normalize_job_posting(
    title: str,
    company: str = "",
    location: str = "",
    description: str = "",
    destination_country: Optional[str] = None,
    remote_flag: Optional[bool] = None,
) -> NormalizedJobFields:
    """
    Execute full normalization pipeline across title, taxonomy, seniority,
    remote scope, location, skills, and sponsorship language.
    """
    normalized_title = normalize_title_string(title)
    uncertainty: Dict[str, str] = {}

    # 1. ISCO-08 Occupation Mapping
    isco_matches = search_isco_by_keywords(f"{normalized_title} {title}")
    isco_code = None
    isco_title = None
    isco_major_code = None
    isco_major_title = None
    country_occupation = None

    if isco_matches:
        top_unit, confidence = isco_matches[0]
        isco_code = top_unit.code
        isco_title = top_unit.title
        isco_major_code = top_unit.major_group_code
        isco_major_title = top_unit.major_group_title

        target_country = destination_country or location
        if target_country:
            country_occupation = get_country_specific_occupation_code(top_unit.code, target_country)
    else:
        uncertainty["taxonomy"] = "No matching ISCO-08 unit group found for job title"

    # 2. Seniority Extraction
    seniority, sen_conf = extract_seniority(normalized_title, description)
    if seniority == "unspecified":
        uncertainty["seniority"] = "Seniority level not specified in title or description"

    # 3. Remote Scope
    remote_scope, is_remote, is_hybrid, allowed_regions = extract_remote_scope(
        location=location,
        description=description,
        remote_flag=remote_flag,
    )
    if remote_scope == "unspecified":
        uncertainty["remote_scope"] = "No remote or workplace policy declared in listing"

    # 4. Location Normalization
    canon_country, canon_city = normalize_location(location)
    if not canon_country:
        uncertainty["location_country"] = "Country not identified in location text"

    # 5. Employment Type
    emp_type = extract_employment_type(f"{title} {description}")
    if emp_type == "unspecified":
        uncertainty["employment_type"] = "Employment duration/contract type not declared"

    # 6. Skill & Credential Extraction
    target_sector = None
    if isco_major_code == "2":
        if top_unit.sub_major_code == "22":
            target_sector = "healthcare"
        elif top_unit.sub_major_code == "21":
            target_sector = "engineering_and_sciences"
        elif top_unit.sub_major_code == "25":
            target_sector = "information_technology"
        elif top_unit.sub_major_code == "24":
            target_sector = "finance_and_business"
    elif isco_major_code == "7":
        target_sector = "trades_and_construction"
    elif isco_major_code in ("1", "3", "5") and ("chef" in normalized_title.lower() or "hotel" in normalized_title.lower()):
        target_sector = "culinary_and_hospitality"

    extracted_skills_dict = extract_skills_from_text(f"{normalized_title} {description}", target_sector=target_sector)

    # 7. Sponsorship Language Extraction
    spons_mentioned, spons_type, spons_quotes = detect_sponsorship_language(description)
    if not spons_mentioned:
        uncertainty["sponsorship_language"] = "No explicit visa or sponsorship statement in job text"

    # 8. Industry Inference
    industry = "unspecified"
    if isco_major_title:
        industry = isco_major_title

    return NormalizedJobFields(
        raw_title=title,
        normalized_title=normalized_title,
        isco_code=isco_code,
        isco_title=isco_title,
        isco_major_group_code=isco_major_code,
        isco_major_group_title=isco_major_title,
        country_specific_occupation=country_occupation,
        seniority=seniority,
        seniority_confidence=sen_conf,
        remote_scope=remote_scope,
        is_remote=is_remote,
        is_hybrid=is_hybrid,
        canonical_country=canon_country,
        canonical_city=canon_city,
        allowed_regions=allowed_regions,
        employment_type=emp_type,
        industry=industry,
        skills=extracted_skills_dict.get("technical_skills", []),
        credentials=extracted_skills_dict.get("credentials", []),
        sponsorship_mentioned=spons_mentioned,
        sponsorship_mention_type=spons_type,
        sponsorship_quotes=spons_quotes,
        uncertainty_reasons=uncertainty,
    )

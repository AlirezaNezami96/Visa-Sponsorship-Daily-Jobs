"""
Canonical Country and Visa Type definitions for VisaLane.
Provides normalized slug resolution, label mapping, and country-visa associations.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class CanonicalCountry(TypedDict):
    slug: str
    code: str
    name: str
    aliases: List[str]


class CanonicalVisaType(TypedDict):
    slug: str
    name: str
    country_code: str
    country_slug: str
    aliases: List[str]


CANONICAL_COUNTRIES: List[CanonicalCountry] = [
    {
        "slug": "united-states",
        "code": "US",
        "name": "United States",
        "aliases": ["us", "usa", "united states", "united-states", "america"],
    },
    {
        "slug": "united-kingdom",
        "code": "GB",
        "name": "United Kingdom",
        "aliases": ["gb", "uk", "gbr", "united kingdom", "united-kingdom", "great britain", "england", "scotland", "wales"],
    },
    {
        "slug": "germany",
        "code": "DE",
        "name": "Germany",
        "aliases": ["de", "deu", "germany", "deutschland"],
    },
    {
        "slug": "canada",
        "code": "CA",
        "name": "Canada",
        "aliases": ["ca", "can", "canada"],
    },
    {
        "slug": "australia",
        "code": "AU",
        "name": "Australia",
        "aliases": ["au", "aus", "australia"],
    },
    {
        "slug": "ireland",
        "code": "IE",
        "name": "Ireland",
        "aliases": ["ie", "irl", "ireland"],
    },
    {
        "slug": "netherlands",
        "code": "NL",
        "name": "Netherlands",
        "aliases": ["nl", "nld", "netherlands", "holland"],
    },
    {
        "slug": "singapore",
        "code": "SG",
        "name": "Singapore",
        "aliases": ["sg", "sgp", "singapore"],
    },
    {
        "slug": "uae",
        "code": "AE",
        "name": "United Arab Emirates",
        "aliases": ["ae", "are", "uae", "united arab emirates", "dubai", "abu dhabi"],
    },
    {
        "slug": "new-zealand",
        "code": "NZ",
        "name": "New Zealand",
        "aliases": ["nz", "nzl", "new zealand", "new-zealand"],
    },
]

CANONICAL_VISA_TYPES: List[CanonicalVisaType] = [
    # US
    {
        "slug": "h-1b",
        "name": "H-1B",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["h1b", "h-1b", "h 1b", "h-1b visa"],
    },
    {
        "slug": "o-1",
        "name": "O-1",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["o1", "o-1", "o 1", "o-1 visa", "o1a", "o1b"],
    },
    {
        "slug": "tn",
        "name": "TN",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["tn", "tn visa", "nafta"],
    },
    {
        "slug": "l-1",
        "name": "L-1",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["l1", "l-1", "l 1", "l-1 visa", "l1a", "l1b"],
    },
    # UK
    {
        "slug": "skilled-worker",
        "name": "Skilled Worker",
        "country_code": "GB",
        "country_slug": "united-kingdom",
        "aliases": ["skilled worker", "skilled worker visa", "skilled-worker", "tier 2", "tier 2 general"],
    },
    {
        "slug": "health-and-care-worker",
        "name": "Health and Care Worker",
        "country_code": "GB",
        "country_slug": "united-kingdom",
        "aliases": ["health and care worker", "health and care worker visa", "health-and-care-worker"],
    },
    # Germany
    {
        "slug": "eu-blue-card",
        "name": "EU Blue Card",
        "country_code": "DE",
        "country_slug": "germany",
        "aliases": ["eu blue card", "blue card", "blaue karte", "eu-blue-card"],
    },
    {
        "slug": "skilled-immigration-act",
        "name": "Skilled Immigration Act",
        "country_code": "DE",
        "country_slug": "germany",
        "aliases": ["skilled immigration act", "chancenkarte", "opportunity card", "skilled-immigration-act"],
    },
    # Canada
    {
        "slug": "express-entry",
        "name": "Express Entry",
        "country_code": "CA",
        "country_slug": "canada",
        "aliases": ["express entry", "express-entry", "federal skilled worker", "fsw"],
    },
    {
        "slug": "lmia-work-permit",
        "name": "LMIA Work Permit",
        "country_code": "CA",
        "country_slug": "canada",
        "aliases": ["lmia", "lmia work permit", "lmia-work-permit", "temporary foreign worker"],
    },
    # Australia
    {
        "slug": "skills-in-demand-482",
        "name": "482 Skills in Demand",
        "country_code": "AU",
        "country_slug": "australia",
        "aliases": ["482", "subclass 482", "tss", "skills in demand", "482 skills in demand", "skills-in-demand-482"],
    },
    # Ireland
    {
        "slug": "critical-skills-employment-permit",
        "name": "Critical Skills Employment Permit",
        "country_code": "IE",
        "country_slug": "ireland",
        "aliases": ["critical skills", "critical skills employment permit", "critical-skills-employment-permit", "csep"],
    },
    # Netherlands
    {
        "slug": "highly-skilled-migrant",
        "name": "Highly Skilled Migrant",
        "country_code": "NL",
        "country_slug": "netherlands",
        "aliases": ["highly skilled migrant", "highly-skilled-migrant", "kennismigrant", "hsm"],
    },
    # Singapore
    {
        "slug": "employment-pass",
        "name": "Employment Pass",
        "country_code": "SG",
        "country_slug": "singapore",
        "aliases": ["employment pass", "employment-pass", "ep", "s pass", "compass"],
    },
    # UAE
    {
        "slug": "golden-visa",
        "name": "Golden Visa",
        "country_code": "AE",
        "country_slug": "uae",
        "aliases": ["golden visa", "golden-visa", "uae golden visa"],
    },
    {
        "slug": "employment-visa",
        "name": "Employment Visa",
        "country_code": "AE",
        "country_slug": "uae",
        "aliases": ["employment visa", "employment-visa", "green visa", "uae employment"],
    },
    # New Zealand
    {
        "slug": "accredited-employer-work-visa",
        "name": "Accredited Employer Work Visa",
        "country_code": "NZ",
        "country_slug": "new-zealand",
        "aliases": ["accredited employer", "aewv", "accredited employer work visa", "accredited-employer-work-visa"],
    },
]

# Lookup Maps
_COUNTRY_BY_SLUG: Dict[str, CanonicalCountry] = {c["slug"]: c for c in CANONICAL_COUNTRIES}
_COUNTRY_BY_CODE: Dict[str, CanonicalCountry] = {c["code"]: c for c in CANONICAL_COUNTRIES}

_COUNTRY_ALIAS_MAP: Dict[str, CanonicalCountry] = {}
for c in CANONICAL_COUNTRIES:
    _COUNTRY_ALIAS_MAP[c["slug"].lower()] = c
    _COUNTRY_ALIAS_MAP[c["code"].lower()] = c
    _COUNTRY_ALIAS_MAP[c["name"].lower()] = c
    for alias in c["aliases"]:
        _COUNTRY_ALIAS_MAP[alias.lower()] = c

_VISA_BY_SLUG: Dict[str, CanonicalVisaType] = {v["slug"]: v for v in CANONICAL_VISA_TYPES}

_VISA_ALIAS_MAP: Dict[str, CanonicalVisaType] = {}
for v in CANONICAL_VISA_TYPES:
    _VISA_ALIAS_MAP[v["slug"].lower()] = v
    _VISA_ALIAS_MAP[v["name"].lower()] = v
    for alias in v["aliases"]:
        _VISA_ALIAS_MAP[alias.lower()] = v


def find_country(query: Optional[str]) -> Optional[CanonicalCountry]:
    """Resolve a country by slug, ISO code, or common name."""
    if not query:
        return None
    cleaned = query.strip().lower()
    return _COUNTRY_ALIAS_MAP.get(cleaned)


def find_visa_type(query: Optional[str]) -> Optional[CanonicalVisaType]:
    """Resolve a visa type by slug, name, or alias."""
    if not query:
        return None
    cleaned = query.strip().lower()
    return _VISA_ALIAS_MAP.get(cleaned)


def match_visa_type_from_string(text: Optional[str]) -> Optional[CanonicalVisaType]:
    """Check if a string contains or matches any canonical visa type."""
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned in _VISA_ALIAS_MAP:
        return _VISA_ALIAS_MAP[cleaned]
    for alias, v in _VISA_ALIAS_MAP.items():
        if len(alias) >= 3 and alias in cleaned:
            return v
    return None

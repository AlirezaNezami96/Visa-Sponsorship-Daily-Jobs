"""Destination-country normalization for the overseas expansion pack.

Maps free-form location/city/country text found in job listings to a canonical
destination country. Shared by the adapter (setting ``job.country``) and the
visa stage (selecting the employer-sponsored ``visa_type``). The lexicon is
conservative: it only recognizes the overseas migration-corridor destinations
this actor targets (Gulf states, South/East Asia, plus Germany/UK/Canada/
Australia/NZ and a few common European corridors).
"""
from __future__ import annotations

import re
from typing import Optional

# keyword (lowercase) -> canonical destination country
# Longest-match-first ordering is applied at build time.
_LEXICON: dict = {
    # Gulf (GCC) — city and country synonyms
    "united arab emirates": "UAE",
    "uae": "UAE",
    "dubai": "UAE",
    "abu dhabi": "UAE",
    "sharjah": "UAE",
    "ajman": "UAE",
    "fujairah": "UAE",
    "ras al khaimah": "UAE",
    "umm al quwain": "UAE",
    "al ain": "UAE",
    "saudi arabia": "Saudi Arabia",
    "kingdom of saudi arabia": "Saudi Arabia",
    "ksa": "Saudi Arabia",
    "riyadh": "Saudi Arabia",
    "jeddah": "Saudi Arabia",
    "dammam": "Saudi Arabia",
    "al khobar": "Saudi Arabia",
    "khobar": "Saudi Arabia",
    "mecca": "Saudi Arabia",
    "medina": "Saudi Arabia",
    "tabuk": "Saudi Arabia",
    "qatar": "Qatar",
    "doha": "Qatar",
    "al rayyan": "Qatar",
    "kuwait": "Kuwait",
    "kuwait city": "Kuwait",
    "oman": "Oman",
    "sultanate of oman": "Oman",
    "muscat": "Oman",
    "sohar": "Oman",
    "salalah": "Oman",
    "bahrain": "Bahrain",
    "manama": "Bahrain",
    # South / East Asia
    "malaysia": "Malaysia",
    "kuala lumpur": "Malaysia",
    "johor bahru": "Malaysia",
    "penang": "Malaysia",
    "selangor": "Malaysia",
    "melaka": "Malaysia",
    "singapore": "Singapore",
    "japan": "Japan",
    "tokyo": "Japan",
    "osaka": "Japan",
    "nagoya": "Japan",
    "yokohama": "Japan",
    "kyoto": "Japan",
    "fukuoka": "Japan",
    "kobe": "Japan",
    "south korea": "South Korea",
    "korea (south)": "South Korea",
    "seoul": "South Korea",
    "busan": "South Korea",
    "incheon": "South Korea",
    "daegu": "South Korea",
    # Europe / Anglosphere destinations
    "germany": "Germany",
    "deutschland": "Germany",
    "berlin": "Germany",
    "munich": "Germany",
    "hamburg": "Germany",
    "frankfurt": "Germany",
    "cologne": "Germany",
    "stuttgart": "Germany",
    "dusseldorf": "Germany",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "london": "United Kingdom",
    "manchester": "United Kingdom",
    "birmingham": "United Kingdom",
    "glasgow": "United Kingdom",
    "edinburgh": "United Kingdom",
    "canada": "Canada",
    "toronto": "Canada",
    "vancouver": "Canada",
    "montreal": "Canada",
    "calgary": "Canada",
    "ottawa": "Canada",
    "edmonton": "Canada",
    "australia": "Australia",
    "sydney": "Australia",
    "melbourne": "Australia",
    "brisbane": "Australia",
    "perth": "Australia",
    "adelaide": "Australia",
    "gold coast": "Australia",
    "new zealand": "New Zealand",
    "auckland": "New Zealand",
    "wellington": "New Zealand",
    "christchurch": "New Zealand",
    # Two-letter ISO codes commonly emitted by JSON-LD addressCountry / RSS
    "ae": "UAE",
    "sa": "Saudi Arabia",
    "qa": "Qatar",
    "kw": "Kuwait",
    "om": "Oman",
    "bh": "Bahrain",
    "my": "Malaysia",
    "sg": "Singapore",
    "jp": "Japan",
    "kr": "South Korea",
    "gb": "United Kingdom",
    "nz": "New Zealand",
}

# Pre-compile, longest keys first so "kuala lumpur" beats "lumpur",
# "south korea" beats a bare city, etc.
_ORDERED_PATTERNS = []
for _kw in sorted(_LEXICON.keys(), key=len, reverse=True):
    _ORDERED_PATTERNS.append(
        (re.compile(r"(?<![a-z0-9])" + re.escape(_kw) + r"(?![a-z0-9])"), _LEXICON[_kw])
    )

del _kw

# Destinations that appear in the visa_type mapping (destination -> visa_type).
DESTINATION_VISA_TYPES: dict = {
    "UAE": "UAE Work Permit",
    "Saudi Arabia": "Saudi Work Visa (Iqama)",
    "Qatar": "Qatar Work Permit",
    "Kuwait": "Kuwait Work Visa",
    "Oman": "Oman Work Visa",
    "Bahrain": "Bahrain Work Visa",
    "Malaysia": "Malaysia Employment Pass",
    "Japan": "Japan Work Visa (SSW/Engineer)",
    "South Korea": "Korea EPS E-9 Visa",
    "Singapore": "Singapore Work Pass",
    "Germany": "Germany Work Visa / EU Blue Card",
    "United Kingdom": "UK Skilled Worker",
    "Canada": "Canada Work Permit (LMIA)",
    "Australia": "Australia TSS 482 Visa",
    "New Zealand": "NZ AEWV",
}

FALLBACK_VISA_TYPE = "Employer-sponsored work visa"


def normalize_destination(text: Optional[str]) -> Optional[str]:
    """Return the canonical destination country for a location string, or None.

    Case-insensitive, word-boundary matching, longest-phrase-first. Returns
    None when no known destination is recognized.
    """
    if not text:
        return None
    lowered = text.lower()
    for pattern, country in _ORDERED_PATTERNS:
        if pattern.search(lowered):
            return country
    return None


def visa_type_for_destination(country: Optional[str]) -> str:
    """Map a canonical destination country to its employer-sponsored visa type."""
    if not country:
        return FALLBACK_VISA_TYPE
    return DESTINATION_VISA_TYPES.get(country, FALLBACK_VISA_TYPE)

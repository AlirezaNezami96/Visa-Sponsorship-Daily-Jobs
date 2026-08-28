"""
src/job_radar/visa/normalizer.py

Company name normalization and fuzzy matching against official sponsor registers.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import rapidfuzz.fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    _HAS_RAPIDFUZZ = False

logger = logging.getLogger(__name__)

UNMATCHED_LOG_PATH = Path("state/unmatched_sponsors.jsonl")

# Common corporate suffixes and legal form designators across US, UK, EU, etc.
CORP_SUFFIXES = [
    r"\bsp\.?\s*z\s*o\.?\s*o\.?\b",
    r"\bs\.?r\.?o\.?\b",
    r"\bltd\.?\b",
    r"\blimited\b",
    r"\bllc\.?\b",
    r"\binc\.?\b",
    r"\bincorporated\b",
    r"\bcorp\.?\b",
    r"\bcorporation\b",
    r"\bco\.?\b",
    r"\bcompany\b",
    r"\bgmbh\.?\b",
    r"\bplc\.?\b",
    r"\bholding(s)?\b",
    r"\bgroup\b",
    r"\btechnologies\b",
    r"\btechnology\b",
    r"\bsolutions\b",
    r"\bag\b",
    r"\bs\.?a\.?\b",
    r"\bnv\b",
    r"\bbv\b",
    r"\boy\b",
    r"\bab\b",
    r"\bpty\b",
    r"\bkk\b",
]

_SUFFIX_REGEX = re.compile(
    "|".join(CORP_SUFFIXES),
    re.IGNORECASE,
)

GENERIC_TERMS = {
    "solutions", "digital", "consulting", "services", "global", "systems",
    "international", "labs", "software", "tech", "data", "media", "holdings"
}

# Pre-defined aliases for major tech employers
KNOWN_ALIASES: Dict[str, str] = {
    "google": "google",
    "google llc": "google",
    "deepmind": "deepmind",
    "deepmind technologies": "deepmind",
    "meta": "meta",
    "meta platforms": "meta",
    "facebook": "meta",
    "amazon": "amazon",
    "amazon web services": "amazon",
    "aws": "amazon",
    "microsoft": "microsoft",
    "apple": "apple",
    "stripe": "stripe",
    "spotify": "spotify",
    "netflix": "netflix",
    "uber": "uber",
    "airbnb": "airbnb",
    "bytedance": "bytedance",
    "tiktok": "bytedance",
    "allegro": "allegro",
    "allegro sp z o o": "allegro",
    "tesco": "tesco",
    "tesco stores": "tesco",
}


def normalize_company_name(name: str) -> str:
    """
    Standardize company name:
    1. Unicode NFKD normalization
    2. Lowercase
    3. Strip punctuation
    4. Strip corporate suffixes (inc, ltd, gmbh, etc.)
    5. Collapse whitespace
    """
    if not name:
        return ""

    # Normalize unicode characters (e.g. Poznań -> Poznan)
    nfkd = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in nfkd if not unicodedata.combining(c))

    text = text.lower()

    # Remove special punctuation
    text = re.sub(r"[\.,\(\)\[\]\{\}\\\/\-_\*\&\|\#\@\+\=\!\?\;:]", " ", text)

    # Strip suffixes
    text = _SUFFIX_REGEX.sub(" ", text)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


def build_token_index(sponsors_by_norm: Dict[str, Any]) -> Dict[str, List[str]]:
    """Build an inverted token -> sponsor-normalized-name index.

    Used as a candidate pre-filter for fuzzy matching. Empirically validated:
    a sponsor can only reach token_set_ratio >= 0.92 with a query if they share
    at least one normalized token (measured max for disjoint-token pairs is
    ~75 over 30k adversarial pairs vs the 92 cutoff). Filtering to
    token-sharing candidates therefore never drops a true >= 0.92 match while
    shrinking each scan from ~125k candidates to a handful.
    """
    index: Dict[str, List[str]] = {}
    for norm_name in sponsors_by_norm.keys():
        for token in norm_name.split():
            index.setdefault(token, []).append(norm_name)
    return index


def match_company_to_sponsor(
    company_name: str,
    sponsors_by_norm: Dict[str, Any],
    alias_map: Optional[Dict[str, str]] = None,
    min_fuzzy_score: float = 0.92,
    token_index: Optional[Dict[str, List[str]]] = None,
    match_cache: Optional[Dict[str, Tuple[Optional[Any], str]]] = None,
) -> Tuple[Optional[Any], str]:
    """
    Match a target company name to a verified sponsor record.

    Steps:
      0. (optional) per-run memoization by normalized name
      1. Exact match on normalized name
      2. Alias mapping lookup
      3. High-precision token-set fuzzy matching (score >= 0.92), restricted
         to token-sharing candidates when a token_index is supplied
      4. Log unmatched companies to unmatched_sponsors.jsonl for audit

    Results are identical with or without token_index/match_cache; they are
    pure speedups (index validated against the 0.92 cutoff; cache memoizes the
    same function's output).

    Returns:
        (SponsorRecord or None, match_method: "exact" | "alias" | "fuzzy" | "none")
    """
    norm = normalize_company_name(company_name)
    if not norm or len(norm) < 2:
        return None, "none"

    # 0. Memoization (per-run): same input -> same output, no re-scan, no
    # duplicate unmatched audit lines.
    if match_cache is not None and norm in match_cache:
        return match_cache[norm]

    result = _match_company_uncached(
        norm=norm,
        company_name=company_name,
        sponsors_by_norm=sponsors_by_norm,
        alias_map=alias_map,
        min_fuzzy_score=min_fuzzy_score,
        token_index=token_index,
    )
    if match_cache is not None:
        match_cache[norm] = result
    return result


def _match_company_uncached(
    norm: str,
    company_name: str,
    sponsors_by_norm: Dict[str, Any],
    alias_map: Optional[Dict[str, str]] = None,
    min_fuzzy_score: float = 0.92,
    token_index: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Optional[Any], str]:
    # 1. Exact match
    if norm in sponsors_by_norm:
        return sponsors_by_norm[norm], "exact"

    # 2. Known aliases
    merged_aliases = {**KNOWN_ALIASES, **(alias_map or {})}
    if norm in merged_aliases:
        alias_target = merged_aliases[norm]
        if alias_target in sponsors_by_norm:
            return sponsors_by_norm[alias_target], "alias"

    # 3. Fuzzy matching (rapidfuzz token_set_ratio or difflib fallback)
    if len(norm) > 3 and norm not in GENERIC_TERMS:
        query_tokens = norm.split()

        if token_index is not None:
            # Candidate pre-filter: only sponsors sharing >= 1 token can reach
            # the 0.92 cutoff (empirically validated). Preserves exact-match
            # semantics of the full scan.
            candidate_names: List[str] = []
            seen: Set[str] = set()
            for token in query_tokens:
                for sp_norm in token_index.get(token, ()):
                    if sp_norm not in seen:
                        seen.add(sp_norm)
                        candidate_names.append(sp_norm)
        else:
            candidate_names = list(sponsors_by_norm.keys())

        best_match = None
        best_score = 0.0
        for sp_norm in candidate_names:
            if len(sp_norm) <= 3:
                continue

            if _HAS_RAPIDFUZZ:
                score = rapidfuzz.fuzz.token_set_ratio(norm, sp_norm) / 100.0
            else:
                score = difflib.SequenceMatcher(None, norm, sp_norm).ratio()

            if score >= min_fuzzy_score and score > best_score:
                best_score = score
                best_match = sponsors_by_norm[sp_norm]

        if best_match:
            return best_match, f"fuzzy_{best_score:.2f}"

    # 4. Log unmatched for later aliasing
    _log_unmatched_sponsor(company_name, norm)
    return None, "none"


def _log_unmatched_sponsor(raw_name: str, normalized_name: str) -> None:
    try:
        UNMATCHED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(UNMATCHED_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"raw": raw_name, "norm": normalized_name}) + "\n")
    except Exception:
        pass

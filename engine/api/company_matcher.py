"""
Company Name Normalization & Trigram Fuzzy Matching Engine for VisaLane Extension Lookup.
Provides robust cleaning of real-world messy company names (e.g. from LinkedIn, Indeed, Glassdoor),
legal suffix removal, trigram similarity scoring, and strict false-positive suppression.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

# Pre-normalization replacements for dotted abbreviations and special forms
DOTTED_ABBREVIATIONS = [
    (r"\bl\.l\.c\.?\b", "llc"),
    (r"\bl\.t\.d\.?\b", "ltd"),
    (r"\bi\.n\.c\.?\b", "inc"),
    (r"\bc\.o\.r\.p\.?\b", "corp"),
    (r"\bg\.m\.b\.h\.?\b", "gmbh"),
    (r"\bb\.v\.?\b", "bv"),
    (r"\bn\.v\.?\b", "nv"),
    (r"\ba\.g\.?\b", "ag"),
    (r"\bs\.e\.?\b", "se"),
    (r"\bs\.a\.r\.l\.?\b", "sarl"),
    (r"\bs\.r\.l\.?\b", "srl"),
    (r"\bs\.a\.s\.?\b", "sas"),
    (r"\bs\.a\.?\b", "sa"),
    (r"\bs\.l\.?\b", "sl"),
    (r"\bp\.l\.c\.?\b", "plc"),
    (r"\bp\.t\.y\.?\b", "pty"),
    (r"\bpte\.?\s*ltd\.?\b", "pte ltd"),
    (r"\bpty\.?\s*ltd\.?\b", "pty ltd"),
    (r"\bsp\.?\s*z\s*o\.?\s*o\.?\b", "sp zoo"),
]

# Corporate entity and legal suffixes to strip (ordered by length descending)
LEGAL_SUFFIX_PATTERNS = [
    r"\blimited liability company\b",
    r"\bpublic limited company\b",
    r"\bcorporation\b",
    r"\bincorporated\b",
    r"\btechnologies\b",
    r"\btechnology\b",
    r"\bsolutions\b",
    r"\bservices\b",
    r"\bholdings\b",
    r"\bholding\b",
    r"\bcompany\b",
    r"\blimited\b",
    r"\bgroup\b",
    r"\binternational\b",
    r"\bglobal\b",
    r"\bdeutschland\b",
    r"\bgermany\b",
    r"\bnetherlands\b",
    r"\bireland\b",
    r"\beurope\b",
    r"\bsweden\b",
    r"\bfrance\b",
    r"\bpte\s+ltd\b",
    r"\bpty\s+ltd\b",
    r"\bsp\s+zoo\b",
    r"\bpty\b",
    r"\bllc\b",
    r"\bltd\b",
    r"\binc\b",
    r"\bcorp\b",
    r"\bgmbh\b",
    r"\bsarl\b",
    r"\bsrl\b",
    r"\bsas\b",
    r"\bplc\b",
    r"\bcie\b",
    r"\bkg\b",
    r"\bug\b",
    r"\bco\b",
    r"\bbv\b",
    r"\bnv\b",
    r"\bag\b",
    r"\bse\b",
    r"\bsa\b",
    r"\bsl\b",
    r"\bab\b",
    r"\bas\b",
    r"\boy\b",
    r"\bb\s+v\b",
    r"\bn\s+v\b",
    r"\bs\s+a\b",
    r"\ba\s+g\b",
    r"\bs\s+e\b",
    r"\busa\b",
    r"\bus\b",
    r"\buk\b",
]

# Known parent/subsidiary aliases or direct mappings
KNOWN_COMPANY_ALIASES: Dict[str, str] = {
    "aws": "amazon",
    "amazon web services": "amazon",
    "amazon web services aws": "amazon",
    "aws amazon web services": "amazon",
    "meta platforms": "meta",
    "facebook": "meta",
    "facebook meta": "meta",
    "instagram": "meta",
    "whatsapp": "meta",
    "google cloud": "google",
    "deepmind": "google",
    "google deepmind": "google",
    "microsoft corporation": "microsoft",
    "apple inc": "apple",
    "uber technologies": "uber",
    "twitter": "x",
    "stripe payments": "stripe",
    "stripe payments europe": "stripe",
    "spotify usa": "spotify",
    "spotify ab": "spotify",
    "mckinsey and": "mckinsey",
}


def normalize_company_name(name: Optional[str]) -> str:
    """
    Normalizes a messy company name string.
    - Strips accents/diacritics
    - Resolves dotted legal abbreviations (e.g. B.V. -> bv, S.A. -> sa)
    - Removes parenthetical additions like (AWS), [HQ], (US), (UK)
    - Strips punctuation and legal/corporate suffixes (Inc, LLC, Ltd, GmbH, etc.)
    - Removes trailing geographical designations and hanging conjunctions
    - Collapses excess whitespace
    """
    if not name or not isinstance(name, str):
        return ""

    # 1. Unicode normalization (NFKD to decompose accents, e.g. é -> e)
    n = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8").lower().strip()

    # 2. Pre-process dotted abbreviations before stripping periods
    for pattern, replacement in DOTTED_ABBREVIATIONS:
        n = re.sub(pattern, f" {replacement} ", n, flags=re.IGNORECASE)

    # 3. Handle parentheticals (check for alias like Facebook (Meta))
    parenthetical_match = re.search(r"[\(\[\{](.*?)[\)\]\}]", n)
    parenthetical_text = parenthetical_match.group(1).strip() if parenthetical_match else ""

    n = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", n)

    # 4. Replace common separators (&, +, /, @) with space or standard word
    n = n.replace("&", " and ")
    n = re.sub(r"[\.,;:_\-\/\\\|\+\*#~`!?'\"@\$\^\=\<\>]", " ", n)

    # 5. Remove leading/trailing numbers or bullet artifacts
    n = re.sub(r"^\d+[\.\-\s]+", "", n)

    # 6. Iteratively strip legal and corporate entity suffixes until stable
    prev_str = ""
    cleaned_str = n
    for _ in range(3):
        if prev_str == cleaned_str:
            break
        prev_str = cleaned_str
        for pattern in LEGAL_SUFFIX_PATTERNS:
            cleaned_str = re.sub(pattern, " ", cleaned_str, flags=re.IGNORECASE)
        cleaned_str = " ".join(cleaned_str.split())

    # 7. Strip trailing conjunctions/prepositions (e.g. "mckinsey and" -> "mckinsey")
    cleaned_str = re.sub(r"\b(and|the|of)\s*$", "", cleaned_str, flags=re.IGNORECASE)

    # 8. Re-clean extra spaces
    cleaned_words = [w for w in cleaned_str.split() if w]
    final_norm = " ".join(cleaned_words).strip()

    # 9. Check alias table
    if final_norm in KNOWN_COMPANY_ALIASES:
        return KNOWN_COMPANY_ALIASES[final_norm]

    # Check parenthetical alias fallback (e.g. "Facebook (Meta)")
    if parenthetical_text in KNOWN_COMPANY_ALIASES:
        return KNOWN_COMPANY_ALIASES[parenthetical_text]

    return final_norm or name.strip().lower()


def generate_trigrams(text: str) -> Set[str]:
    """Generate padded character trigrams for a string."""
    if not text:
        return set()
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def calculate_trigram_similarity(str1: str, str2: str) -> float:
    """
    Calculates Sørensen-Dice trigram similarity between two strings.
    Returns float in range [0.0, 1.0].
    """
    if not str1 or not str2:
        return 0.0
    if str1 == str2:
        return 1.0

    tri1 = generate_trigrams(str1)
    tri2 = generate_trigrams(str2)

    total_trigrams = len(tri1) + len(tri2)
    if total_trigrams == 0:
        return 0.0

    intersection = len(tri1 & tri2)
    return round((2.0 * intersection) / total_trigrams, 4)


def calculate_token_similarity(norm1: str, norm2: str) -> float:
    """Calculates word token overlap and prefix containment score."""
    if not norm1 or not norm2:
        return 0.0
    if norm1 == norm2:
        return 1.0

    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())

    if not tokens1 or not tokens2:
        return 0.0

    # If one token set is entirely contained within the other
    if tokens1.issubset(tokens2) or tokens2.issubset(tokens1):
        min_len = min(len(tokens1), len(tokens2))
        max_len = max(len(tokens1), len(tokens2))
        return round(min_len / max_len, 4)

    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    return round(intersection / union, 4)


def match_company_fuzzy(
    query_name: str,
    candidates: List[Dict[str, Any]],
    threshold: float = 0.70,
) -> Tuple[Optional[Dict[str, Any]], float, str]:
    """
    Find the best matching company from candidate list using normalized trigram + token similarity.
    Returns (best_matched_candidate_dict, match_score, normalized_query).
    
    Guarantees:
    - Never returns low-confidence matches (< threshold).
    - Prevents false-positive substring matches (e.g. 'Apple' vs 'Pineapple').
    - Handles messy corporate suffixes (e.g. 'Stripe Payments Europe, Ltd.' -> 'Stripe').
    """
    norm_query = normalize_company_name(query_name)
    if not norm_query:
        return None, 0.0, ""

    best_candidate: Optional[Dict[str, Any]] = None
    best_score: float = 0.0

    for cand in candidates:
        cand_name = cand.get("name") or cand.get("company_name") or ""
        norm_cand = normalize_company_name(cand_name)

        # 1. Exact normalized match (instant 1.0)
        if norm_query == norm_cand:
            return cand, 1.0, norm_query

        # 2. Check candidate aliases
        cand_aliases = cand.get("aliases") or []
        for alias in cand_aliases:
            if norm_query == normalize_company_name(alias):
                return cand, 1.0, norm_query

        # 3. Trigram Dice Similarity
        trigram_score = calculate_trigram_similarity(norm_query, norm_cand)

        # 4. Token Overlap Score
        token_score = calculate_token_similarity(norm_query, norm_cand)

        # Weighted combined score (favoring trigrams with token boost for multi-word names)
        combined_score = round(max(trigram_score, (trigram_score * 0.6 + token_score * 0.4)), 4)

        # False-positive guard: If one name is short (<= 5 chars) and doesn't match exactly,
        # require very high trigram score (>= 0.85) to avoid 'apple' matching 'pineapple'
        if min(len(norm_query), len(norm_cand)) <= 5 and combined_score < 0.85:
            # Check if one is a completely different word
            query_words = set(norm_query.split())
            cand_words = set(norm_cand.split())
            if not query_words.intersection(cand_words):
                continue

        if combined_score > best_score:
            best_score = combined_score
            best_candidate = cand

    if best_score >= threshold and best_candidate is not None:
        return best_candidate, best_score, norm_query

    return None, best_score, norm_query

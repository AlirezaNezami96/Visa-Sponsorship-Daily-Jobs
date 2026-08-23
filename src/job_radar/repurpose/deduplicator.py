"""Deduplication and Content Normalization Engine.

Provides multi-level deduplication:
  1. Deterministic Content Normalization (Unicode, URLs, whitespace, lowercase)
  2. Exact Duplicate Detection via SHA-256 content hashing
  3. Near-Duplicate Detection via token Jaccard & sequence similarity
  4. Media-aware composite fingerprinting
"""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Common URL tracking parameters to strip
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "trk", "trackingid", "rcm", "originalsubdomain", "midtoken", "ek",
    "li_fat_id", "fbclid", "gclid", "ref", "source", "ref_id",
}


class ContentDeduplicator:
    """Handles text normalization and multi-tier duplicate detection."""

    @staticmethod
    def clean_url(url: str) -> str:
        """Strips tracking query parameters from URLs."""
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query, keep_blank_values=False)
            filtered = {
                k: v for k, v in query_params.items()
                if k.lower() not in TRACKING_PARAMS
            }
            new_query = urlencode(filtered, doseq=True)
            clean_parsed = parsed._replace(query=new_query, fragment="")
            return urlunparse(clean_parsed).rstrip("/")
        except Exception:
            return url.strip()

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """
        Applies rigorous deterministic text normalization:
          - Unicode NFKD normalization
          - Lowercasing
          - Clean tracking parameters from embedded URLs
          - Normalizing line endings and collapsing repeated whitespace
        """
        if not text:
            return ""

        # 1. Unicode NFKD normalization & lowercase
        norm = unicodedata.normalize("NFKD", text).lower()

        # 2. Clean URLs within text
        def replace_url(match):
            return cls.clean_url(match.group(0))

        norm = re.sub(r"https?://[^\s]+", replace_url, norm)

        # 3. Normalize line endings
        norm = norm.replace("\r\n", "\n").replace("\r", "\n")

        # 4. Collapse consecutive spaces / tabs within lines
        norm = re.sub(r"[ \t]+", " ", norm)

        # 5. Collapse 3+ consecutive newlines to double newline
        norm = re.sub(r"\n{3,}", "\n\n", norm)

        # 6. Trim leading/trailing whitespace
        return norm.strip()

    @classmethod
    def compute_content_hash(cls, text: str) -> str:
        """Computes SHA-256 hash of normalized text."""
        normalized = cls.normalize_text(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def tokenize(cls, text: str) -> Set[str]:
        """Extracts set of alphanumeric word tokens from normalized text."""
        normalized = cls.normalize_text(text)
        tokens = re.findall(r"\b[a-z0-9_]{3,}\b", normalized)
        return set(tokens)

    @classmethod
    def token_jaccard_similarity(cls, text_a: str, text_b: str) -> float:
        """Calculates token Jaccard similarity score between two texts."""
        tokens_a = cls.tokenize(text_a)
        tokens_b = cls.tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        return len(intersection) / len(union) if union else 0.0

    @classmethod
    def sequence_similarity(cls, text_a: str, text_b: str) -> float:
        """Calculates character sequence similarity ratio."""
        norm_a = cls.normalize_text(text_a)
        norm_b = cls.normalize_text(text_b)
        if not norm_a or not norm_b:
            return 0.0
        return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()

    @classmethod
    def is_near_duplicate(
        cls,
        candidate_text: str,
        existing_texts: List[Tuple[str, str]],  # List of (post_id, text)
        jaccard_threshold: float = 0.85,
        sequence_threshold: float = 0.88,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Checks if candidate_text is a near-duplicate of any existing text.
        Returns: (is_duplicate, matched_post_id, highest_score)
        """
        highest_score = 0.0
        matched_id = None

        cand_tokens = cls.tokenize(candidate_text)
        if not cand_tokens:
            return False, None, 0.0

        for post_id, existing_text in existing_texts:
            # Quick token Jaccard check first
            ex_tokens = cls.tokenize(existing_text)
            if not ex_tokens:
                continue

            jaccard = len(cand_tokens.intersection(ex_tokens)) / len(cand_tokens.union(ex_tokens))
            if jaccard > highest_score:
                highest_score = jaccard
                matched_id = post_id

            if jaccard >= jaccard_threshold:
                return True, post_id, jaccard

            # Detailed sequence similarity if Jaccard is promising (>= 0.70)
            if jaccard >= 0.70:
                seq_ratio = cls.sequence_similarity(candidate_text, existing_text)
                if seq_ratio > highest_score:
                    highest_score = seq_ratio
                    matched_id = post_id
                if seq_ratio >= sequence_threshold:
                    return True, post_id, seq_ratio

        return False, matched_id, highest_score

    @classmethod
    def compute_composite_fingerprint(
        cls,
        content: str,
        media_urls: Optional[List[str]] = None,
    ) -> str:
        """Generates a composite fingerprint combining content and media URLs."""
        c_hash = cls.compute_content_hash(content)
        if not media_urls:
            return c_hash

        clean_media = sorted([cls.clean_url(u) for u in media_urls if u])
        media_str = "|".join(clean_media)
        m_hash = hashlib.sha256(media_str.encode("utf-8")).hexdigest()[:16]
        return f"{c_hash}:{m_hash}"

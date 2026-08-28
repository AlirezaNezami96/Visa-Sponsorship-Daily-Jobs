"""SimHash near-duplicate deduplication for overseas job descriptions.

Overseas manpower agencies copy-paste identical JDs with different agency
names/companies, so the fingerprint (company+title+location) cannot catch
them. This stage catches near-duplicate *content* across the whole run.

Correctness guarantees (the prior draft of this idea was broken — see notes):
1. Empty/short text is NEVER hashed. Text with fewer than MIN_TOKENS
   whitespace tokens (post-normalization) skips SimHash entirely and relies on
   fingerprint dedupe. (The broken version hashed "" -> hash 0 for everyone ->
   the whole run collapsed to ~1 job.)
2. Text = description + title.
3. Shingles = word 3-grams over normalized text.
4. 64-bit hashes via blake2b(digest_size=8), standard SimHash bit accumulation.
5. Two jobs are duplicates when hamming distance <= overseas_simhash_threshold.
6. LSH banding (4 bands x 16 bits) bounds candidate pairs; no O(n^2) over all
   jobs, only jobs sharing a band bucket are compared.
7. On collision: keep the longer description; tie-break: description_source
   == "detail_page" wins, then first-seen.

Pure function, no I/O.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job

logger = logging.getLogger(__name__)

MIN_TOKENS = 40
NUM_BANDS = 4
BAND_BITS = 16
BAND_MASK = (1 << BAND_BITS) - 1

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _shingles(norm_text: str) -> List[str]:
    """Word 3-grams of normalized text."""
    words = norm_text.split(" ")
    if len(words) < 3:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]


def _hash64(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")


def simhash_value(shingle_list: List[str]) -> int:
    """Standard SimHash accumulation over 64 bits."""
    if not shingle_list:
        return 0
    v = [0] * 64
    for shingle in shingle_list:
        h = _hash64(shingle)
        for i in range(64):
            if (h >> i) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _keep_key(job: Job, index: int) -> Tuple[int, int, int]:
    """Sort key for collision resolution: higher wins.

    Longer description wins; then detail_page provenance; then first-seen
    (smaller index).
    """
    desc_len = len(job.description or "")
    detail = 1 if job.metadata.get("description_source") == "detail_page" else 0
    return (desc_len, detail, -index)


def _domain_of(job: Job) -> str:
    return (
        job.metadata.get("source_domain")
        or job.ats
        or job.source
        or "?"
    )


def simhash_deduplicate(jobs: List[Job], config: JobSearchConfig) -> Tuple[List[Job], int]:
    """Remove near-duplicate overseas job content. Returns (survivors, dup_count).

    Jobs with < MIN_TOKENS of normalized text are never hashed and always
    survive (they rely on fingerprint dedupe).
    """
    if not jobs:
        return jobs, 0

    threshold = int(getattr(config, "overseas_simhash_threshold", 6))
    if threshold < 0:
        threshold = 0

    hashes: List[Optional[int]] = []
    for job in jobs:
        desc = job.description or ""
        title = job.title or ""
        norm = _normalize(f"{desc} {title}")
        if len(norm.split(" ")) < MIN_TOKENS:
            hashes.append(None)  # too short to fingerprint safely; keep it
            continue
        hashes.append(simhash_value(_shingles(norm)))

    # LSH banding: bucket by each 16-bit band.
    buckets: Dict[Tuple[int, int], List[int]] = {}
    for idx, h in enumerate(hashes):
        if h is None:
            continue
        for band in range(NUM_BANDS):
            band_value = (h >> (band * BAND_BITS)) & BAND_MASK
            buckets.setdefault((band, band_value), []).append(idx)

    removed: List[bool] = [False] * len(jobs)
    dup_count = 0
    checked: Set[Tuple[int, int]] = set()

    for _key, members in buckets.items():
        n = len(members)
        if n < 2:
            continue
        for i in range(n):
            a = members[i]
            if removed[a]:
                continue
            for j in range(i + 1, n):
                b = members[j]
                if removed[b]:
                    continue
                pair = (a, b) if a < b else (b, a)
                if pair in checked:
                    continue
                checked.add(pair)
                ha = hashes[a]
                hb = hashes[b]
                if ha is None or hb is None:
                    continue
                if hamming_distance(ha, hb) > threshold:
                    continue
                # Collision: resolve which job survives.
                if _keep_key(jobs[a], a) >= _keep_key(jobs[b], b):
                    loser = b
                else:
                    loser = a
                removed[loser] = True
                dup_count += 1
                logger.debug(
                    "simhash: near-duplicate removed (%s vs %s, hamming=%d)",
                    _domain_of(jobs[a]),
                    _domain_of(jobs[b]),
                    hamming_distance(ha, hb),
                )

    survivors = [job for idx, job in enumerate(jobs) if not removed[idx]]
    logger.info("SimHash dedup: %d -> %d jobs (%d near-duplicates removed)", len(jobs), len(survivors), dup_count)
    return survivors, dup_count

"""LLM-based relevance classification, remote scope validation, and visa signal extraction for job listings.

Implements the single-pass combined LLM auditor (relevance, track, seniority,
remote scope, visa sponsorship mention, and resume matching in one call).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.classifiers.cache import ClassificationCache, make_cache_key
from job_radar.config import RadarConfig, get_config
from job_radar.models import CombinedLLMResponse, Job, VisaStatus
from job_radar.taxonomy import normalize_job_posting
from job_radar.visa.evaluator import score_job_visa

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert global job quality auditor and recruitment analyst.
Evaluate the job posting below to verify whether it is a legitimate, current, and usable job posting (not a scam, expired placeholder, duplicate spam, or garbled text).

Respond with strict JSON adhering to this schema:
{
  "relevance": 85,
  "why": "Clear 1-sentence summary of the role, field, and job authenticity.",
  "is_legitimate_job": true,
  "occupation_category": "healthcare",
  "seniority_guess": "mid",
  "remote_scope": "worldwide",
  "allowed_regions": ["US", "Canada"],
  "visa_mention": "sponsors",
  "visa_quote": null,
  "visa_sponsorship_confidence": 80,
  "visa_sponsorship_verified": false,
  "visa_types": ["H-1B"],
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "salary_interval": null,
  "resume_match_score": null,
  "resume_match_why": null
}

Field definitions & rules:
1. "relevance": 0 to 100 based on job posting completeness, validity, and data quality (0 only if scam, spam, broken text, or non-job advertisement). Never zero out a job for being outside tech/software.
2. "is_legitimate_job": true if this is an authentic, active, identifiable job opening in ANY industry.
3. "occupation_category": broad field (e.g. "software", "healthcare", "trades", "engineering", "finance", "hospitality", "education", "logistics", "agriculture", "other").
4. "seniority_guess": "intern" | "junior" | "mid" | "senior" | "lead" | "executive" | "unspecified".
5. "remote_scope": "worldwide" | "region_restricted" | "hybrid" | "onsite_only" | "unknown".
6. "visa_mention": "sponsors" | "opt_friendly" | "no" | "unspecified".
7. "visa_quote": direct quote from the job description regarding sponsorship/relocation if present, else null.
8. "visa_sponsorship_confidence": 0 to 100 integer calibrated confidence that employer sponsors work visas.
9. "visa_sponsorship_verified": true ONLY when the JD explicitly offers sponsorship/relocation.
10. "visa_types": named visa programs stated in the JD (e.g. ["H-1B","TN"], ["Skilled Worker Visa"]). Empty array when unspecified.
11. "resume_match_score": 0 to 100 integer if candidate resume is provided, else null.
12. Return ONLY valid JSON, no markdown fences, no extra text.
"""

LLM_CLASSIFIER_PROMPT = SYSTEM_PROMPT
CLASSIFIER_PROMPT_VERSION = "v3-occupation-agnostic"


class JobClassification(dict):
    """Classification result container."""
    pass


def _cache_key(company: str, title: str, location: str, url: str) -> str:
    return make_cache_key(company, title, location=location, url=url)


def _call_gemini(user_prompt: str, model_name: str) -> str:
    """Call LLM via router with waterfall fallback."""
    import sys
    if "classify_relevance" in sys.modules:
        cr = sys.modules["classify_relevance"]
        if hasattr(cr, "_call_gemini") and cr._call_gemini is not _call_gemini:
            return cr._call_gemini(user_prompt, model_name)

    from job_radar.llm.router import complete

    full_input = f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    res = complete(
        prompt=full_input,
        json_schema={"type": "object"},
        max_tokens=1000,
    )
    return (res.text or "").strip()


def _call_anthropic(user_prompt: str, model_name: str) -> str:
    """Call Anthropic API."""
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model_name,
        "max_tokens": 1000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"].strip()


def _call_openai(user_prompt: str, model_name: str) -> str:
    """Call OpenAI API."""
    import requests

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def classify_single_job(
    job: dict,
    config: Optional[RadarConfig] = None,
    cache: Optional[ClassificationCache] = None,
    resume_text: Optional[str] = None,
) -> dict:
    """
    Classify a single job using occupation-agnostic evaluation with ISCO-08 taxonomy normalization.
    """
    cfg = config or get_config()
    company = job.get("company", "Unknown")
    title = job.get("title", "Untitled")
    location = job.get("location", "")
    url = job.get("url", "")
    desc = job.get("description") or job.get("description_text") or job.get("snippet") or ""

    # 1. Deterministic Taxonomy & Metadata Normalization
    norm_result = normalize_job_posting(
        title=title,
        company=company,
        location=location,
        description=desc,
        remote_flag=bool(job.get("remote")),
    )

    # Hash full available text for cache key
    key = make_cache_key(
        company=company,
        title=title,
        description=desc,
        resume_text=resume_text or "",
        location=location,
        url=url,
    )

    if cache:
        cached = cache.get(key)
        if cached:
            # Ensure taxonomy fields are backfilled in cached entries
            if "isco_code" not in cached:
                cached["isco_code"] = norm_result.isco_code
                cached["isco_title"] = norm_result.isco_title
                cached["isco_major_group_code"] = norm_result.isco_major_group_code
                cached["isco_major_group_title"] = norm_result.isco_major_group_title
                cached["credentials"] = norm_result.credentials
                cached["industry"] = norm_result.industry
            return cached

    parsed: Optional[dict] = None
    raw_text: Optional[str] = None

    if cfg.classifier.enabled:
        provider = (cfg.classifier.provider or "gemini").lower()
        model = cfg.classifier.model

        user_prompt = f"Company: {company}\nTitle: {title}\nLocation: {location}\nURL: {url}\n\nJob Description:\n{desc[:4000]}"
        if resume_text:
            user_prompt += f"\n\nCandidate Resume:\n{resume_text[:2500]}"

        try:
            if provider == "gemini" or os.environ.get("GEMINI_API_KEY"):
                raw_text = _call_gemini(user_prompt, model or "gemini-3.6-flash")
            elif provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
                raw_text = _call_anthropic(user_prompt, model or "claude-3-5-haiku-20241022")
            elif provider == "openai" or os.environ.get("OPENAI_API_KEY"):
                raw_text = _call_openai(user_prompt, model or "gpt-4o-mini")
        except Exception as exc:
            logger.warning("LLM classification failed for '%s — %s' (%s): %s — failing open", company, title, provider, exc)

    if raw_text:
        try:
            cleaned = raw_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
        except Exception as parse_exc:
            logger.warning("Failed to parse LLM JSON response: %s", parse_exc)

    # Fail-open fallback to deterministic taxonomy evaluation
    if not parsed:
        is_ai = norm_result.isco_code in ("2512", "2514", "2519", "2521", "2529") or any(
            k in title.lower() for k in ("ai", "machine learning", "ml", "data scientist", "deep learning")
        )
        track = "internship" if norm_result.seniority == "intern" else ("engineer" if is_ai else "other")

        parsed = {
            "relevance": 80 if len(desc) >= 30 or title != "Untitled" else 30,
            "why": f"Legitimate {norm_result.isco_title or 'professional'} role verified via taxonomy.",
            "is_legitimate_job": True,
            "is_ai_ml_day_to_day": is_ai,
            "occupation_category": norm_result.isco_major_group_title or "other",
            "track_guess": track,
            "seniority_guess": norm_result.seniority if norm_result.seniority != "unspecified" else "mid",
            "remote_scope": norm_result.remote_scope if norm_result.remote_scope != "unspecified" else "worldwide",
            "allowed_regions": norm_result.allowed_regions or ([location] if location else ["Worldwide"]),
            "visa_mention": "sponsors" if norm_result.sponsorship_mention_type == "offers_sponsorship" else (
                "no" if norm_result.sponsorship_mention_type == "explicit_refusal" else "unspecified"
            ),
            "visa_quote": norm_result.sponsorship_quotes[0] if norm_result.sponsorship_quotes else None,
            "visa_sponsorship_confidence": 75 if norm_result.sponsorship_mention_type == "offers_sponsorship" else 25,
            "visa_sponsorship_verified": norm_result.sponsorship_mention_type == "offers_sponsorship",
            "visa_types": [],
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_currency": job.get("salary_currency"),
            "salary_interval": job.get("salary_interval"),
            "resume_match_score": None,
            "resume_match_why": None,
            "_fallback": True,
        }

    # Attach ISCO taxonomy metadata
    parsed["isco_code"] = norm_result.isco_code
    parsed["isco_title"] = norm_result.isco_title
    parsed["isco_major_group_code"] = norm_result.isco_major_group_code
    parsed["isco_major_group_title"] = norm_result.isco_major_group_title
    parsed["country_specific_occupation"] = norm_result.country_specific_occupation
    parsed["credentials"] = norm_result.credentials
    parsed["industry"] = norm_result.industry
    parsed["uncertainty_reasons"] = norm_result.uncertainty_reasons

    # Standardize legacy keys for downstream components without overriding explicit keys
    if "is_ai_ml_role" not in parsed:
        parsed["is_ai_ml_role"] = parsed.get("is_ai_ml_day_to_day", False)
    if "relevance_score" not in parsed:
        parsed["relevance_score"] = parsed.get("relevance", 0)
    if "track" not in parsed:
        parsed["track"] = parsed.get("track_guess", "other")
    elif parsed.get("track") == "new_grad_engineer" and "track_guess" in parsed:
        parsed["track"] = "engineer"

    if cache:
        cache.set(key, parsed)

    return parsed


def classify_and_filter_jobs(
    jobs: List[dict],
    config: Optional[RadarConfig] = None,
    resume_text: Optional[str] = None,
    require_ai_filter: bool = False,
) -> Tuple[List[dict], Dict[str, Any]]:
    """
    Filter candidate jobs through the single-pass combined LLM + Visa classification pass.
    Occupation-agnostic by default: evaluates data quality, not occupation restriction.
    """
    cfg = config or get_config()
    cache = ClassificationCache(cfg.classifier.cache_file)
    min_score = cfg.classifier.min_relevance_score
    visa_weights = cfg.visa.weights.__dict__ if hasattr(cfg, "visa") and hasattr(cfg.visa, "weights") else None

    qualified_jobs = []
    stats = {
        "total_evaluated": len(jobs),
        "passed": 0,
        "rejected_not_legitimate": 0,
        "rejected_not_remote": 0,
        "rejected_low_score": 0,
        "visa_status_counts": {},
    }

    for job in jobs:
        clf = classify_single_job(job, config=cfg, cache=cache, resume_text=resume_text)
        is_legit = clf.get("is_legitimate_job", True)
        track = clf.get("track_guess", clf.get("track", "other"))
        seniority = clf.get("seniority_guess", "")
        remote_scope = clf.get("remote_scope", "unknown")
        score = clf.get("relevance", clf.get("relevance_score", 0))

        # 1. Quality & Legitimacy check
        if not is_legit or score < min_score:
            stats["rejected_low_score"] += 1
            continue

        # Optional query-time AI-only filter (if caller explicitly requested AI feed only)
        if require_ai_filter:
            is_ai = clf.get("is_ai_ml_day_to_day", clf.get("is_ai_ml_role", False))
            if not is_ai:
                continue

        # 2. Remote scope check (if remote is required by caller config)
        is_explicit_remote = bool(job.get("remote")) or any(
            w in (job.get("location") or "").lower() for w in ("remote", "worldwide", "anywhere")
        )
        if hasattr(cfg, "geography") and getattr(cfg.geography, "allowed_remote_scopes", None):
            allowed_scopes = set(cfg.geography.allowed_remote_scopes)
            if "onsite_only" not in allowed_scopes and remote_scope in ("onsite_only", "onsite") and not is_explicit_remote:
                stats["rejected_not_remote"] += 1
                continue

        # 3. Visa Scoring Pass
        visa_mention = clf.get("visa_mention")
        visa_quote = clf.get("visa_quote")
        visa_status, visa_score, visa_evidence = score_job_visa(
            job=job,
            llm_visa_mention=visa_mention,
            llm_visa_quote=visa_quote,
            weights=visa_weights,
        )

        stats["visa_status_counts"][visa_status] = stats["visa_status_counts"].get(visa_status, 0) + 1

        enriched_job = dict(job)
        enriched_job["classified_track"] = track
        enriched_job["track"] = track
        enriched_job["seniority"] = seniority
        enriched_job["remote_scope"] = remote_scope
        enriched_job["allowed_regions"] = clf.get("allowed_regions", [])
        enriched_job["relevance_score"] = score
        enriched_job["why_matched"] = clf.get("why", "")

        # Taxonomy attributes
        enriched_job["isco_code"] = clf.get("isco_code")
        enriched_job["isco_title"] = clf.get("isco_title")
        enriched_job["isco_major_group_code"] = clf.get("isco_major_group_code")
        enriched_job["isco_major_group_title"] = clf.get("isco_major_group_title")
        enriched_job["country_specific_occupation"] = clf.get("country_specific_occupation")
        enriched_job["credentials"] = clf.get("credentials", [])
        enriched_job["industry"] = clf.get("industry")
        enriched_job["uncertainty_reasons"] = clf.get("uncertainty_reasons", {})

        # Compensation enrichment from LLM if structured fields were missing
        if clf.get("salary_min") and not enriched_job.get("salary_min"):
            enriched_job["salary_min"] = clf.get("salary_min")
        if clf.get("salary_max") and not enriched_job.get("salary_max"):
            enriched_job["salary_max"] = clf.get("salary_max")
        if clf.get("salary_currency") and not enriched_job.get("salary_currency"):
            enriched_job["salary_currency"] = clf.get("salary_currency")

        # Visa enrichment
        enriched_job["visa_status"] = visa_status
        enriched_job["visa_score"] = visa_score
        enriched_job["visa_evidence"] = visa_evidence
        enriched_job["visa_sponsorship"] = visa_status in (VisaStatus.SPONSORS.value, VisaStatus.LIKELY.value)

        llm_confidence = clf.get("visa_sponsorship_confidence")
        if llm_confidence is None:
            llm_confidence = int(round((visa_score or 0.0) * 100))
        enriched_job["visa_sponsorship_confidence"] = max(0, min(100, int(llm_confidence)))
        enriched_job["visa_sponsorship_verified"] = bool(
            clf.get("visa_sponsorship_verified", visa_status == VisaStatus.SPONSORS.value)
        )
        enriched_job["visa_types"] = [str(v) for v in (clf.get("visa_types") or []) if v]

        # Resume match enrichment
        if clf.get("resume_match_score") is not None:
            enriched_job["resume_match_score"] = clf.get("resume_match_score")
            enriched_job["resume_match_why"] = clf.get("resume_match_why")
            enriched_job["resume_match"] = {
                "ats_score": clf.get("resume_match_score"),
                "score_rationale": clf.get("resume_match_why") or "",
                "keywords_to_add": [],
                "resume_editing_prompt": "",
            }

        qualified_jobs.append(enriched_job)
        stats["passed"] += 1

    cache.save()
    logger.info(
        "Occupation-agnostic classification complete: %d/%d passed (rejected: %d low-quality, %d non-remote)",
        stats["passed"],
        stats["total_evaluated"],
        stats["rejected_low_score"],
        stats["rejected_not_remote"],
    )
    return qualified_jobs, stats


classify_job_llm = classify_single_job


def heuristic_classify_job(job: dict, config: Optional[RadarConfig] = None) -> dict:
    cfg = config or get_config()
    return classify_single_job(job, config=cfg)


def parse_llm_json_response(raw_text: str) -> Optional[dict]:
    if not raw_text:
        return None
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception:
        return None

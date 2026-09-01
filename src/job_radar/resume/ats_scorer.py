"""Deterministic, shared ATS scoring module for VisaLane (Python mirror of _shared/ats-score.ts).

Implements the reproducible 5-component rubric (0-100, healthy sweet-spot 75-90):
  1. Keyword / Skill Coverage:          40 pts (Must-have terms weighted higher)
  2. Title / Seniority Match:            15 pts
  3. Quantification Density:             15 pts (% of experience bullets with metrics)
  4. Section & Format Completeness:      15 pts (Standard structure, contact info)
  5. Natural-Language Repetition Penalty: -0 to -15 pts (Penalizes keyword stuffing)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with",
    "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves", "will", "shall", "may", "might"
}


def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    matches = re.findall(r"\b[a-z0-9][a-z0-9_\-\+\#\.]{1,35}\b", text.lower())
    return [w for w in matches if len(w) >= 2 and w not in STOP_WORDS]


def _extract_all_bullets(input_data: Dict[str, Any]) -> List[str]:
    bullets: List[str] = []

    sections = input_data.get("sections")
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict) and isinstance(sec.get("items"), list):
                for item in sec["items"]:
                    if isinstance(item, str):
                        bullets.append(item)
                    elif isinstance(item, dict):
                        for b in item.get("bullets") or item.get("highlights") or []:
                            if isinstance(b, str):
                                bullets.append(b)

    parsed_data = input_data.get("parsedData") or input_data.get("parsed_data")
    if not bullets and isinstance(parsed_data, dict):
        for exp in parsed_data.get("experience") or []:
            if isinstance(exp, dict):
                for h in exp.get("highlights") or exp.get("bullets") or []:
                    if isinstance(h, str):
                        bullets.append(h)

    resume_text = input_data.get("resumeText") or input_data.get("resume_text") or ""
    if not bullets and resume_text:
        for line in resume_text.splitlines():
            trimmed = line.strip()
            if re.match(r"^[\u2022\u2023\u25E6\u2043\u2219\*\-\+]\s+", trimmed):
                bullets.append(re.sub(r"^[\u2022\u2023\u25E6\u2043\u2219\*\-\+]\s+", "", trimmed))

    return bullets


def compute_ats_score(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Computes a deterministic ATS score matching _shared/ats-score.ts exactly."""
    resume_text = str(input_data.get("resumeText") or input_data.get("resume_text") or "")
    resume_lower = resume_text.lower()
    resume_keywords = extract_keywords(resume_text)
    resume_kw_set = set(resume_keywords)

    job = input_data.get("job") or {}
    job_desc = str(job.get("description") or "")
    job_title = str(job.get("title") or "")
    job_skills = job.get("skills") if isinstance(job.get("skills"), list) else []
    explicit_must_haves = (
        job.get("must_haves")
        if isinstance(job.get("must_haves"), list)
        else job_skills[:5]
    )

    # 1. Keyword / Skill Coverage (40 pts)
    jd_keywords = extract_keywords(job_desc)
    jd_kw_set = set(jd_keywords)

    must_haves_found: List[str] = []
    must_haves_missing: List[str] = []
    must_have_score = 20

    if explicit_must_haves:
        for mh in explicit_must_haves:
            mh_norm = str(mh).lower().strip()
            if mh_norm in resume_lower or mh_norm in resume_kw_set:
                must_haves_found.append(str(mh))
            else:
                must_haves_missing.append(str(mh))
        must_have_score = round((len(must_haves_found) / len(explicit_must_haves)) * 25)

    general_kw_score = 10
    if jd_kw_set:
        match_count = sum(1 for kw in jd_kw_set if kw in resume_kw_set)
        general_kw_score = round((match_count / len(jd_kw_set)) * 15)

    keyword_score = min(40, must_have_score + general_kw_score)

    # 2. Title / Seniority Match (15 pts)
    title_score = 5
    parsed_data = input_data.get("parsedData") or input_data.get("parsed_data") or {}
    candidate_titles: List[str] = []
    if isinstance(parsed_data.get("job_titles"), list):
        candidate_titles.extend(str(t) for t in parsed_data["job_titles"] if t)
    if isinstance(parsed_data.get("experience"), list):
        for e in parsed_data["experience"]:
            if isinstance(e, dict) and e.get("title"):
                candidate_titles.append(str(e["title"]))

    jt = job_title.lower().strip()
    jt_tokens = extract_keywords(jt)

    if jt and candidate_titles:
        for t in candidate_titles:
            t_norm = t.lower().strip()
            if t_norm == jt:
                title_score = 15
                break
            t_tokens = set(extract_keywords(t_norm))
            if jt_tokens:
                overlap = sum(1 for tok in jt_tokens if tok in t_tokens)
                ratio = overlap / len(jt_tokens)
                current_score = round(ratio * 14)
                if current_score > title_score:
                    title_score = current_score
    elif jt and jt in resume_lower:
        title_score = 12

    # 3. Quantification Density (15 pts)
    bullets = _extract_all_bullets(input_data)
    metric_regex = re.compile(
        r"\b\d+%|\b\d+x\b|\$\d+|\b\d{2,}\b|\b\d+\s*(?:k|m|million|billion|users|clients|requests|ms|seconds|minutes|hours|days|engineers|team members|developers)\b",
        re.IGNORECASE,
    )

    quantification_score = 8
    if bullets:
        quantified_count = sum(1 for b in bullets if metric_regex.search(b))
        ratio = quantified_count / len(bullets)
        quantification_score = min(15, round(ratio * 30))

    # 4. Section & Format Completeness (15 pts)
    completeness_score = 0
    has_contact = bool(
        re.search(r"[\w.-]+@[\w.-]+\.\w+", resume_text)
        or re.search(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", resume_text)
    )
    if has_contact:
        completeness_score += 4

    has_summary = bool(
        parsed_data.get("summary")
        or "summary" in resume_lower
        or "profile" in resume_lower
    )
    if has_summary:
        completeness_score += 3

    skills_val = parsed_data.get("skills")
    has_skills = bool(
        (isinstance(skills_val, list) and len(skills_val) > 0)
        or "skills" in resume_lower
        or "technologies" in resume_lower
    )
    if has_skills:
        completeness_score += 4

    edu_val = parsed_data.get("education")
    has_edu = bool(
        (isinstance(edu_val, list) and len(edu_val) > 0)
        or "education" in resume_lower
        or "university" in resume_lower
        or "degree" in resume_lower
    )
    if has_edu:
        completeness_score += 4

    completeness_score = min(15, completeness_score)

    # 5. Natural-Language Repetition Penalty (0 to -15 pts)
    kw_counts: Dict[str, int] = {}
    for kw in resume_keywords:
        if len(kw) >= 3:
            kw_counts[kw] = kw_counts.get(kw, 0) + 1

    penalty_score = 0
    for kw, count in kw_counts.items():
        if count >= 7 and kw not in {"development", "software", "system", "engineer", "team", "project"}:
            penalty_score -= min(5, count - 6)
    penalty_score = max(-15, penalty_score)

    raw_total = keyword_score + title_score + quantification_score + completeness_score + penalty_score
    total = max(0, min(100, raw_total))

    return {
        "total": total,
        "keywordScore": keyword_score,
        "titleScore": title_score,
        "quantificationScore": quantification_score,
        "completenessScore": completeness_score,
        "penaltyScore": penalty_score,
        "mustHavesFound": must_haves_found,
        "mustHavesMissing": must_haves_missing,
    }

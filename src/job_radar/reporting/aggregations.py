"""Pure aggregation & formatting helpers for the run report layer.

This module is intentionally independent of the Apify SDK and of the scraping
pipeline: it consumes already-produced ``Job`` objects / stats and derives
report-friendly structures. Nothing here re-fetches, re-classifies, or
re-queries any source.

Every helper is defensive: malformed or partially-populated jobs must not raise.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job

# Reuse the canonical scoring inputs so the report score is the SAME number the
# pipeline used for ranking, exposed on a 0-100 scale. We import the map (not the
# function) to keep this module free of config-dependent side effects.
from job_radar.pipeline.scoring import SOURCE_QUALITY_MAP

# --------------------------------------------------------------------------- #
# Country detection & flags
# --------------------------------------------------------------------------- #

# ISO-ish display name -> emoji flag. Conservative list of destinations this
# Actor actually targets; unknown countries simply get no flag glyph.
_COUNTRY_FLAGS: Dict[str, str] = {
    # Europe
    "United Kingdom": "🇬🇧", "UK": "🇬🇧", "Germany": "🇩🇪", "Netherlands": "🇳🇱",
    "France": "🇫🇷", "Ireland": "🇮🇪", "Spain": "🇪🇸", "Italy": "🇮🇹",
    "Sweden": "🇸🇪", "Norway": "🇳🇴", "Denmark": "🇩🇰", "Finland": "🇫🇮",
    "Poland": "🇵🇱", "Portugal": "🇵🇹", "Belgium": "🇧🇪", "Austria": "🇦🇹",
    "Switzerland": "🇨🇭", "Luxembourg": "🇱🇺", "Estonia": "🇪🇪", "Latvia": "🇱🇻",
    "Lithuania": "🇱🇹", "Czech Republic": "🇨🇿", "Czechia": "🇨🇿", "Romania": "🇷🇴",
    "Hungary": "🇭🇺", "Greece": "🇬🇷", "Bulgaria": "🇧🇬", "Croatia": "🇭🇷",
    "Slovakia": "🇸🇰", "Slovenia": "🇸🇮", "Malta": "🇲🇹", "Cyprus": "🇨🇾",
    "Iceland": "🇮🇸", "Serbia": "🇷🇸", "Ukraine": "🇺🇦",

    # North America
    "United States": "🇺🇸", "USA": "🇺🇸", "Canada": "🇨🇦", "Mexico": "🇲🇽",

    # South America
    "Brazil": "🇧🇷", "Argentina": "🇦🇷", "Chile": "🇨🇱", "Colombia": "🇨🇴",
    "Peru": "🇵🇪", "Uruguay": "🇺🇾",

    # East Asia, Southeast Asia & South Asia
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Singapore": "🇸🇬", "Hong Kong": "🇭🇰",
    "Taiwan": "🇹🇼", "China": "🇨🇳", "Malaysia": "🇲🇾", "Thailand": "🇹🇭",
    "Vietnam": "🇻🇳", "Indonesia": "🇮🇩", "Philippines": "🇵🇭", "India": "🇮🇳",
    "Pakistan": "🇵🇰", "Bangladesh": "🇧🇩",

    # Arab Countries & Middle East
    "United Arab Emirates": "🇦🇪", "UAE": "🇦🇪", "Saudi Arabia": "🇸🇦",
    "Qatar": "🇶🇦", "Kuwait": "🇰🇼", "Oman": "🇴🇲", "Bahrain": "🇧🇭",
    "Egypt": "🇪🇬", "Jordan": "🇯🇴", "Lebanon": "🇱🇧", "Morocco": "🇲🇦",
    "Israel": "🇮🇱",

    # Oceania
    "Australia": "🇦🇺", "New Zealand": "🇳🇿",
}

# Ordered longest-first so "United Kingdom" wins before any shorter substring.
_COUNTRY_NAMES: List[str] = sorted(_COUNTRY_FLAGS.keys(), key=len, reverse=True)

# Common city -> country hints used only as a fallback when the location string
# carries a well-known capital/hub but no country name. These are unambiguous.
_CITY_COUNTRY: Dict[str, str] = {
    "london": "United Kingdom", "berlin": "Germany", "munich": "Germany", "frankfurt": "Germany",
    "amsterdam": "Netherlands", "rotterdam": "Netherlands", "paris": "France",
    "dublin": "Ireland", "stockholm": "Sweden", "oslo": "Norway",
    "copenhagen": "Denmark", "helsinki": "Finland", "madrid": "Spain",
    "barcelona": "Spain", "lisbon": "Portugal", "zurich": "Switzerland", "geneva": "Switzerland",
    "vienna": "Austria", "brussels": "Belgium", "warsaw": "Poland", "prague": "Czech Republic",
    "budapest": "Hungary", "athens": "Greece", "bucharest": "Romania", "tallinn": "Estonia",
    "riga": "Latvia", "vilnius": "Lithuania", "zagreb": "Croatia", "sofia": "Bulgaria",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "sydney": "Australia", "melbourne": "Australia", "auckland": "New Zealand",
    "new york": "United States", "san francisco": "United States", "seattle": "United States",
    "mexico city": "Mexico", "sao paulo": "Brazil", "buenos aires": "Argentina",
    "santiago": "Chile", "bogota": "Colombia", "lima": "Peru", "montevideo": "Uruguay",
    "tokyo": "Japan", "seoul": "South Korea", "singapore": "Singapore", "hong kong": "Hong Kong",
    "taipei": "Taiwan", "beijing": "China", "shanghai": "China", "kuala lumpur": "Malaysia",
    "bangkok": "Thailand", "hanoi": "Vietnam", "ho chi minh": "Vietnam", "jakarta": "Indonesia",
    "manila": "Philippines", "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "doha": "Qatar", "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "kuwait city": "Kuwait",
    "muscat": "Oman", "manama": "Bahrain", "cairo": "Egypt", "amman": "Jordan",
    "beirut": "Lebanon", "casablanca": "Morocco", "tel aviv": "Israel",
}

REMOTE_COUNTRY_LABEL = "Remote"
OTHER_COUNTRY_LABEL = "Other"


def detect_country(job: Job) -> str:
    """Best-effort display country for grouping. Never invents data.

    Order: explicit ``job.country`` -> country name in location -> known city
    hint -> "Remote" (if remote) -> "Other". All parsing is read-only.
    """
    country = (getattr(job, "country", None) or "").strip()
    if country:
        return country

    haystack = f"{getattr(job, 'location', '') or ''} {' '.join(getattr(job, 'locations', []) or [])}".lower()
    for name in _COUNTRY_NAMES:
        if name.lower() in haystack:
            return name
    for city, ctry in _CITY_COUNTRY.items():
        if city in haystack:
            return ctry

    if getattr(job, "remote", False) or getattr(job, "is_remote", False):
        return REMOTE_COUNTRY_LABEL
    return OTHER_COUNTRY_LABEL


def country_flag(country: str) -> str:
    return _COUNTRY_FLAGS.get(country, "")


# --------------------------------------------------------------------------- #
# Visa evidence representation (nuanced + legally careful)
# --------------------------------------------------------------------------- #

# signal -> (short label, tone, emoji, explanation)
# tone is one of: strong | possible | neutral | negative
VISA_SIGNAL_INFO: Dict[str, Dict[str, str]] = {
    "stated_in_jd": {
        "label": "Explicit sponsorship in job description",
        "tone": "strong",
        "emoji": "🟢",
        "explanation": "The job description explicitly mentions visa sponsorship or relocation support.",
    },
    "on_sponsor_list": {
        "label": "Employer on official sponsor registry",
        "tone": "strong",
        "emoji": "🟢",
        "explanation": (
            "The employer appears on an official government sponsor registry. This indicates "
            "sponsorship capability; confirm sponsorship for this specific role with the employer."
        ),
    },
    "employer_sponsored_region": {
        "label": "Employer-sponsored destination (work-permit model)",
        "tone": "possible",
        "emoji": "🟡",
        "explanation": (
            "The destination uses an employer-sponsored work-permit model (e.g. Gulf, Japan SSW, "
            "Korea EPS). This is not a verified registry match."
        ),
    },
    "historical_filings": {
        "label": "Historical sponsorship filings on record",
        "tone": "possible",
        "emoji": "🟡",
        "explanation": "Public records show the employer has filed sponsorship paperwork in the past.",
    },
    "unknown": {
        "label": "No sponsorship signal",
        "tone": "neutral",
        "emoji": "⚪",
        "explanation": "No explicit sponsorship information was found for this role.",
    },
    "explicit_no": {
        "label": "Explicitly does not sponsor",
        "tone": "negative",
        "emoji": "🔴",
        "explanation": "The job states that sponsorship is not available / right to work is required.",
    },
}

_STRONG_TONES = {"strong"}
_POSSIBLE_TONES = {"strong", "possible"}


def visa_info(signal: Optional[str]) -> Dict[str, str]:
    """Return label/tone/emoji/explanation for a visa confidence signal."""
    if not signal:
        return dict(VISA_SIGNAL_INFO["unknown"])
    return dict(VISA_SIGNAL_INFO.get(signal, VISA_SIGNAL_INFO["unknown"]))


def is_visa_positive(signal: Optional[str]) -> bool:
    return visa_info(signal)["tone"] in _POSSIBLE_TONES


def is_visa_strong(signal: Optional[str]) -> bool:
    return visa_info(signal)["tone"] in _STRONG_TONES


# --------------------------------------------------------------------------- #
# Source trust / verification
# --------------------------------------------------------------------------- #

# Baseline sources -> human trust label. These describe the *type* of source,
# never an unverifiable "verified" claim.
_BASELINE_SOURCE_LABELS: Dict[str, str] = {
    "greenhouse": "Company career page",
    "lever": "Company career page",
    "ashby": "Company career page",
    "workable": "Company career page",
    "smartrecruiters": "Company career page",
    "personio": "Company career page",
    "remoteok": "Remote job board",
    "remotive": "Remote job board",
    "himalayas": "Remote job board",
    "jobicy": "Remote job board",
    "arbeitnow": "Job board",
    "hn_whoshiring": "Community board",
}

# overseas metadata.source_category -> human trust label.
_OVERSEAS_CATEGORY_LABELS: Dict[str, str] = {
    "government": "Government job portal",
    "manpower_agency": "Recruitment agency",
    "aggregator": "Job aggregator",
    "remote_board": "Remote job board",
    "visa_specialist": "Visa-specialist board",
    "unknown_board": "Niche job board",
}


def source_trust(job: Job) -> str:
    """Human-readable source trust label derived only from available data."""
    category = None
    meta = getattr(job, "metadata", None) or {}
    if isinstance(meta, dict):
        category = meta.get("source_category")
    if category and category in _OVERSEAS_CATEGORY_LABELS:
        return _OVERSEAS_CATEGORY_LABELS[category]
    src = (getattr(job, "source", "") or "").lower()
    return _BASELINE_SOURCE_LABELS.get(src, "Job board")


def source_quality(source: str) -> float:
    """Numeric source quality (0-100) reused from the scoring stage."""
    return SOURCE_QUALITY_MAP.get((source or "").lower(), 60.0)


# --------------------------------------------------------------------------- #
# Opportunity score + transparent reasons
# --------------------------------------------------------------------------- #

def opportunity_score(job: Job) -> int:
    """0-100 opportunity score. Same ranking signal the pipeline used."""
    score = getattr(job, "composite_score", None)
    if score is None:
        return 0
    try:
        return max(0, min(100, round(float(score) * 100)))
    except Exception:
        return 0


def _posted_age_hours(job: Job) -> Optional[float]:
    posted = getattr(job, "posted_at", None)
    if not posted and getattr(job, "date_posted", None):
        try:
            posted = datetime.datetime.fromisoformat(str(job.date_posted).replace("Z", "+00:00"))
        except Exception:
            return None
    if not posted:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        return max(0.0, (now - posted).total_seconds() / 3600.0)
    except Exception:
        return None


def opportunity_reasons(job: Job, config: Optional[JobSearchConfig] = None) -> List[str]:
    """Human-readable, data-backed reasons a job ranks high. No invented claims."""
    reasons: List[str] = []

    # 1. Visa evidence.
    signal = _conf_str(job)
    info = visa_info(signal)
    if info["tone"] == "strong":
        reasons.append("Strong sponsorship evidence")
    elif info["tone"] == "possible":
        reasons.append("Possible sponsorship evidence")

    # 2. Keyword match (only when keywords were requested and present).
    if config is not None and config.keywords:
        text = f"{getattr(job, 'title', '')} {getattr(job, 'description_text', '') or ''}".lower()
        hits = [k for k in config.keywords if k and k.lower() in text]
        if hits:
            shown = ", ".join(hits[:3])
            reasons.append(f"Matches requested keywords: {shown}")

    # 3. Requested country match.
    if config is not None and config.countries:
        ctry = detect_country(job)
        if ctry and ctry in config.countries:
            reasons.append(f"Located in requested country: {ctry}")

    # 4. Seniority match.
    if config is not None and config.seniority_levels:
        sen = (getattr(job, "seniority", None) or "").lower()
        title_l = (getattr(job, "title", "") or "").lower()
        targets = [s.lower() for s in config.seniority_levels]
        if (sen and sen in targets) or any(t in title_l for t in targets):
            reasons.append("Matches requested seniority level")

    # 5. Recency.
    age = _posted_age_hours(job)
    if age is not None:
        if age < 24:
            reasons.append("Posted within the last day")
        elif age < 72:
            reasons.append("Posted within the last 3 days")
        elif age < 120:
            reasons.append("Posted within the last 5 days")

    # 6. Salary transparency.
    if getattr(job, "salary_min", None) or getattr(job, "salary_max", None):
        reasons.append("Salary range disclosed")

    # 7. Remote compatibility.
    if getattr(job, "remote", False) or getattr(job, "is_remote", False):
        if config is not None and config.remote_only:
            reasons.append("Remote role (as requested)")
        else:
            reasons.append("Remote-friendly")

    # 8. Source trust.
    q = source_quality(getattr(job, "source", ""))
    if q >= 90:
        reasons.append("High-trust source (official ATS)")

    # Cap to keep the card readable.
    return reasons[:6]


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

_CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "SAR": "SAR ", "QAR": "QAR ",
    "KWD": "KWD ", "OMR": "OMR ", "BHD": "BHD ", "INR": "₹", "PKR": "PKR ",
    "BDT": "BDT ", "JPY": "¥", "SGD": "S$", "CAD": "C$", "AUD": "A$", "NZD": "NZ$",
    "CHF": "CHF ", "SEK": "kr ", "PLN": "zł ",
}


def format_salary(job: Job) -> str:
    """Compact human-readable salary or '' when unavailable."""
    smin = getattr(job, "salary_min", None)
    smax = getattr(job, "salary_max", None)
    cur = (getattr(job, "salary_currency", None) or "").upper()
    sym = _CURRENCY_SYMBOLS.get(cur, f"{cur} " if cur else "")
    if not smin and not smax:
        return ""
    try:
        if smin and smax and smin != smax:
            return f"{sym}{_compact(smin)}–{_compact(smax)}"
        return f"{sym}{_compact(smax or smin)}"
    except Exception:
        return ""


def _compact(value: float) -> str:
    try:
        v = float(value)
    except Exception:
        return str(value)
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        trimmed = f"{v/1_000:.0f}k" if v % 1_000 == 0 or v >= 10_000 else f"{v:,.0f}"
        return trimmed if v >= 10_000 else f"{v:,.0f}"
    return f"{v:,.0f}"


def time_ago(posted_at: Optional[datetime.datetime], date_posted: Optional[str] = None) -> str:
    """Human-friendly 'N days ago' style string, or '' when unknown."""
    posted = posted_at
    if not posted and date_posted:
        try:
            posted = datetime.datetime.fromisoformat(str(date_posted).replace("Z", "+00:00"))
        except Exception:
            return ""
    if not posted:
        return ""
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        delta = now - posted
    except Exception:
        return ""
    hours = delta.total_seconds() / 3600.0
    if hours < 0:
        return ""
    if hours < 1:
        return "just now"
    if hours < 24:
        h = max(1, int(hours))
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(hours / 24)
    if days < 60:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return posted.strftime("%d %b %Y")


def _conf_str(job: Job) -> str:
    conf = getattr(job, "visa_confidence", None)
    if conf is None:
        return "unknown"
    return conf if isinstance(conf, str) else getattr(conf, "value", "unknown")


def workplace_label(job: Job) -> str:
    """Remote / Hybrid / On-site label."""
    wt = (getattr(job, "workplace_type", None) or "").lower()
    if wt in ("remote", "hybrid", "onsite", "on-site"):
        return {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site", "on-site": "On-site"}[wt]
    if getattr(job, "remote", False) or getattr(job, "is_remote", False):
        return "Remote"
    if getattr(job, "is_hybrid", False):
        return "Hybrid"
    return ""


# --------------------------------------------------------------------------- #
# Ranking & aggregation
# --------------------------------------------------------------------------- #

def top_match_count(total: int) -> int:
    """Decide how many top matches to surface in the human report."""
    if total <= 0:
        return 0
    if total <= 15:
        return min(10, total)
    return 20


def rank_top_jobs(jobs: List[Job], n: int) -> List[Job]:
    """Return the top-n jobs by composite score (desc), defensively sorted."""
    def key(j: Job) -> Tuple[float, float]:
        conf = _conf_str(j)
        conf_rank = {
            "stated_in_jd": 5, "on_sponsor_list": 4, "employer_sponsored_region": 3,
            "historical_filings": 2, "unknown": 1, "explicit_no": 0,
        }.get(conf, 0)
        try:
            score = float(getattr(j, "composite_score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        return (score, conf_rank)

    ordered = sorted(jobs, key=key, reverse=True)
    return ordered[: max(0, n)]


def aggregate_countries(jobs: List[Job]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        c = detect_country(job)
        b = buckets.setdefault(c, {"country": c, "jobs": 0, "visaPositive": 0, "highConfidence": 0})
        b["jobs"] += 1
        signal = _conf_str(job)
        if is_visa_positive(signal):
            b["visaPositive"] += 1
        if is_visa_strong(signal):
            b["highConfidence"] += 1
    out = sorted(buckets.values(), key=lambda x: x["jobs"], reverse=True)
    for b in out:
        b["flag"] = country_flag(b["country"])
    return out


def aggregate_companies(jobs: List[Job], limit: int = 15) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        name = (getattr(job, "company", None) or "Unknown").strip() or "Unknown"
        norm = (getattr(job, "company_normalized", None) or name.lower()).strip()
        key = norm or name.lower()
        b = buckets.setdefault(key, {
            "company": name, "domain": getattr(job, "company_domain", None),
            "jobs": 0, "visaPositive": 0, "countries": set(), "locations": set(),
            "sources": set(), "scores": [], "titles": [],
        })
        b["jobs"] += 1
        signal = _conf_str(job)
        if is_visa_positive(signal):
            b["visaPositive"] += 1
        c = detect_country(job)
        if c and c not in (OTHER_COUNTRY_LABEL,):
            b["countries"].add(c)
        loc = (getattr(job, "location", None) or "").strip()
        if loc:
            b["locations"].add(loc)
        src = getattr(job, "source", None)
        if src:
            b["sources"].add(src)
        b["scores"].append(opportunity_score(job))
        title = (getattr(job, "title", None) or "").strip()
        if title:
            b["titles"].append(title)

    rows: List[Dict[str, Any]] = []
    for b in buckets.values():
        scores = b["scores"]
        rows.append({
            "company": b["company"],
            "domain": b["domain"],
            "jobs": b["jobs"],
            "visaPositive": b["visaPositive"],
            "countryCount": len(b["countries"]),
            "countries": sorted(b["countries"]),
            "sources": sorted(b["sources"]),
            "highestScore": max(scores) if scores else 0,
            "averageScore": round(sum(scores) / len(scores)) if scores else 0,
            "topRoles": b["titles"][:5],
        })
    rows.sort(key=lambda r: (r["jobs"], r["highestScore"]), reverse=True)
    return rows[: max(0, limit)]


def aggregate_sources(
    jobs: List[Job],
    successful_sources: Optional[List[str]] = None,
    failed_sources: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    successful = set(successful_sources or [])
    failed_by_name: Dict[str, str] = {}
    for fs in (failed_sources or []):
        if isinstance(fs, dict):
            failed_by_name[str(fs.get("name", ""))] = str(fs.get("error", "") or "error")

    buckets: Dict[str, Dict[str, Any]] = {}
    # Seed with all attempted sources so failures with zero rows still show.
    for name in successful:
        buckets.setdefault(name, {"source": name, "jobs": 0})
    for name in failed_by_name:
        buckets.setdefault(name, {"source": name, "jobs": 0})
    for job in jobs:
        src = getattr(job, "source", None) or "unknown"
        b = buckets.setdefault(src, {"source": src, "jobs": 0})
        b["jobs"] += 1

    rows: List[Dict[str, Any]] = []
    for name, b in buckets.items():
        if name in failed_by_name:
            status = "failed"
        elif name in successful:
            status = "ok"
        elif b["jobs"] > 0:
            status = "ok"
        else:
            status = "unknown"
        rows.append({
            "source": name,
            "jobs": b["jobs"],
            "status": status,
            "trust": "",  # filled below from a representative job / baseline map
            "error": failed_by_name.get(name, ""),
        })

    # Attach trust labels from any representative job if we have one.
    trust_by_source: Dict[str, str] = {}
    for job in jobs:
        src = getattr(job, "source", None) or "unknown"
        trust_by_source.setdefault(src, source_trust(job))
    for r in rows:
        r["trust"] = trust_by_source.get(r["source"]) or _BASELINE_SOURCE_LABELS.get(r["source"].lower(), "Job board")

    rows.sort(key=lambda r: r["jobs"], reverse=True)
    return rows


def aggregate_visa(jobs: List[Job]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for job in jobs:
        signal = _conf_str(job)
        counts[signal] = counts.get(signal, 0) + 1
    order = ["stated_in_jd", "on_sponsor_list", "employer_sponsored_region",
             "historical_filings", "unknown", "explicit_no"]
    rows: List[Dict[str, Any]] = []
    for signal in order:
        if counts.get(signal):
            info = visa_info(signal)
            rows.append({
                "signal": signal,
                "count": counts[signal],
                "label": info["label"],
                "tone": info["tone"],
                "emoji": info["emoji"],
            })
    # Any unexpected signals (defensive).
    for signal, count in counts.items():
        if signal not in order:
            rows.append({"signal": signal, "count": count, "label": signal,
                         "tone": "neutral", "emoji": "⚪"})
    return rows

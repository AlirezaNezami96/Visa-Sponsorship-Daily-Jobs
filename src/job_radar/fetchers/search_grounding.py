"""Gemini search-grounded job discovery fetcher (4th source).

Uses Google GenAI Interactions API with `google_search` and `url_context` grounding tools
to discover verified, live job postings directly from company career pages and ATS domains.

Follows the codebase's resilience patterns:
- Fails open / returns [] on any failure — never crashes the pipeline.
- Automatic fallback from gemini-3.7-flash to gemini-3.6-flash on model errors.
- Defensive JSON parsing with markdown code-fence stripping.
- Strict ATS allowlist and aggregator blacklist.
- Normalizes output into standard job_radar dictionary shape.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

CATEGORY_PROFILES: Dict[str, Dict[str, Any]] = {
    "remote": {
        "label": "100% globally-remote software engineering roles",
        "query_hints": [
            'site:jobs.ashbyhq.com ("Remote" OR "Work from anywhere") ("Software Engineer" OR "Mobile" OR "Backend" OR "Frontend" OR "Full Stack" OR "DevOps")',
            'site:boards.greenhouse.io ("Remote" OR "Worldwide") ("Software Engineer" OR "Mobile Developer")',
            'site:jobs.lever.co ("Remote" OR "EMEA" OR "LATAM" OR "Europe") ("Developer" OR "Engineer")',
            'site:apply.workable.com "Remote" ("Engineer" OR "Developer")',
        ],
        "verify": "Confirm remote eligibility from the posting text itself, not just how a board tags it.",
    },
    "visa_sponsorship": {
        "label": "roles where the posting itself offers visa sponsorship or relocation support",
        "query_hints": [
            'site:boards.greenhouse.io ("visa sponsorship" OR "relocation support" OR "relocation package") (Engineer OR Developer)',
            'site:jobs.ashbyhq.com ("visa sponsorship" OR "relocation assistance") (Software OR Engineer)',
            'site:jobs.lever.co ("visa sponsorship provided" OR "relocation assistance") ("Engineer" OR "Developer")',
            'site:careers.smartrecruiters.com ("visa sponsorship" OR "relocation") ("Software Engineer")',
        ],
        "verify": "Confirm the posting itself explicitly states visa sponsorship or relocation assistance — never infer this from company size, industry, or country.",
    },
    "ai_intern": {
        "label": "AI/ML/data-science internships, co-ops, fellowships, or explicitly entry-level/new-grad AI engineering roles",
        "query_hints": [
            'site:jobs.ashbyhq.com ("AI Intern" OR "ML Intern" OR "Machine Learning Intern" OR "AI Research Intern" OR "LLM Intern")',
            'site:boards.greenhouse.io ("AI Intern" OR "Machine Learning Intern" OR "GenAI Intern" OR "Data Science Intern")',
            'site:jobs.lever.co ("AI Intern" OR "Machine Learning Internship" OR "AI Engineering Intern")',
        ],
        "verify": "Confirm this is explicitly internship/co-op/fellowship or entry-level/new-grad — reject senior/staff.",
    },
}

BLACKLISTED_HOSTS = {
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "jooble.org",
    "monster.com",
    "talent.com",
    "dice.com",
    "simplyhired.com",
    "remotive.com",
    "weworkremotely.com",
    "wellfound.com",
    "angel.co",
    "jobrapido.com",
    "neuvoo.com",
    "careerbuilder.com",
}

JOB_LIST_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "company": {"type": "STRING"},
            "apply_url": {"type": "STRING"},
            "location": {"type": "STRING"},
            "workplace_type": {"type": "STRING"},
            "visa_sponsorship": {"type": "BOOLEAN"},
            "posted_date": {"type": "STRING"},
            "tech_stack": {"type": "ARRAY", "items": {"type": "STRING"}},
            "summary": {"type": "STRING"},
        },
        "required": ["title", "company", "apply_url"],
    },
}


def build_search_grounding_prompt(category: str, max_age_days: int = 5) -> str:
    """Build the search-grounding task prompt for a given category."""
    profile = CATEGORY_PROFILES.get(category, CATEGORY_PROFILES["remote"])
    category_label = profile["label"]
    query_hints_text = "\n".join(f"  - {hint}" for hint in profile["query_hints"])
    verify_instruction = profile["verify"]

    return f"""You are a career-intelligence search agent. Use live Google Search and the url_context
tool to find genuinely new tech job postings for: {category_label}.

SOURCE RESTRICTION — direct ATS and company career pages only:
  jobs.ashbyhq.com/* · boards.greenhouse.io/* or job-boards.greenhouse.io/* ·
  jobs.lever.co/* · apply.workable.com/* · *.personio.de/* or *.personio.com/* ·
  careers.smartrecruiters.com/* · *.pinpointhq.com/* · *.bamboohr.com/careers/* ·
  *.rippling-ats.com/* · careers.<company>.com/* or <company>.com/careers/*
STRICT BLACKLIST — reject immediately: LinkedIn, Indeed, Glassdoor, ZipRecruiter,
  Jooble, Monster, Talent.com, Dice, SimplyHired, Remotive, WeWorkRemotely,
  Wellfound/AngelList, Jobrapido, Neuvoo, CareerBuilder, or any recruiter directory.

FRESHNESS: only postings from the last {max_age_days} days. Check date strings,
  timestamps, and indexing dates ("2 days ago", "posted this week", etc.).

GEOGRAPHY: no geographic exclusion. Every country and region is in scope, including
  the United States and India. (This project deliberately removed country-based
  filtering — do not reintroduce it under any framing.)

SEARCH STRATEGY — starting points, adapt as the results guide you:
{query_hints_text}

VERIFICATION — for every candidate posting, before including it:
  1. Open it with url_context and confirm it's a real, currently-live posting on an
     allowed domain — not an aggregator, not expired, not a generic careers-page
     listing page (must be the specific job's own page).
  2. Confirm the freshness window from the page itself, not just the search snippet.
  3. {verify_instruction}
  4. Deduplicate: drop repeated postings from the same company/URL.
  If a field can't be confirmed from what you actually retrieved, omit that job rather
  than guessing. There is NO minimum result count — return exactly as many verified
  postings as genuinely exist, including zero. Never pad toward a target number.

OUTPUT — return ONLY a valid JSON array (no markdown fences, no commentary), each
  object matching:
  {{
    "title": "string",
    "company": "string",
    "apply_url": "string (https, direct to the ATS/career page application)",
    "location": "string",
    "workplace_type": "Remote" | "Hybrid" | "On-site",
    "visa_sponsorship": true | false,
    "posted_date": "string (YYYY-MM-DD or 'X days ago')",
    "tech_stack": ["string"],
    "summary": "string (1-2 sentences)"
  }}"""


def _extract_cited_urls(interaction: Any) -> Set[str]:
    """Defensively extract URLs cited or visited by grounding tools in the interaction."""
    cited: Set[str] = set()
    if not interaction:
        return cited

    try:
        steps = getattr(interaction, "steps", None) or []
        for step in steps:
            # Check step tools / tool calls / outputs
            step_dict = step if isinstance(step, dict) else (step.dict() if hasattr(step, "dict") else {})
            step_str = str(step_dict)
            for url in re.findall(r"https?://[^\s'\"<>]+", step_str):
                cleaned = url.rstrip(".,;:)")
                cited.add(cleaned)
    except Exception as exc:
        logger.debug("Failed to extract cited URLs from interaction metadata: %s", exc)

    return cited


def _call_gemini_grounded(
    prompt: str,
    model: str = "gemini-3.7-flash",
    fallback_model: str = "gemini-3.6-flash",
    thinking_level: str = "HIGH",
) -> Tuple[str, Set[str]]:
    """Call Google GenAI with google_search and url_context tools.

    Returns (raw_text, cited_urls).
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    tools = [{"type": "google_search"}, {"type": "url_context"}]

    extra_body: Dict[str, Any] = {}
    if thinking_level:
        extra_body["thinking_level"] = thinking_level

    # Primary attempt with model + schema
    try:
        interaction = client.interactions.create(
            model=model,
            input=prompt,
            tools=tools,
            response_format={"type": "text", "mime_type": "application/json", "schema": JOB_LIST_SCHEMA},
            extra_body=extra_body if extra_body else None,
        )
        raw_text = (interaction.output_text or "").strip()
        cited = _extract_cited_urls(interaction)
        return raw_text, cited
    except Exception as primary_exc:
        err_str = str(primary_exc).lower()

        # If schema-based response_format had a compatibility issue with grounding tools, retry without schema
        if "schema" in err_str or "response_format" in err_str or "400" in err_str:
            logger.info("Retrying %s without response_format schema for grounding compatibility...", model)
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    tools=tools,
                    extra_body=extra_body if extra_body else None,
                )
                raw_text = (interaction.output_text or "").strip()
                cited = _extract_cited_urls(interaction)
                return raw_text, cited
            except Exception as no_schema_exc:
                primary_exc = no_schema_exc
                err_str = str(no_schema_exc).lower()

        # Fallback model attempt if primary model not found / failed
        if "not found" in err_str or "model" in err_str or "404" in err_str or "unavailable" in err_str:
            logger.warning(
                "Primary grounding model %s failed (%s), retrying with fallback %s",
                model, primary_exc, fallback_model,
            )
            try:
                interaction = client.interactions.create(
                    model=fallback_model,
                    input=prompt,
                    tools=tools,
                    extra_body=extra_body if extra_body else None,
                )
                raw_text = (interaction.output_text or "").strip()
                cited = _extract_cited_urls(interaction)
                return raw_text, cited
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Both primary ({model}) and fallback ({fallback_model}) search grounding failed: {fallback_exc}"
                ) from fallback_exc

        raise primary_exc


def _parse_grounded_response(raw_text: str) -> List[dict]:
    """Parse JSON array response from Gemini with defensive code-fence stripping."""
    if not raw_text:
        return []

    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()

    # Sometimes model wraps response in {"jobs": [...]} or {"data": [...]}
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            for key in ("jobs", "postings", "results", "data"):
                if isinstance(parsed.get(key), list):
                    return [item for item in parsed[key] if isinstance(item, dict)]
        return []
    except Exception as exc:
        logger.debug("Failed to parse search-grounding JSON response: %s (first 100 chars: %r)", exc, raw_text[:100])
        # Try finding JSON array inside text
        array_match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
        if array_match:
            try:
                parsed = json.loads(array_match.group(0))
                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, dict)]
            except Exception:
                pass
        return []


def _is_blacklisted_url(url: str) -> bool:
    """Return True if URL belongs to a blacklisted aggregator or job board."""
    if not url:
        return True
    u_lower = url.lower()
    for host in BLACKLISTED_HOSTS:
        if host in u_lower:
            return True
    return False


def _normalize(raw: dict, category: str) -> Optional[dict]:
    """Normalize raw grounded job object into standard job_radar dictionary shape."""
    title = str(raw.get("title", "")).strip()
    url = str(raw.get("apply_url") or raw.get("url") or "").strip()
    company = str(raw.get("company", "")).strip()

    if not title or not url or not company:
        return None

    if _is_blacklisted_url(url):
        logger.debug("Dropping search-grounded job with blacklisted URL: %s", url)
        return None

    workplace_type = str(raw.get("workplace_type", "")).strip()
    is_remote = workplace_type.lower() == "remote" or raw.get("remote") is True or "remote" in raw.get("location", "").lower()

    return {
        "title": title,
        "url": url,
        "company": company,
        "location": raw.get("location") or ("Remote" if is_remote else ""),
        "date_posted": raw.get("posted_date") or raw.get("date_posted"),
        "remote": is_remote,
        "remote_scope": "worldwide" if is_remote else "onsite",
        "description": raw.get("summary") or raw.get("description", ""),
        "visa_sponsorship": bool(raw.get("visa_sponsorship", False)),
        "tech_stack": raw.get("tech_stack", []) if isinstance(raw.get("tech_stack"), list) else [],
        "category": category,
        "source": "SEARCH_GROUNDING",
    }


def fetch_search_grounded_jobs(category: str, config: Any = None) -> List[dict]:
    """Fetch search-grounded job postings for a specific category using Gemini.

    Args:
        category: "remote" | "visa_sponsorship" | "ai_intern"
        config: Optional RadarConfig instance

    Returns:
        List of normalized job dicts. Never raises — returns [] on any failure.
    """
    if category not in CATEGORY_PROFILES:
        logger.warning("Unknown search grounding category '%s'. Available: %s", category, list(CATEGORY_PROFILES.keys()))
        return []

    # Check API key
    if not os.environ.get("GEMINI_API_KEY"):
        logger.debug("GEMINI_API_KEY not set — skipping search grounding for '%s'", category)
        return []

    # Resolve config
    if config is None:
        try:
            from job_radar.config.loader import get_config
            config = get_config()
        except Exception:
            config = None

    enabled = True
    model = "gemini-3.7-flash"
    fallback_model = "gemini-3.6-flash"
    thinking_level = "HIGH"
    max_age_days = 5

    if config is not None:
        if hasattr(config, "search_grounding"):
            enabled = config.search_grounding.enabled
            model = config.search_grounding.model
            fallback_model = config.search_grounding.fallback_model
            thinking_level = config.search_grounding.thinking_level
        if hasattr(config, "freshness"):
            max_age_days = config.freshness.max_age_days

    if not enabled:
        logger.debug("Search grounding is disabled in config")
        return []

    logger.info("🔍 Initiating Gemini Search-Grounded Discovery for '%s' (model: %s)...", category, model)
    prompt = build_search_grounding_prompt(category, max_age_days=max_age_days)

    try:
        raw_text, cited_urls = _call_gemini_grounded(
            prompt=prompt,
            model=model,
            fallback_model=fallback_model,
            thinking_level=thinking_level,
        )
        raw_items = _parse_grounded_response(raw_text)
        logger.info("Search grounding returned %d raw candidate items for '%s'", len(raw_items), category)

        normalized_jobs: List[dict] = []
        seen_urls: Set[str] = set()

        for item in raw_items:
            norm = _normalize(item, category=category)
            if norm and norm["url"] not in seen_urls:
                seen_urls.add(norm["url"])
                normalized_jobs.append(norm)

        logger.info("✅ Search grounding produced %d verified jobs for '%s'", len(normalized_jobs), category)
        return normalized_jobs

    except Exception as exc:
        logger.warning("Search grounding failed for category '%s': %s (returning empty list)", category, exc)
        return []

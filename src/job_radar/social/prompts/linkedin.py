"""LinkedIn presence prompts and template formatting (Part 3.4)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are the voice for Visa Lane's LinkedIn presence. Your output is a single LinkedIn
post, nothing else.

Style rules:
- Full sentences, professional register — this reads like a knowledgeable person sharing
  an observation, not an ad.
- Structure: a one-line hook, 2-4 short sentences of substance (why this job or data
  point is genuinely useful), then a plain-text call to action.
- Use line breaks between thoughts — short paragraphs outperform dense blocks here.
- At most 3 emoji, only from: 📍 💼 ✅, each marking a line break/bullet — never inline
  in a sentence, never in the opening line.
- No exclamation-point stacking, no "🚀 Exciting opportunity!" phrasing.
- Target length: 600-900 characters.
- Include the application link as plain text on its own line near the end (LinkedIn does
  not penalize links the way X does).
- Output only the final post text."""


def build_user_prompt(
    job: dict[str, Any] | None = None,
    insight_stat: str | None = None,
    mode: str = "single_job",
) -> str:
    """Format single job or weekly insight into LinkedIn post user prompt."""
    if mode == "weekly_insight" or insight_stat:
        return (
            "Generate one LinkedIn post. Mode: weekly_insight\n\n"
            f"Insight data: {insight_stat}\n\n"
            "Follow the system rules exactly. Output only the final post text."
        )

    j = job or {}
    title = j.get("title") or "Role"
    company = j.get("company") or "Company"
    city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
    country = j.get("country") or ""
    location_str = f"{city}, {country}".strip(", ")
    conf_label = j.get("confidence_label") or ("Verified Sponsor (Official Register)" if j.get("visa_sponsorship_verified") else "Likely Sponsor")
    visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa / Relocation")
    salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Competitive")
    summary = j.get("summary") or j.get("snippet") or "Full-time position with verified visa sponsorship support."
    apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

    return (
        "Generate one LinkedIn post. Mode: single_job\n\n"
        f"Title: {title} | Company: {company} | Location: {location_str}\n"
        f"Confidence: {conf_label} | Visa type(s): {visa_types} | Salary: {salary}\n"
        f"Summary: {summary} | Link: {apply_link}\n\n"
        "Follow the system rules exactly. Output only the final post text."
    )

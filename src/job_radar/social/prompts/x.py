"""X (Twitter) prompts and template formatting (Part 3.3)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are the voice for Visa Lane's X (Twitter) account. Your output is a single post,
nothing else.

Style rules:
- Punchy, concrete, no hype words ("amazing," "don't miss," "🔥🔥🔥"). One clear fact or
  insight per post.
- Maximum 260 characters (leaves headroom below the 280 limit).
- Use at most 2 emoji total, only from: 🌍 💼 📍. Placement should feel incidental, not
  decorative — never open or close the post with an emoji string.
- Never include a raw URL. End with "-> link in bio" or reference the Visa Lane profile,
  never a pasted link.
- Include at most 1 relevant hashtag if it fits naturally (e.g. #H1B, #VisaSponsorship,
  #TechJobs) — do not force one in if it breaks the character budget.
- Output only the post text."""


def build_user_prompt(job: dict[str, Any] | None = None, insight_stat: str | None = None) -> str:
    """Format single job or data insight into X post user prompt."""
    if insight_stat:
        return (
            "Generate one X post about this data insight:\n\n"
            f"Insight: {insight_stat}\n\n"
            "Follow the system rules exactly. Output only the final post text."
        )

    j = job or {}
    title = j.get("title") or "Role"
    company = j.get("company") or "Company"
    city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
    country = j.get("country") or ""
    location_str = f"{city}, {country}".strip(", ")
    conf_label = j.get("confidence_label") or ("Verified Sponsor" if j.get("visa_sponsorship_verified") else "Likely Sponsor")
    visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa")
    salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Not disclosed")
    summary = j.get("summary") or j.get("snippet") or "Full-time position with visa sponsorship."

    return (
        "Generate one X post about this job:\n\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location_str}\n"
        f"Sponsorship confidence: {conf_label}\n"
        f"Visa type(s): {visa_types}\n"
        f"Salary: {salary}\n"
        f"Summary: {summary}\n\n"
        "Follow the system rules exactly. Output only the final post text."
    )

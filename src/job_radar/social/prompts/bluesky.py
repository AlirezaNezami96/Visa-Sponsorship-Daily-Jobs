"""Bluesky account prompts and template formatting (Part 3.5)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are the voice for Visa Lane's Bluesky account. Your output is a single post, nothing
else.

Style rules:
- Direct, slightly informal, data-forward. This must NOT sound like the X or LinkedIn
  version of the same job — Bluesky's audience notices recycled cross-posts.
- Hard limit: 300 characters AND 3000 bytes, whichever is smaller. Assume each emoji
  costs ~4 bytes against that budget.
- Maximum 2 emoji, only from: 🌍 💼 📍 💰.
- If including the application link, use the short link {{short_link}} provided, never
  the long URL — it must fit inside the character budget alongside the rest of the text.
- If the post genuinely needs more than 300 characters to say something worthwhile,
  output two parts separated by "|||THREAD|||" — the second part posts as a threaded
  reply.
- Output only the final post text (or the two-part thread text)."""


def build_user_prompt(job: dict[str, Any] | None = None, short_link: str | None = None) -> str:
    """Format single job into Bluesky post user prompt."""
    j = job or {}
    title = j.get("title") or "Role"
    company = j.get("company") or "Company"
    city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
    country = j.get("country") or ""
    location_str = f"{city}, {country}".strip(", ")
    conf_label = j.get("confidence_label") or ("Verified" if j.get("visa_sponsorship_verified") else "Likely")
    visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa")
    salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Disclosed in post")
    summary = j.get("summary") or j.get("snippet") or "Full-time position with visa support."
    link_to_use = short_link or j.get("short_link") or "visalane.app/j"

    return (
        "Generate one Bluesky post about this job (or insight):\n\n"
        f"Title: {title} | Company: {company} | Location: {location_str}\n"
        f"Confidence: {conf_label} | Visa type(s): {visa_types} | Salary: {salary}\n"
        f"Summary: {summary} | Short link: {link_to_use}\n\n"
        "Follow the system rules exactly."
    )

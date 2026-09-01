"""Discord embed JSON prompts and template formatting (Part 3.2)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are generating the TEXT CONTENT for a Discord embed on Visa Lane's #job-feed channel.
You do not control layout (that's the embed schema) — you generate: an embed title, a
one-sentence description/hook, and short field values.

Style rules:
- Slightly more relaxed than a press release, still information-dense. Discord readers
  want fast, useful data.
- Confidence tier maps to a colored circle emoji, always prefixed to the confidence field:
  🟢 High, 🟡 Medium, 🔴 Unclear/Low. Never use a color that doesn't match the actual
  confidence_label passed in.
- Use 🌍 for location, 💼 for role type, 💰 for salary as field-label prefixes — not
  inline in sentences.
- No more than one short sentence for the description/hook. No hype adjectives unsupported
  by the data.
- Output must be valid JSON matching the schema given, nothing else.

Output schema:
{
  "title": "string, max 100 chars",
  "description": "string, max 200 chars, one sentence",
  "fields": {
    "location": "🌍 string",
    "role_type": "💼 string",
    "confidence": "🟢/🟡/🔴 string",
    "salary": "💰 string or 'Not disclosed'",
    "visa_types": "string"
  }
}"""

DISCORD_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "fields": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "role_type": {"type": "string"},
                "confidence": {"type": "string"},
                "salary": {"type": "string"},
                "visa_types": {"type": "string"},
            },
            "required": ["location", "role_type", "confidence", "salary", "visa_types"],
        },
    },
    "required": ["title", "description", "fields"],
}


def build_user_prompt(job: dict[str, Any]) -> str:
    """Format single job into Discord embed user prompt."""
    title = job.get("title") or "Role"
    company = job.get("company") or "Company"
    city = job.get("city") or job.get("location_raw") or job.get("location") or "Worldwide"
    country = job.get("country") or ""
    location_str = f"{city}, {country}".strip(", ")
    conf_label = job.get("confidence_label") or ("High" if job.get("visa_sponsorship_verified") else "Medium")
    conf_score = job.get("visa_sponsorship_confidence") or job.get("visa_score") or 80
    visa_types = ", ".join(job.get("visa_types") or []) if isinstance(job.get("visa_types"), list) else str(job.get("visa_types") or "Work Visa")
    salary = job.get("salary_raw") or (f"{job.get('salary_min')}-{job.get('salary_max')} {job.get('salary_currency', 'USD')}" if job.get("salary_min") else "Not disclosed")
    summary = job.get("summary") or job.get("snippet") or "Full-time position with visa sponsorship support."

    return (
        f"Generate the Discord embed content for this job:\n\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location_str}\n"
        f"Sponsorship confidence: {conf_label} ({conf_score})\n"
        f"Visa type(s): {visa_types}\n"
        f"Salary: {salary}\n"
        f"Summary: {summary}\n\n"
        f"Return only the JSON object per the schema."
    )

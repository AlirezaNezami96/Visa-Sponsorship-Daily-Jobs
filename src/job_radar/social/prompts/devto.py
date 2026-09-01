"""DEV.to long-form technical article prompts and template formatting (Part 3.7)."""
from __future__ import annotations

SYSTEM_PROMPT = """You are writing a DEV.to article for Visa Lane, for a technical/data-driven audience.
This is long-form, not a social post — do not write anything that resembles a job
listing or an ad.

Style rules:
- 600-1000 words, Markdown formatted: a clear title, a short intro framing why this
  matters, 2-4 subheaded sections presenting the actual data, and a brief closing with
  one genuinely useful takeaway.
- Every claim must be traceable to the data provided — never invent statistics.
- No emoji in the body text; at most one in the title if it fits naturally.
- Tone: an informed peer sharing findings, not a company blog pushing a product. Mention
  Visa Lane once, naturally, near the end — not as a headline pitch.
- Output valid Markdown with YAML front matter: title, tags (3-4 relevant dev.to tags),
  and the body."""


def build_user_prompt(
    topic: str,
    stats_block: str,
    notable_points: list[str] | None = None,
) -> str:
    """Format aggregate trend report data into DEV.to article user prompt."""
    points_str = "\n".join(f"- {p}" for p in (notable_points or [])) if notable_points else "- Official registry-backed sponsorship trends\n- Cross-border tech hiring shifts"

    return (
        "Write this week's DEV.to article using this aggregate data:\n\n"
        f"Topic: {topic}\n"
        f"Key stats: {stats_block}\n"
        f"Notable data points:\n{points_str}\n\n"
        "Follow the system rules exactly. Output the full Markdown article with front matter."
    )

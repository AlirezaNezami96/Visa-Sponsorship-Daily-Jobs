"""Text preparation and URL-safe progressive truncation for social platforms.

Ensures posts fit within character or grapheme limits (e.g., X 280 chars, Bluesky 300 graphemes)
without ever breaking apply URLs.
"""
from __future__ import annotations

import re

try:
    import grapheme
except ImportError:
    grapheme = None  # type: ignore[assignment]


def get_text_length(text: str, is_grapheme: bool = False) -> int:
    """Return text length either in graphemes (Bluesky) or standard characters."""
    if is_grapheme and grapheme is not None:
        return grapheme.length(text)
    return len(text)


def truncate_keep_url(
    text: str,
    limit: int,
    url: str | None = None,
    is_grapheme: bool = False,
) -> str:
    """Truncate post text safely to limit without breaking URLs.

    Progressive strategy:
    1. If already within limit, return verbatim.
    2. Extract apply URL if present.
    3. Remove non-essential description/summary lines.
    4. Remove salary line if necessary.
    5. Compress whitespace.
    6. Hard-truncate prefix with ellipsis ('…') and re-append apply URL.
    """
    if get_text_length(text, is_grapheme) <= limit:
        return text

    # Detect URL in text if not explicitly passed
    if not url:
        url_match = re.search(r"https?://[^\s)]+", text)
        if url_match:
            url = url_match.group(0)

    url_suffix = f"\nApply: {url}" if url else ""
    suffix_len = get_text_length(url_suffix, is_grapheme)
    available_prefix_len = limit - suffix_len - 1  # 1 char for ellipsis

    if available_prefix_len <= 10:
        # URL is almost the entire limit; return url directly
        return url or text[:limit]

    # Remove the url from text to work only on the content prefix
    content = text
    if url:
        content = content.replace(url, "").replace("Apply:", "").replace("🔗 Apply here:", "")
        content = re.sub(r"\n\s*\n+", "\n\n", content).strip()

    # Step 3: Remove summary/quote lines
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    reduced_lines = [l for l in lines if not l.startswith(">") and not l.startswith("💡")]
    candidate = "\n".join(reduced_lines) + url_suffix
    if get_text_length(candidate, is_grapheme) <= limit:
        return candidate

    # Step 4: Remove salary lines if still overflowing
    reduced_lines = [l for l in reduced_lines if not l.startswith("💰") and "Salary:" not in l]
    candidate = "\n".join(reduced_lines) + url_suffix
    if get_text_length(candidate, is_grapheme) <= limit:
        return candidate

    # Step 5: Compress whitespace
    compressed_content = " ".join(lines)
    candidate = f"{compressed_content}{url_suffix}"
    if get_text_length(candidate, is_grapheme) <= limit:
        return candidate

    # Step 6: Hard-truncate prefix with ellipsis
    if is_grapheme and grapheme is not None:
        truncated_prefix = grapheme.slice(compressed_content, 0, available_prefix_len)
    else:
        truncated_prefix = compressed_content[:available_prefix_len]

    return f"{truncated_prefix.rstrip()}…{url_suffix}"

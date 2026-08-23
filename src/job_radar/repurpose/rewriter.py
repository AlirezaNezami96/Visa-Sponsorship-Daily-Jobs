"""Gemini 3.7 Flash Content Rewriter & Quality Validator."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.llm.router import complete
from job_radar.repurpose.deduplicator import ContentDeduplicator
from job_radar.repurpose.models import SourcePostRecord

logger = logging.getLogger(__name__)

REPURPOSE_SYSTEM_INSTRUCTION = """# SYSTEM ROLE: Senior Software Engineer & AI Creator (Alireza Nezami)

You are adapting a curated developer/AI LinkedIn post into an original, high-value post for your own profile.

# CORE RULES:
1. **Preserve the Core Idea & Value**: Keep the technical insight, utility, tool recommendations, and practical steps from the source.
2. **Original & Natural Phrasing**: Completely rewrite the text in your own authentic, concise voice. Do NOT copy distinctive sentences verbatim.
3. **Strip All Original Author Branding**:
   - Never mention the original creator's name, handle, or identity.
   - Remove self-promotional calls-to-action like "Follow me for more", "Follow [Name]", "Repost to support", "Link in bio".
4. **Attribution & Truthfulness**:
   - If the source discusses a specific open-source repo, library, paper, or tool, preserve factual attribution to that tool/project.
   - Do NOT claim you created third-party tools or libraries.
   - Do NOT invent fake personal metrics, exaggerated benchmarks, or fictional backstories.
5. **Formatting**:
   - High readability: Short 1-2 sentence paragraphs.
   - Use bullet points (`-` or `•`) for lists and step-by-step breakdowns.
   - Keep tone helpful, punchy, and professional.
6. **Output Format**:
   - Output ONLY the final LinkedIn post text.
   - Do NOT wrap in quotes. Do NOT add meta commentary like "Here is the rewritten post:".
"""


class ContentRewriter:
    """Adapts source posts into original LinkedIn posts using Gemini with validation."""

    def __init__(self, model_name: str = "gemini-3.7-flash"):
        self.model_name = os.environ.get("GEMINI_FLASH_MODEL", model_name)
        self.dedup = ContentDeduplicator()

    def create_prompt(self, post: SourcePostRecord) -> str:
        """Constructs prompt for Gemini adaptation."""
        media_context = f"Post Media Type: {post.media_type}"
        if post.media_type == "video":
            media_context += " (This post will be accompanied by a video demo)"
        elif post.media_type in ("image", "multi_image"):
            media_context += " (This post will be accompanied by an image diagram/infographic)"

        prompt = f"""[SOURCE POST CONTEXT]
{media_context}

[SOURCE POST CONTENT]
{post.content}

---
Please rewrite and adapt the post above into an original, engaging LinkedIn post following the system instructions.
Output ONLY the final post text:"""
        return prompt

    def sanitize_output(
        self,
        adapted_text: str,
        author_name: Optional[str] = None,
        author_username: Optional[str] = None,
    ) -> str:
        """Cleans residual intro prefixes, meta text, and author handles."""
        text = adapted_text.strip()

        # Remove markdown code fences if model wrapped the post in ```
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        # Remove leading intro phrases
        text = re.sub(r"^(here('s| is) (the |your )?(rewritten |adapted )?(linkedin )?post:?\s*)", "", text, flags=re.IGNORECASE).strip()

        # Strip specific author mentions if accidentally present (full name and components)
        if author_name and len(author_name) > 2:
            clean_name = re.sub(r"[^\w\s]", "", author_name).strip()
            if clean_name:
                pattern = re.compile(rf"\b{re.escape(clean_name)}\b", re.IGNORECASE)
                text = pattern.sub("", text)
                for part in clean_name.split():
                    if len(part) >= 3:
                        part_pattern = re.compile(rf"\b{re.escape(part)}\b", re.IGNORECASE)
                        text = part_pattern.sub("", text)

        if author_username and len(author_username) > 2:
            clean_handle = author_username.lstrip("@")
            pattern = re.compile(rf"@?\b{re.escape(clean_handle)}\b", re.IGNORECASE)
            text = pattern.sub("", text)

        # Remove common trailing CTAs & self-promos
        cta_patterns = [
            r"(?i)\bfollow\s+.*",
            r"(?i)\brepost\s+.*",
            r"(?i)\blike\s+and\s+repost\b.*",
            r"(?i)\bdefinitely\s+save\s+it\s+for\s+later.*",
        ]
        for cta in cta_patterns:
            text = re.sub(cta, "", text).strip()

        # Clean up double spaces created by stripping
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    def validate_adaptation(
        self,
        adapted_text: str,
        source_text: str,
        author_name: Optional[str] = None,
        author_username: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Deterministic post quality and anti-copying verification:
          - Non-empty
          - Dynamic length limit based on source brevity (15 to 3000 chars)
          - Not identical or nearly identical to source (< 90% sequence similarity)
          - Does not contain original author name/handle
        """
        if not adapted_text or not adapted_text.strip():
            return False, "Generated text is empty."

        clean_text = adapted_text.strip()
        source_len = len(source_text.strip()) if source_text else 0
        min_len = 15 if source_len < 60 else (30 if source_len < 100 else 45)

        if len(clean_text) < min_len:
            return False, f"Generated text too short ({len(clean_text)} chars, expected at least {min_len})."

        if len(clean_text) > 3000:
            return False, f"Generated text exceeds LinkedIn character limit ({len(clean_text)}/3000 chars)."

        # Check sequence similarity against source
        seq_ratio = self.dedup.sequence_similarity(clean_text, source_text)
        if seq_ratio > 0.90:
            return False, f"Adaptation is too close to source (similarity: {seq_ratio:.2f})."

        # Check token Jaccard similarity
        jaccard = self.dedup.token_jaccard_similarity(clean_text, source_text)
        if jaccard > 0.88:
            return False, f"Adaptation shares too many exact tokens with source (Jaccard: {jaccard:.2f})."

        # Check author name / username leakage
        if author_name and len(author_name) > 3:
            clean_name = re.sub(r"[^\w\s]", "", author_name).strip()
            if clean_name and re.search(rf"\b{re.escape(clean_name)}\b", clean_text, re.IGNORECASE):
                return False, f"Original author name '{author_name}' detected in adapted text."

        if author_username and len(author_username) > 3:
            clean_handle = author_username.lstrip("@")
            if clean_handle and re.search(rf"@?\b{re.escape(clean_handle)}\b", clean_text, re.IGNORECASE):
                return False, f"Original author handle '{author_username}' detected in adapted text."

        return True, None

    def adapt_post(
        self,
        post: SourcePostRecord,
        max_retries: int = 2,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Adapts source post with Gemini and validates result.
        Returns: (success, adapted_text, error_message)
        """
        prompt = self.create_prompt(post)

        for attempt in range(max_retries + 1):
            logger.info("Calling Gemini for post adaptation (Attempt %d/%d)...", attempt + 1, max_retries + 1)
            temp = 0.4 if attempt == 0 else 0.7

            result = complete(
                prompt=prompt,
                system_instruction=REPURPOSE_SYSTEM_INSTRUCTION,
                temperature=temp,
            )

            raw_text = (result.text or "").strip()
            sanitized = self.sanitize_output(
                raw_text,
                author_name=post.author_name,
                author_username=post.author_username,
            )

            valid, err = self.validate_adaptation(
                sanitized,
                source_text=post.content,
                author_name=post.author_name,
                author_username=post.author_username,
            )

            if valid:
                logger.info("Gemini adaptation completed and validated successfully (Length: %d chars).", len(sanitized))
                return True, sanitized, None
            else:
                logger.warning("Adaptation validation failed on attempt %d: %s", attempt + 1, err)

        return False, "", err or "Failed to generate valid adapted content after retries."

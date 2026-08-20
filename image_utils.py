"""Cover image utilities (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.social.images import (
    ACTIVE_IMAGE_PROVIDER,
    FONT_FILE,
    create_professional_cover_image,
    draw_pil_gradient_background,
    ensure_font_downloaded,
    fetch_gemini_background_image,
    fetch_pollinations_background_image,
    generate_tech_illustration,
)

__all__ = [
    "FONT_FILE",
    "ACTIVE_IMAGE_PROVIDER",
    "ensure_font_downloaded",
    "fetch_gemini_background_image",
    "fetch_pollinations_background_image",
    "draw_pil_gradient_background",
    "generate_tech_illustration",
    "create_professional_cover_image",
]

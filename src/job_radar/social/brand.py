"""VisaLane brand constants: colors, canvas geometry, bundled OFL fonts.

The card renderer and PDF builder share these so every rendered surface is
pixel-consistent with the reference card. Fonts are OFL-licensed TTFs committed
to assets/fonts/ (Poppins + Inter statics). System fonts are NEVER used —
a missing bundled font is a hard error, not a silent fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import ImageFont  # pragma: no cover

REPO_ROOT = Path(__file__).resolve().parents[3]
FONTS_DIR = REPO_ROOT / "assets" / "fonts"

CARD_WIDTH = 1350
CARD_HEIGHT = 1200

CONTENT_X = 320
CONTENT_RIGHT = 1265
CONTENT_WIDTH = CONTENT_RIGHT - CONTENT_X

# The white content panel. The landmark photo sits under the full canvas and
# stays visible only left of this slanted edge (diagonal top(250,0)->bottom(140,H)),
# which keeps every content element (x >= CONTENT_X) on the panel.
WHITE_POLYGON: list[tuple[int, int]] = [
    (250, 0),
    (CARD_WIDTH, 0),
    (CARD_WIDTH, CARD_HEIGHT),
    (140, CARD_HEIGHT),
]

NAVY = "#0E1B3C"
RED = "#E23B3B"
INDIGO = "#4F46E5"
GRAY = "#64748B"
HAIRLINE = "#E2E8F0"
PANEL = "#FFFFFF"

TAGLINE = "Verified visa sponsorship. Every listing checked."
FOOTER_LEFT = "Daily verified visa-sponsoring jobs"
FOOTER_RIGHT = "VISALANE.APP"

FONT_FILES = {
    "poppins_bold": "Poppins-Bold.ttf",
    "poppins_semibold": "Poppins-SemiBold.ttf",
    "inter_regular": "Inter-Regular.ttf",
    "inter_medium": "Inter-Medium.ttf",
    "inter_bold": "Inter-Bold.ttf",
}

_font_cache: dict[tuple[str, int], Any] = {}


def font_path(key: str) -> Path:
    """Absolute path of a bundled font. Raises if the OFL file is missing."""
    filename = FONT_FILES[key]
    path = FONTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Bundled font missing: {path}. System fonts are intentionally "
            "never used; restore assets/fonts/ from the repository."
        )
    return path


def get_font(key: str, size: int) -> ImageFont.FreeTypeFont:
    """Cached TrueType font loader keyed on (font, size).

    Pillow is imported lazily so non-image consumers (e.g. the PDF builder)
    can reuse `font_path` without a Pillow dependency.
    """
    from PIL import ImageFont

    cached = _font_cache.get((key, size))
    if cached is None:
        cached = ImageFont.truetype(str(font_path(key)), size)
        _font_cache[(key, size)] = cached
    return cached

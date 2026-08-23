"""Multi-platform font discovery and typography manager for creator badge rendering."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
from PIL import ImageFont


class FontManager:
    """Discovers available system or bundled fonts across macOS, Linux, and Windows."""

    @staticmethod
    def get_system_font_candidates(weight: str = "bold") -> list[str]:
        """Returns ordered list of candidate font paths based on OS and desired weight."""
        candidates: list[str] = []

        # 1. Project local font file
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        project_roboto = repo_root / "Roboto-Bold.ttf"
        if project_roboto.exists():
            candidates.append(str(project_roboto))

        # 2. macOS System Fonts
        if weight == "bold":
            candidates.extend([
                "/System/Library/Fonts/SFPro-Bold.ttf",
                "/System/Library/Fonts/SF-Pro-Text-Bold.otf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ])
        else:
            candidates.extend([
                "/System/Library/Fonts/SFPro-Regular.ttf",
                "/System/Library/Fonts/SF-Pro-Text-Regular.otf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ])

        # 3. Linux System Fonts
        if weight == "bold":
            candidates.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            ])
        else:
            candidates.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
            ])

        # 4. Windows System Fonts
        win_fonts = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
        if weight == "bold":
            candidates.extend([
                os.path.join(win_fonts, "segoeuib.ttf"),
                os.path.join(win_fonts, "arialbd.ttf"),
                os.path.join(win_fonts, "arial.ttf"),
            ])
        else:
            candidates.extend([
                os.path.join(win_fonts, "segoeui.ttf"),
                os.path.join(win_fonts, "arial.ttf"),
            ])

        return candidates

    @classmethod
    def resolve_font_path(cls, custom_path: Optional[str] = None, weight: str = "bold") -> Optional[str]:
        """Resolves a valid font path, checking custom override first, then platform candidates."""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        for candidate in cls.get_system_font_candidates(weight):
            if os.path.exists(candidate):
                return candidate

        return None

    @classmethod
    def load_font(cls, size: int, weight: str = "bold", custom_path: Optional[str] = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Loads a font at specified point size with fallback."""
        font_path = cls.resolve_font_path(custom_path, weight)
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass

        # Fallback to default PIL font
        return ImageFont.load_default()

    @classmethod
    def get_badge_fonts(
        cls,
        name_size: int,
        username_size: int,
        custom_path: Optional[str] = None
    ) -> Tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        """Loads both name font (bold) and username font (regular/medium)."""
        name_font = cls.load_font(name_size, weight="bold", custom_path=custom_path)
        username_font = cls.load_font(username_size, weight="regular", custom_path=custom_path)
        return name_font, username_font

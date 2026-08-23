"""Profile image processor with square center-cropping and anti-aliased circular masking."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageOps

from .exceptions import ProfileImageNotFoundError


class ProfileImageProcessor:
    """Handles loading, center-cropping, resizing, and circular masking of profile pictures."""

    @staticmethod
    def discover_profile_image(preferred_path: Optional[str | Path] = None) -> Path:
        """Finds a candidate profile image from preference or default project locations."""
        if preferred_path:
            p = Path(preferred_path)
            if p.exists() and p.is_file():
                return p
            raise ProfileImageNotFoundError(f"Specified profile image does not exist: {preferred_path}")

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        candidates = [
            repo_root / "assets" / "samples" / "ChatGPT Image Aug 11, 2026, 01_48_27 PM.jpg",
            repo_root / "assets" / "samples" / "exact_user_prompt_post.jpg",
            repo_root / "assets" / "samples" / "perfect_tech_illustration.jpg",
        ]

        for c in candidates:
            if c.exists() and c.is_file():
                return c

        samples_dir = repo_root / "assets" / "samples"
        if samples_dir.exists():
            for f in samples_dir.glob("*.jpg"):
                return f
            for f in samples_dir.glob("*.png"):
                return f

        raise ProfileImageNotFoundError(
            "No profile image found. Please provide a valid path or place an image in 'assets/samples/'."
        )

    @classmethod
    def create_circular_avatar(
        cls,
        image_path: Optional[str | Path],
        diameter: int,
        border_color: str = "#FFFFFF",
        border_width: int = 0,
    ) -> Image.Image:
        """Loads image, center-crops to square, applies anti-aliased circular mask, and resizes."""
        path_obj = cls.discover_profile_image(image_path)

        try:
            raw_img = Image.open(path_obj)
            # Correct EXIF rotation if needed
            img = ImageOps.exif_transpose(raw_img).convert("RGBA")
        except Exception as e:
            raise ProfileImageNotFoundError(f"Failed to open profile image '{image_path}': {e}") from e

        w, h = img.size
        # 1. Center crop to 1:1 square
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        cropped = img.crop((left, top, left + min_dim, top + min_dim))

        # 2. Render at 2x supersampling for smooth antialiasing
        scale = 2
        ss_diameter = diameter * scale
        resized = cropped.resize((ss_diameter, ss_diameter), Image.Resampling.LANCZOS)

        # 3. Create smooth circular mask
        mask = Image.new("L", (ss_diameter, ss_diameter), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, ss_diameter - 1, ss_diameter - 1), fill=255)

        avatar = Image.new("RGBA", (ss_diameter, ss_diameter), (0, 0, 0, 0))
        avatar.paste(resized, (0, 0), mask=mask)

        # 4. Optional crisp circular border
        if border_width > 0:
            border_draw = ImageDraw.Draw(avatar)
            ss_border = border_width * scale
            for i in range(ss_border):
                border_draw.ellipse(
                    (i, i, ss_diameter - 1 - i, ss_diameter - 1 - i),
                    outline=border_color,
                )

        # 5. Downsample to target diameter
        final_avatar = avatar.resize((diameter, diameter), Image.Resampling.LANCZOS)
        return final_avatar

"""Badge rendering engine with dynamic resolution scaling, text fitting, and 2x supersampling."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw

from .config import CreatorBadgeConfig, DEFAULT_CONFIG
from .font_manager import FontManager
from .image_processor import ProfileImageProcessor


class BadgeRenderer:
    """Renders the transparent composite creator badge."""

    def __init__(self, config: Optional[CreatorBadgeConfig] = None):
        self.config = config or DEFAULT_CONFIG

    def calculate_dimensions(self, video_width: int, video_height: int) -> Tuple[int, int, int]:
        """
        Calculates optimal pill height, avatar diameter, and base scale based on video resolution.
        """
        # Base scale references the minimum dimension for portrait/landscape consistency
        min_dim = min(video_width, video_height)
        max_dim = max(video_width, video_height)
        # Geometric mean weighting for balanced scaling across all aspect ratios
        scale_ref = math.sqrt(min_dim * max_dim)

        # Scale pill height proportionally (e.g. ~80px on 1080p, ~160px on 4K, ~55px on 720p)
        pill_h = max(36, min(240, int(scale_ref * 0.065)))
        # Avatar is slightly taller than pill for prominent social watermark look
        avatar_d = int(pill_h * 1.15)
        avatar_border = max(1, int(avatar_d * self.config.avatar_border_width_ratio))

        return pill_h, avatar_d, avatar_border

    def fit_text_fonts(
        self,
        name: str,
        username: str,
        target_name_size: int,
        target_user_size: int,
        max_text_width: int,
        custom_font_path: Optional[str] = None,
    ) -> Tuple[Any, Any, int, int]:
        """Dynamically scales down font sizes if text exceeds available pill width."""
        curr_name_size = target_name_size
        curr_user_size = target_user_size
        min_name_size = max(10, int(target_name_size * 0.55))
        min_user_size = max(8, int(target_user_size * 0.55))

        while curr_name_size >= min_name_size and curr_user_size >= min_user_size:
            name_font, user_font = FontManager.get_badge_fonts(
                curr_name_size, curr_user_size, custom_path=custom_font_path
            )
            name_bbox = name_font.getbbox(name) if hasattr(name_font, "getbbox") else (0, 0, curr_name_size * len(name) * 0.6, curr_name_size)
            user_bbox = user_font.getbbox(username) if hasattr(user_font, "getbbox") else (0, 0, curr_user_size * len(username) * 0.6, curr_user_size)

            name_w = name_bbox[2] - name_bbox[0]
            user_w = user_bbox[2] - user_bbox[0]
            max_w = max(name_w, user_w)

            if max_w <= max_text_width:
                return name_font, user_font, int(name_w), int(user_w)

            curr_name_size -= 1
            curr_user_size = max(min_user_size, int(curr_name_size * 0.78))

        # Return minimum sizes
        name_font, user_font = FontManager.get_badge_fonts(
            min_name_size, min_user_size, custom_path=custom_font_path
        )
        name_bbox = name_font.getbbox(name) if hasattr(name_font, "getbbox") else (0, 0, min_name_size * len(name) * 0.6, min_name_size)
        user_bbox = user_font.getbbox(username) if hasattr(user_font, "getbbox") else (0, 0, min_user_size * len(username) * 0.6, min_user_size)
        return name_font, user_font, int(name_bbox[2] - name_bbox[0]), int(user_bbox[2] - user_bbox[0])

    def render(
        self,
        video_width: int = 1920,
        video_height: int = 1080,
        profile_image_path: Optional[str | Path] = None,
        name: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Image.Image:
        """Renders the transparent creator badge tailored to the specified video resolution."""
        cand_name = name or self.config.name
        cand_username = username or self.config.username
        img_path = profile_image_path or self.config.profile_image_path

        pill_h, avatar_d, avatar_border = self.calculate_dimensions(video_width, video_height)

        # Avatar overlap: avatar extends outside pill by ~25% of avatar diameter
        avatar_overlap_x = int(avatar_d * 0.35)
        # Left margin inside pill before text starts (to clear avatar)
        text_start_offset = int(avatar_d * 0.78)
        right_padding = int(pill_h * 0.35)

        # Max allowable text width before downscaling (relative to video width)
        max_allowed_text_w = int(video_width * 0.35)

        target_name_size = int(pill_h * 0.36)
        target_user_size = int(pill_h * 0.28)

        name_font, user_font, name_w, user_w = self.fit_text_fonts(
            cand_name,
            cand_username,
            target_name_size,
            target_user_size,
            max_text_width=max_allowed_text_w,
            custom_font_path=self.config.custom_font_path,
        )

        text_block_w = max(name_w, user_w)
        pill_w = text_start_offset + text_block_w + right_padding

        # Total canvas dimensions accommodating avatar overhang
        canvas_w = avatar_overlap_x + pill_w
        canvas_h = max(pill_h, avatar_d)

        # Render with 2x supersampling for high DPI smoothness
        scale = 2
        ss_w = canvas_w * scale
        ss_h = canvas_h * scale
        ss_pill_w = pill_w * scale
        ss_pill_h = pill_h * scale
        ss_avatar_d = avatar_d * scale
        ss_overlap_x = avatar_overlap_x * scale
        ss_text_offset_x = (avatar_overlap_x + text_start_offset) * scale

        # Base transparent layer
        badge = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)

        # 1. Draw Pill Background
        pill_top = (ss_h - ss_pill_h) // 2
        pill_bottom = pill_top + ss_pill_h
        pill_left = ss_overlap_x
        pill_right = pill_left + ss_pill_w
        pill_radius = ss_pill_h // 2

        draw.rounded_rectangle(
            [(pill_left, pill_top), (pill_right, pill_bottom)],
            radius=pill_radius,
            fill=self.config.badge_bg_color,
        )

        # 2. Draw Circular Profile Picture
        avatar_img = ProfileImageProcessor.create_circular_avatar(
            image_path=img_path,
            diameter=ss_avatar_d,
            border_color=self.config.avatar_border_color,
            border_width=avatar_border * scale,
        )
        avatar_top = (ss_h - ss_avatar_d) // 2
        badge.paste(avatar_img, (0, avatar_top), mask=avatar_img)

        # 3. Draw Text (Name & Username)
        ss_name_font, ss_user_font = FontManager.get_badge_fonts(
            name_size=target_name_size * scale,
            username_size=target_user_size * scale,
            custom_path=self.config.custom_font_path,
        )

        # Refit for 2x scale
        ss_name_font, ss_user_font, _, _ = self.fit_text_fonts(
            cand_name,
            cand_username,
            target_name_size * scale,
            target_user_size * scale,
            max_text_width=max_allowed_text_w * scale,
            custom_font_path=self.config.custom_font_path,
        )

        # Vertical spacing
        name_bbox = ss_name_font.getbbox(cand_name) if hasattr(ss_name_font, "getbbox") else (0, 0, 0, target_name_size * scale)
        name_h = name_bbox[3] - name_bbox[1]

        user_bbox = ss_user_font.getbbox(cand_username) if hasattr(ss_user_font, "getbbox") else (0, 0, 0, target_user_size * scale)
        user_h = user_bbox[3] - user_bbox[1]

        text_gap = int(4 * scale)
        total_text_h = name_h + text_gap + user_h
        text_start_y = (ss_h - total_text_h) // 2 - int(2 * scale)

        # Name line
        name_y = text_start_y - (name_bbox[1] if hasattr(ss_name_font, "getbbox") else 0)
        draw.text(
            (ss_text_offset_x, name_y),
            cand_name,
            fill=self.config.name_color,
            font=ss_name_font,
        )

        # Username line
        user_y = text_start_y + name_h + text_gap - (user_bbox[1] if hasattr(ss_user_font, "getbbox") else 0)
        draw.text(
            (ss_text_offset_x, user_y),
            cand_username,
            fill=self.config.username_color,
            font=ss_user_font,
        )

        # 4. Downsample to target size with LANCZOS
        final_badge = badge.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
        return final_badge

"""Deterministic brand-card renderer (pure Pillow — no AI, no browser).

Renders the VisaLane job card, pixel-faithful to the reference layout
(docs): photo layer (or deterministic fallback) under a slanted white panel,
logo lockup, auto-fitting job title, location line, visa badge, apply-with-AI
row, tagline and footer.

Pure function of its inputs: same inputs produce identical PNG bytes.
Rendering must never raise for missing photos — `photo_bytes=None` (or any
undecodable payload) falls back to the solid navy + red diagonal band
background.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from job_radar.social import brand

MIN_BADGE_CONFIDENCE = 60
BADGE_SHIFT = 120

TITLE_SIZES = (96, 80, 66)


@dataclass(frozen=True)
class CardJob:
    """Minimal job payload needed to render a card."""

    title: str
    country: str = ""
    city: str | None = None
    work_mode: str | None = None
    visa_sponsorship_verified: bool = False
    visa_sponsorship_confidence: int = 0


@dataclass(frozen=True)
class CardLayout:
    """Deterministic vertical layout for one card."""

    show_badge: bool
    badge_y: int
    apply_y: int
    tagline_y: int
    hairline_y: int
    footer_y: int


def compute_layout(job: CardJob) -> CardLayout:
    """Badge shows only for verified sponsors or confidence >= 60.

    When omitted, all rows at/below the badge shift up by BADGE_SHIFT so the
    composition stays balanced — a deterministic function of the job.
    """
    show_badge = bool(job.visa_sponsorship_verified) or int(job.visa_sponsorship_confidence) >= MIN_BADGE_CONFIDENCE
    shift = 0 if show_badge else -BADGE_SHIFT
    return CardLayout(
        show_badge=show_badge,
        badge_y=730 + shift,
        apply_y=905 + shift,
        tagline_y=972 + shift,
        hairline_y=1050 + shift,
        footer_y=1108 + shift,
    )


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _spaced(font, size_em: float) -> float:
    """Letter spacing in px derived from the font size (em-based)."""
    return font.size * size_em


def _measure_spaced(draw: ImageDraw.ImageDraw, text: str, font, spacing_em: float) -> float:
    width = 0.0
    for i, ch in enumerate(text):
        width += font.getlength(ch)
        if i < len(text) - 1:
            width += _spaced(font, spacing_em)
    return width


def _draw_spaced(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font,
    fill: str,
    spacing_em: float,
    anchor: str = "la",
) -> float:
    """Draw text with manual letter spacing; returns total advance width."""
    width = _measure_spaced(draw, text, font, spacing_em)
    x = xy[0]
    baseline_anchor = anchor.endswith("b")
    if anchor.startswith("r"):
        x = xy[0] - width
    elif anchor.startswith("m"):
        x = xy[0] - width / 2
    y_anchor = "lb" if baseline_anchor else "la"
    for i, ch in enumerate(text):
        draw.text((x, xy[1]), ch, font=font, fill=fill, anchor=f"l{y_anchor[1]}")
        x += font.getlength(ch)
        if i < len(text) - 1:
            x += _spaced(font, spacing_em)
    return width


def _wrap(text: str, font, max_width: float) -> list[str]:
    """Greedy word wrap measured with the real font metrics."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_title(text: str, max_width: float) -> tuple[list[str], int]:
    """Auto-fit: 96px -> 80px -> 66px, max 2 lines (reference card rule)."""
    for size in TITLE_SIZES:
        font = brand.get_font("poppins_bold", size)
        lines = _wrap(text, font, max_width)
        if len(lines) <= 2 and all(font.getlength(line) <= max_width for line in lines):
            return lines[:2], size
    font = brand.get_font("poppins_bold", TITLE_SIZES[-1])
    lines = _wrap(text, font, max_width)
    return lines[:2], TITLE_SIZES[-1]


# ---------------------------------------------------------------------------
# Icon primitives (all drawn, never bitmap assets)
# ---------------------------------------------------------------------------


def _draw_pin(draw: ImageDraw.ImageDraw, x: int, top: int, color: str = brand.RED) -> None:
    """Map pin: filled circle r=14 + downward triangle, 40px tall."""
    r = 14
    cx = x + 20
    circle_top = top
    circle_bottom = circle_top + 2 * r
    draw.ellipse([cx - r, circle_top, cx + r, circle_bottom], fill=color)
    draw.polygon([(cx - r + 3, circle_bottom - 8), (cx + r - 3, circle_bottom - 8), (cx, top + 40)], fill=color)


def _draw_globe(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_center: int,
    diameter: int,
    color: str,
    stroke: int = 4,
) -> None:
    """Globe: circle outline + vertical ellipse + horizontal line."""
    r = diameter / 2
    box = [x, y_center - r, x + diameter, y_center + r]
    draw.ellipse(box, outline=color, width=stroke)
    draw.ellipse([x + diameter * 0.28, box[1], x + diameter * 0.72, box[3]], outline=color, width=stroke)
    draw.line([x, y_center, x + diameter, y_center], fill=color, width=stroke)


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: str) -> None:
    """4-point sparkle star."""
    inner = r * 0.32
    points = []
    for i in range(8):
        angle_radius = r if i % 2 == 0 else inner
        angle = (i * 45 - 90) * math.pi / 180
        points.append((cx + angle_radius * math.cos(angle), cy + angle_radius * math.sin(angle)))
    draw.polygon(points, fill=color)


def _draw_sparkles(draw: ImageDraw.ImageDraw, x: int, top: int) -> None:
    """Indigo sparkle pair: one large 4-point star + one small at top-right."""
    size = 52
    _draw_star(draw, x + 20, top + 32, 20, brand.INDIGO)
    _draw_star(draw, x + 44, top + 10, 10, brand.INDIGO)
    _ = size


def _draw_logo_mark(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """VisaLane 'V/7' line-mark: straight polyline strokes, width 6, RED.

    Two strokes form the V, a third forms the crossing 7-stroke inside a
    65x80 box. Pure vector, deterministic.
    """
    w = 6
    pts_v_left = [(x + 0, y + 8), (x + 22, y + 78)]
    pts_v_right = [(x + 44, y + 8), (x + 22, y + 78)]
    pts_cross = [(x + 12, y + 40), (x + 62, y + 6)]
    for pts in (pts_v_left, pts_v_right, pts_cross):
        draw.line(pts, fill=brand.RED, width=w)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


def _cover_fit(photo: Image.Image) -> Image.Image:
    """Cover-fit the photo to the full canvas (center-cropped)."""
    return ImageOps.fit(photo.convert("RGB"), (brand.CARD_WIDTH, brand.CARD_HEIGHT))


def _fallback_background(draw: ImageDraw.ImageDraw) -> None:
    """Solid NAVY with a single subtle RED diagonal band parallel to the panel edge."""
    draw.rectangle([0, 0, brand.CARD_WIDTH, brand.CARD_HEIGHT], fill=brand.NAVY)
    # Band runs along the photo side of WHITE_POLYGON's slanted edge.
    band_poly = [
        (brand.WHITE_POLYGON[0][0] - 150, 0),
        (brand.WHITE_POLYGON[0][0] - 30, 0),
        (brand.WHITE_POLYGON[3][0] - 30, brand.CARD_HEIGHT),
        (brand.WHITE_POLYGON[3][0] - 150, brand.CARD_HEIGHT),
    ]
    draw.polygon(band_poly, fill=brand.RED)


def _load_photo(photo_bytes: bytes | None) -> Image.Image | None:
    """Decode photo bytes; any failure yields None (fallback background)."""
    if not photo_bytes:
        return None
    try:
        with Image.open(io.BytesIO(photo_bytes)) as img:
            img.load()
        return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


def _location_parts(job: CardJob) -> tuple[str | None, str | None]:
    """(navy_part, red_part) for the location line; None entries skipped."""
    remote = (job.work_mode or "").strip().lower() == "remote"
    country = (job.country or "").strip()
    city = (job.city or "").strip()
    if remote:
        return (None, f"Remote — {country}" if country else "Remote (Worldwide)")
    if city and country:
        return (f"{city}, ", country)
    if city:
        return (f"{city}", None)
    return (None, country or None)


def _draw_footer_right(draw: ImageDraw.ImageDraw, y_baseline: int) -> None:
    font = brand.get_font("inter_bold", 30)
    _draw_spaced(draw, (brand.CONTENT_RIGHT, y_baseline), brand.FOOTER_RIGHT, font, brand.RED, 0.04, anchor="rb")


def render_card(job: CardJob, photo_bytes: bytes | None = None) -> Image.Image:
    """Render the card image. Never raises on photo problems."""
    img = Image.new("RGB", (brand.CARD_WIDTH, brand.CARD_HEIGHT), brand.NAVY)
    draw = ImageDraw.Draw(img)

    photo = _load_photo(photo_bytes)
    if photo is not None:
        img.paste(_cover_fit(photo), (0, 0))
        draw = ImageDraw.Draw(img)
    else:
        _fallback_background(draw)

    # White content panel on top; photo remains visible left of the slanted edge.
    draw.polygon(brand.WHITE_POLYGON, fill=brand.PANEL)

    layout = compute_layout(job)

    # ── Logo lockup (right-aligned cluster) ──
    word_font = brand.get_font("poppins_semibold", 42)
    wordmark_width = _measure_spaced(draw, "VISA LANE", word_font, 0.35)
    word_x = brand.CONTENT_RIGHT - wordmark_width
    _draw_spaced(draw, (word_x, 165), "VISA LANE", word_font, brand.NAVY, 0.35, anchor="la")
    mark_x = int(word_x) - 22 - 65
    _draw_logo_mark(draw, max(mark_x, brand.CONTENT_X), 105)

    # ── Job title (auto-fit, max 2 lines) ──
    title_lines, title_size = _fit_title(job.title or "Untitled role", brand.CONTENT_WIDTH)
    title_font = brand.get_font("poppins_bold", title_size)
    line_h = int(title_size * 1.15)
    y = 300
    for line in title_lines:
        draw.text((brand.CONTENT_X, y), line, font=title_font, fill=brand.NAVY, anchor="la")
        y += line_h

    # ── Location ──
    pin_top = 596
    _draw_pin(draw, brand.CONTENT_X, pin_top)
    navy_part, red_part = _location_parts(job)
    loc_font = brand.get_font("inter_medium", 42)
    loc_y = pin_top + 40 + 16
    x: float = brand.CONTENT_X + 40 + 16
    if navy_part:
        draw.text((x, loc_y), navy_part, font=loc_font, fill=brand.NAVY, anchor="la")
        x += loc_font.getlength(navy_part)
    if red_part:
        draw.text((x, loc_y), red_part, font=loc_font, fill=brand.RED, anchor="la")

    # ── Divider ──
    draw.rectangle([brand.CONTENT_X, 675, brand.CONTENT_X + 100, 678], fill=brand.RED)

    # ── Badge ──
    if layout.show_badge:
        badge_font = brand.get_font("poppins_semibold", 40)
        text = "VISA SPONSORSHIP"
        text_w = _measure_spaced(draw, text, badge_font, 0.06)
        badge_w = int(30 + 44 + 18 + text_w + 30)
        badge_box = [brand.CONTENT_X, layout.badge_y, brand.CONTENT_X + badge_w, layout.badge_y + 86]
        draw.rounded_rectangle(badge_box, radius=14, fill=brand.RED)
        _draw_globe(draw, brand.CONTENT_X + 30, layout.badge_y + 43, 44, brand.PANEL, stroke=4)
        _draw_spaced(
            draw,
            (brand.CONTENT_X + 30 + 44 + 18, layout.badge_y + 43),
            text,
            badge_font,
            brand.PANEL,
            0.06,
            anchor="lm",
        )

    # ── Apply-with-AI row ──
    _draw_sparkles(draw, brand.CONTENT_X, layout.apply_y - 46)
    apply_font = brand.get_font("poppins_bold", 46)
    label = "Apply with "
    draw.text((brand.CONTENT_X + 52 + 14, layout.apply_y), label, font=apply_font, fill=brand.NAVY, anchor="la")
    ai_x = brand.CONTENT_X + 52 + 14 + apply_font.getlength(label)
    draw.text((ai_x, layout.apply_y), "AI", font=apply_font, fill=brand.INDIGO, anchor="la")

    # ── Tagline ──
    tag_font = brand.get_font("inter_regular", 28)
    draw.text((brand.CONTENT_X, layout.tagline_y), brand.TAGLINE, font=tag_font, fill=brand.GRAY, anchor="la")

    # ── Hairline ──
    draw.rectangle(
        [brand.CONTENT_X, layout.hairline_y, brand.CONTENT_RIGHT, layout.hairline_y + 1],
        fill=brand.HAIRLINE,
    )

    # ── Footer ──
    _draw_globe(draw, brand.CONTENT_X, layout.footer_y + 15, 30, brand.RED, stroke=3)
    foot_font = brand.get_font("inter_regular", 28)
    draw.text(
        (brand.CONTENT_X + 30 + 12, layout.footer_y), brand.FOOTER_LEFT, font=foot_font, fill=brand.GRAY, anchor="la"
    )
    _draw_footer_right(draw, layout.footer_y + 30)

    return img


def render_card_png(job: CardJob, photo_bytes: bytes | None = None) -> bytes:
    """Render to deterministic PNG bytes (identical inputs -> identical bytes)."""
    img = render_card(job, photo_bytes)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def card_job_from_row(row: dict[str, Any]) -> CardJob:
    """Build a CardJob from a `jobs` table row (PostgREST shape)."""
    company = row.get("companies") or {}
    country = row.get("country") or (company.get("country") if isinstance(company, dict) else None) or ""
    return CardJob(
        title=str(row.get("title") or "Untitled role"),
        country=str(country or ""),
        city=row.get("city"),
        work_mode=row.get("work_mode"),
        visa_sponsorship_verified=bool(row.get("visa_sponsorship_verified")),
        visa_sponsorship_confidence=int(row.get("visa_sponsorship_confidence") or 0),
    )

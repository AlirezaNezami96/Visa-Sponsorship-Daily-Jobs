"""Cover image utilities and visual asset generators."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import urllib.parse
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import requests

FONT_FILE = "Roboto-Bold.ttf"
ACTIVE_IMAGE_PROVIDER = "disabled"


def ensure_font_downloaded() -> str:
    """Ensures Roboto-Bold font is available locally."""
    if not os.path.exists(FONT_FILE):
        font_url = "https://github.com/google/fonts/raw/main/ofl/roboto/static/Roboto-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(FONT_FILE, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    return FONT_FILE if os.path.exists(FONT_FILE) else ""


def fetch_gemini_background_image(post_topic: str) -> Image.Image | None:
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return None

    topic_clean = post_topic.strip() if post_topic else "Mobile AI & Software Engineering"
    prompt = (
        "Create a modern professional LinkedIn post illustration for a software engineering / technology article.\n\n"
        "The image should visually represent the main idea of the post using a clean, minimal, premium style.\n"
        "Style: futuristic but professional, dark background with elegant blue and purple gradients.\n"
        f"Post topic: {topic_clean}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "16:9"}
        }
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=45)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates:
                for part in candidates[0].get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        img_bytes = base64.b64decode(inline["data"])
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                        return img.resize((1200, 675), Image.Resampling.LANCZOS)
    except Exception:
        pass

    return None


def fetch_pollinations_background_image(post_topic: str) -> Image.Image | None:
    api_key = os.environ.get("POLLINATIONS_API_KEY")
    topic_str = post_topic.strip() if post_topic else "Mobile AI & Software Engineering"

    full_prompt = (
        "Create a modern professional LinkedIn post illustration for a software engineering / technology article.\n\n"
        "Style: futuristic but professional, dark background with elegant blue and purple gradients.\n"
        f"Post topic: {topic_str}"
    )

    seed = random.randint(100, 999999)
    url = "https://image.pollinations.ai/prompt"
    if api_key:
        url += f"?api_key={api_key}"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "prompt": full_prompt,
        "width": 1200,
        "height": 675,
        "nologo": True,
        "seed": seed
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=45)
        if r.status_code == 200 and len(r.content) > 3000:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return img.resize((1200, 675), Image.Resampling.LANCZOS)
    except Exception:
        pass

    return None


def draw_pil_gradient_background(width: int = 1200, height: int = 675) -> Image.Image:
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 35)
        g = int(23 + (y / height) * 15)
        b = int(42 + (y / height) * 65)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base


def generate_tech_illustration(title: str, post_topic: str) -> tuple[bytes, str]:
    if ACTIVE_IMAGE_PROVIDER in ("disabled", "none", "off"):
        return b"", "disabled"

    width, height = 1200, 675
    base_img = None
    source = "pil_fallback"

    if ACTIVE_IMAGE_PROVIDER == "pollinations":
        base_img = fetch_pollinations_background_image(post_topic or title)
        source = "pollinations" if base_img else "pil_fallback"
    elif ACTIVE_IMAGE_PROVIDER == "gemini":
        base_img = fetch_gemini_background_image(post_topic or title)
        source = "gemini" if base_img else "pil_fallback"

    if not base_img:
        base_img = draw_pil_gradient_background(width, height)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    card_margin_x = 80
    card_margin_y = 120
    card_w = width - (card_margin_x * 2)
    card_h = height - (card_margin_y * 2)

    draw.rounded_rectangle(
        [(card_margin_x, card_margin_y), (card_margin_x + card_w, card_margin_y + card_h)],
        radius=20,
        fill=(10, 15, 30, 215),
        outline=(59, 130, 246, 255),
        width=3
    )

    font_path = ensure_font_downloaded()
    if font_path and os.path.exists(font_path):
        font_main = ImageFont.truetype(font_path, 46)
        font_sub = ImageFont.truetype(font_path, 22)
    else:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    cat_text = "SOFTWARE ENGINEERING"
    draw.text((card_margin_x + 40, card_margin_y + 35), cat_text, fill=(96, 165, 250, 255), font=font_sub)

    words = title.strip().upper().split()[:6]
    lines = []
    curr = ""
    for w in words:
        test = f"{curr} {w}".strip()
        bbox = font_main.getbbox(test)
        if (bbox[2] - bbox[0]) > (card_w - 80):
            lines.append(curr)
            curr = w
        else:
            curr = test
    if curr:
        lines.append(curr)

    line_y = card_margin_y + 80
    for line in lines[:2]:
        draw.text((card_margin_x + 40, line_y), line, fill=(255, 255, 255, 255), font=font_main)
        line_y += 58

    final = Image.alpha_composite(base_img, overlay).convert("RGB")
    out = io.BytesIO()
    final.save(out, format="JPEG", quality=95)
    cover_bytes = out.getvalue()
    return cover_bytes, source


def create_professional_cover_image(title: str, category: str = "SOFTWARE ENGINEERING", post_topic: str = "") -> tuple[bytes, str]:
    return generate_tech_illustration(title, post_topic)

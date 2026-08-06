import os
import io
import json
import base64
import hashlib
import requests
from PIL import Image, ImageDraw, ImageFont

FONT_FILE = "Roboto-Bold.ttf"

def ensure_font_downloaded() -> str:
    """Ensures Roboto-Bold font is available locally."""
    if not os.path.exists(FONT_FILE):
        font_url = "https://github.com/google/fonts/raw/main/ofl/roboto/static/Roboto-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(FONT_FILE, "wb") as f:
                    f.write(r.content)
                print(f"[INFO] Downloaded {FONT_FILE} ({os.path.getsize(FONT_FILE)} bytes).")
        except Exception as e:
            print(f"[WARN] Could not download {FONT_FILE}: {e}")
    return FONT_FILE if os.path.exists(FONT_FILE) else ""

def fetch_gemini_background_image(post_topic: str) -> Image.Image:
    """Calls Gemini API (gemini-2.5-flash-image) with responseModalities: ['IMAGE'].
    Raises an exception if the API returns an error or no image part is found.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY is not set in environment.")

    topic_clean = post_topic.strip()[:150] if post_topic else "software engineering and mobile development"
    prompt = (
        f"A clean, minimal, abstract digital illustration for a software engineering article about {topic_clean}. "
        "Dark slate and navy background, subtle glowing neon blue and purple nodes, geometric network lines, high contrast visual metaphor. "
        "No text, no letters, no words, no logos, no mascots."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": "16:9"
            }
        }
    }

    print(f"[INFO] Requesting background illustration from Gemini API (gemini-2.5-flash-image)...")
    res = requests.post(url, headers=headers, json=payload, timeout=60)
    res.raise_for_status()

    data = res.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini image call returned no candidates: {json.dumps(data)[:500]}")

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")

    image_bytes = None
    for part in candidate.get("content", {}).get("parts", []):
        if "inlineData" in part:
            b64_data = part["inlineData"].get("data")
            if b64_data:
                image_bytes = base64.b64decode(b64_data)
                break
        elif "inline_data" in part:
            b64_data = part["inline_data"].get("data")
            if b64_data:
                image_bytes = base64.b64decode(b64_data)
                break

    if image_bytes is None:
        raise RuntimeError(
            f"Gemini image call returned no inlineData. finishReason={finish_reason}, "
            f"raw response={json.dumps(data)[:500]}"
        )

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    return img.resize((1200, 675), Image.Resampling.LANCZOS)

def draw_pil_gradient_background(width: int = 1200, height: int = 675) -> Image.Image:
    """Fallback Tier 2: Generates a smooth dark slate gradient background."""
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 35)
        g = int(23 + (y / height) * 15)
        b = int(42 + (y / height) * 65)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base

def generate_tech_illustration(title: str, post_topic: str) -> tuple[bytes, bool]:
    """Creates a 16:9 LinkedIn cover illustration (1200x675).
    Returns (JPEG_bytes, is_fallback).
    """
    width, height = 1200, 675
    is_fallback = False

    # 1. Primary: Gemini Image Generation
    try:
        base_img = fetch_gemini_background_image(post_topic or title)
        print("[INFO] Gemini Image API background generated successfully.")
    except Exception as exc:
        is_fallback = True
        print(f"[ERROR] Gemini Image API call failed: {exc}")
        print("[WARN] Falling back to PIL dark gradient background.")
        base_img = draw_pil_gradient_background(width, height)

    # 2. Standard Path: Composite PIL title card overlay
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

    # Category badge
    cat_text = "SOFTWARE ENGINEERING"
    draw.text((card_margin_x + 40, card_margin_y + 35), cat_text, fill=(96, 165, 250, 255), font=font_sub)

    # Word-wrapped title text (2-5 words)
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

    md5_hash = hashlib.md5(cover_bytes).hexdigest()[:12]
    print(f"[INFO] Cover Image Output: Size={len(cover_bytes)} bytes, MD5={md5_hash}, IsFallback={is_fallback}")

    return cover_bytes, is_fallback

def create_professional_cover_image(title: str, category: str = "SOFTWARE ENGINEERING", post_topic: str = "") -> tuple[bytes, bool]:
    return generate_tech_illustration(title, post_topic)

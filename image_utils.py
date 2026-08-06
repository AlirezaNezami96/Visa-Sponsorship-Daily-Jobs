import os
import io
import base64
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

def fetch_gemini_background_image(post_topic: str) -> Image.Image | None:
    """Calls Gemini API (gemini-2.5-flash-image) to generate a background illustration without text."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("[WARN] GEMINI_API_KEY not set. Skipping Gemini image generation.")
        return None

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
        ]
    }

    try:
        print(f"[INFO] Requesting background illustration from Gemini API (gemini-2.5-flash-image)...")
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for p in parts:
                    inline = p.get("inlineData") or p.get("inline_data")
                    if inline:
                        b64_data = inline.get("data")
                        if b64_data:
                            img_bytes = base64.b64decode(b64_data)
                            img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                            print("[INFO] Successfully generated background image via Gemini API.")
                            return img.resize((1200, 675), Image.Resampling.LANCZOS)
        else:
            print(f"[WARN] Gemini Image API returned HTTP {res.status_code}: {res.text[:200]}")
    except Exception as e:
        print(f"[WARN] Failed to generate background image via Gemini API: {e}")

    return None

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

def generate_tech_illustration(title: str, post_topic: str) -> bytes:
    """Creates a 16:9 LinkedIn cover illustration (1200x675).
    Primary: Gemini Image API background + PIL composited title text.
    Fallback: PIL dark gradient background + PIL composited title text.
    """
    width, height = 1200, 675

    # 1. Primary: Try Gemini Image Generation
    base_img = fetch_gemini_background_image(post_topic or title)

    # 2. Fallback: Draw dark slate gradient background if Gemini image generation failed
    if base_img is None:
        print("[INFO] Falling back to PIL dark gradient background.")
        base_img = draw_pil_gradient_background(width, height)

    # 3. Standard Path: Composite PIL title card overlay
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
    return out.getvalue()

def create_professional_cover_image(title: str, category: str = "SOFTWARE ENGINEERING", post_topic: str = "") -> bytes:
    return generate_tech_illustration(title, post_topic)

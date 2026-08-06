import os
import io
import json
import base64
import random
import hashlib
import urllib.parse
import requests
from PIL import Image, ImageDraw, ImageFont

FONT_FILE = "Roboto-Bold.ttf"

# Configurable Active Image Provider: "gemini" | "pollinations"
ACTIVE_IMAGE_PROVIDER = "gemini"

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
    """Gemini Image API background generator (gemini-2.5-flash-image)."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("[WARN] GEMINI_API_KEY is not set.")
        return None

    topic_clean = post_topic.strip() if post_topic else "Mobile AI & Software Engineering"
    prompt = (
        "Create a modern professional LinkedIn post illustration for a software engineering / technology article.\n\n"
        "The image should visually represent the main idea of the post using a clean, minimal, premium style. "
        "Focus on concepts like innovation, software development, artificial intelligence, mobile apps, cloud technology, "
        "automation, or digital transformation depending on the topic.\n\n"
        "Style: futuristic but professional, suitable for a senior developer's LinkedIn profile. Use a dark background "
        "with elegant blue and purple gradients, subtle glowing elements, abstract UI interfaces, code elements, digital networks, "
        "and modern technology aesthetics.\n\n"
        "Include a short, bold title text in the center representing the main topic of the post (2-5 words maximum). "
        "Make the typography clean, modern, and highly readable.\n\n"
        "Avoid cartoon characters, mascots, exaggerated 3D illustrations, and overly busy designs. "
        "The image should look like it was created by a technology company for a LinkedIn announcement.\n\n"
        "Aspect ratio: 16:9.\n"
        "High quality, professional, minimal, visually striking.\n"
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
        print(f"[INFO] Requesting background illustration from Gemini API (gemini-2.5-flash-image)...")
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
                        print("[INFO] Gemini AI background generated successfully.")
                        return img.resize((1200, 675), Image.Resampling.LANCZOS)
        else:
            print(f"[WARN] Gemini Image API returned HTTP {res.status_code}: {res.text[:200]}")
    except Exception as e:
        print(f"[WARN] Gemini Image API call failed: {e}")

    return None

def fetch_pollinations_background_image(post_topic: str) -> Image.Image | None:
    """Active Image Provider: Fetches a 1200x675 (16:9) technology illustration from Pollinations.ai API."""
    api_key = os.environ.get("POLLINATIONS_API_KEY")

    topic_str = post_topic.strip() if post_topic else "Mobile AI & Software Engineering"

    full_prompt = (
        "Create a modern professional LinkedIn post illustration for a software engineering / technology article.\n\n"
        "The image should visually represent the main idea of the post using a clean, minimal, premium style. "
        "Focus on concepts like innovation, software development, artificial intelligence, mobile apps, cloud technology, "
        "automation, or digital transformation depending on the topic.\n\n"
        "Style: futuristic but professional, suitable for a senior developer's LinkedIn profile. Use a dark background "
        "with elegant blue and purple gradients, subtle glowing elements, abstract UI interfaces, code elements, digital networks, "
        "and modern technology aesthetics.\n\n"
        "Include a short, bold title text in the center representing the main topic of the post (2-5 words maximum). "
        "Make the typography clean, modern, and highly readable.\n\n"
        "Avoid cartoon characters, mascots, exaggerated 3D illustrations, and overly busy designs. "
        "The image should look like it was created by a technology company for a LinkedIn announcement.\n\n"
        "Aspect ratio: 16:9.\n"
        "High quality, professional, minimal, visually striking.\n"
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
        print(f"[INFO] Requesting 16:9 cover background from Pollinations.ai API (POST, seed={seed})...")
        print(f"[INFO] Image Generation Prompt:\n>>>\n{full_prompt}\n<<<")
        r = requests.post(url, headers=headers, json=payload, timeout=45)
        if r.status_code == 200 and len(r.content) > 3000:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            print("[INFO] Pollinations.ai background generated successfully.")
            return img.resize((1200, 675), Image.Resampling.LANCZOS)
        else:
            print(f"[ERROR] Pollinations.ai API call failed (HTTP {r.status_code}): {r.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Exception during Pollinations.ai image generation: {e}")

    return None

def draw_pil_gradient_background(width: int = 1200, height: int = 675) -> Image.Image:
    """Fallback Tier: Generates a smooth dark slate gradient background."""
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 35)
        g = int(23 + (y / height) * 15)
        b = int(42 + (y / height) * 65)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base

def generate_tech_illustration(title: str, post_topic: str) -> tuple[bytes, str]:
    """Service Layer Entrypoint: Generates a 16:9 LinkedIn cover illustration (1200x675).
    Returns (JPEG_bytes, image_source) where image_source is 'pollinations', 'gemini', or 'pil_fallback'.
    """
    width, height = 1200, 675
    base_img = None
    source = "pil_fallback"

    if ACTIVE_IMAGE_PROVIDER == "pollinations":
        print("[INFO] Active Image Provider: Pollinations.ai")
        base_img = fetch_pollinations_background_image(post_topic or title)
        if base_img:
            source = "pollinations"
        else:
            print("[WARN] Pollinations.ai generation failed. Falling back to PIL dark gradient background.")
            base_img = draw_pil_gradient_background(width, height)
            source = "pil_fallback"

    elif ACTIVE_IMAGE_PROVIDER == "gemini":
        print("[INFO] Active Image Provider: Gemini API")
        base_img = fetch_gemini_background_image(post_topic or title)
        if base_img:
            source = "gemini"
        else:
            print("[WARN] Gemini Image API generation failed. Falling back to PIL dark gradient background.")
            base_img = draw_pil_gradient_background(width, height)
            source = "pil_fallback"

    else:
        print(f"[WARN] Unknown provider '{ACTIVE_IMAGE_PROVIDER}'. Using PIL dark gradient background.")
        base_img = draw_pil_gradient_background(width, height)
        source = "pil_fallback"

    # Standard Path: Composite PIL title card overlay
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
    print(f"[INFO] Cover Image Output: Size={len(cover_bytes)} bytes, MD5={md5_hash}, Source={source}")

    return cover_bytes, source

def create_professional_cover_image(title: str, category: str = "SOFTWARE ENGINEERING", post_topic: str = "") -> tuple[bytes, str]:
    return generate_tech_illustration(title, post_topic)

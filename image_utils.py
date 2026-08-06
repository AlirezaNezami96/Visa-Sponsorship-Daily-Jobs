import os
import io
import base64
import urllib.parse
import requests
from PIL import Image, ImageDraw, ImageFont

FONT_FILE = "Roboto-Bold.ttf"

def ensure_font_downloaded() -> str:
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

def fetch_background_image(post_topic: str) -> Image.Image:
    width, height = 1200, 630
    prompt = (
        "Create a modern professional LinkedIn post illustration for a software engineering and technology article. "
        "Clean minimal premium style, visually representing innovation, software development, AI, mobile apps, or cloud technology. "
        "Style: futuristic but professional, suitable for a senior developer LinkedIn profile. "
        "Dark background with elegant blue and purple gradients, subtle glowing elements, abstract UI interfaces, code elements, digital networks. "
        "Avoid cartoon characters, mascots, exaggerated 3D illustrations, and overly busy designs. "
        "Looks like it was created by a technology company for a LinkedIn announcement. 16:9 aspect ratio, high quality. "
        f"Post topic: {post_topic}"
    )

    # 1. Gemini Image Generation API (if GEMINI_API_KEY is provided)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        models = ["gemini-2.5-flash-image", "gemini-2.0-flash"]
        for mod in models:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={gemini_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]}
            }
            try:
                print(f"[INFO] Requesting AI cover image from Gemini API ({mod})...")
                res = requests.post(gemini_url, headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for p in parts:
                            if "inlineData" in p:
                                b64_data = p["inlineData"].get("data")
                                if b64_data:
                                    img_bytes = base64.b64decode(b64_data)
                                    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                                    print("[INFO] Gemini AI cover background generated successfully.")
                                    return img.resize((width, height), Image.Resampling.LANCZOS)
                else:
                    print(f"[WARN] Gemini API returned HTTP {res.status_code}: {res.text[:200]}")
            except Exception as e:
                print(f"[WARN] Error calling Gemini Image API ({mod}): {e}")

    # 2. Pollinations FLUX Engine (Free fallback)
    encoded = urllib.parse.quote(prompt)
    poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&model=flux&nologo=true"
    try:
        print(f"[INFO] Fetching background illustration from Pollinations (FLUX)...")
        res = requests.get(poll_url, timeout=30)
        if res.status_code == 200 and len(res.content) > 2000:
            img = Image.open(io.BytesIO(res.content)).convert("RGBA")
            return img.resize((width, height), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"[WARN] Failed to fetch AI background image from Pollinations: {e}")

    # 3. Fallback to elegant dark blue & purple gradient background
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 30)
        g = int(20 + (y / height) * 20)
        b = int(50 + (y / height) * 60)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base

def create_professional_cover_image(
    title: str,
    category: str = "SOFTWARE ENGINEERING",
    post_topic: str = ""
) -> bytes:
    """Creates a professional 1200x630 LinkedIn cover illustration with centered headline text (2-5 words max).
    Returns JPEG bytes.
    """
    width, height = 1200, 630
    base_img = fetch_background_image(post_topic or title)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Centered dark semi-transparent card overlay with indigo border
    card_w = 920
    card_h = 240
    card_x = (width - card_w) // 2
    card_y = (height - card_h) // 2

    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=18,
        fill=(11, 19, 43, 220),
        outline=(99, 102, 241, 255),
        width=2
    )

    font_path = ensure_font_downloaded()
    if font_path and os.path.exists(font_path):
        font_main = ImageFont.truetype(font_path, 48)
        font_sub = ImageFont.truetype(font_path, 20)
    else:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Centered category badge
    cat_text = category.strip().upper() if category else "SOFTWARE ENGINEERING"
    cat_bbox = font_sub.getbbox(cat_text)
    cat_w = cat_bbox[2] - cat_bbox[0]
    draw.text(((width - cat_w) // 2, card_y + 30), cat_text, fill=(147, 197, 253, 255), font=font_sub)

    # Centered multi-line bold title (2-5 words max)
    clean_title = title.strip().upper()
    words = clean_title.split()[:6]
    lines = []
    curr = ""
    for w in words:
        test = f"{curr} {w}".strip()
        bbox = font_main.getbbox(test)
        if (bbox[2] - bbox[0]) > (card_w - 60):
            lines.append(curr)
            curr = w
        else:
            curr = test
    if curr:
        lines.append(curr)

    total_title_h = len(lines) * 56
    start_y = card_y + 80 + ((card_h - 110 - total_title_h) // 2)

    for line in lines[:2]:
        bbox = font_main.getbbox(line)
        line_w = bbox[2] - bbox[0]
        draw.text(((width - line_w) // 2, start_y), line, fill=(255, 255, 255, 255), font=font_main)
        start_y += 56

    final = Image.alpha_composite(base_img, overlay).convert("RGB")
    out = io.BytesIO()
    final.save(out, format="JPEG", quality=95)
    return out.getvalue()

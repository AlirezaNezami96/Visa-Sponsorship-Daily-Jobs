import os
import io
import random
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

def generate_tech_illustration(title: str, post_topic: str) -> bytes:
    """Generates a 16:9 modern professional LinkedIn tech illustration (dark blue/purple gradients)."""
    topic_clean = (post_topic or title).strip()[:100]
    title_clean = title.strip().upper()[:40]

    prompt = (
        f"Modern professional 16:9 LinkedIn technology post illustration representing {topic_clean}. "
        f"Futuristic professional style, dark background with elegant blue and purple gradients, subtle glowing elements, abstract UI interfaces, digital networks. "
        f"Bold centered title text: {title_clean}. "
        f"Minimalist premium corporate technology announcement, high quality, 8k."
    )

    width, height = 1200, 675
    seed = random.randint(100, 999999)
    encoded = urllib.parse.quote(prompt)
    poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"

    try:
        print(f"[INFO] Fetching 16:9 tech illustration from Pollinations FLUX (seed={seed})...")
        res = requests.get(poll_url, timeout=35)
        if res.status_code == 200 and len(res.content) > 3000:
            return res.content
    except Exception as e:
        print(f"[WARN] Failed to fetch AI illustration: {e}")

    # Fallback: Generate a high-resolution dark blue/purple gradient image with PIL
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 35)
        g = int(23 + (y / height) * 15)
        b = int(42 + (y / height) * 65)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))

    font_path = ensure_font_downloaded()
    if font_path and os.path.exists(font_path):
        font_main = ImageFont.truetype(font_path, 52)
        font_sub = ImageFont.truetype(font_path, 22)
    else:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Draw centered text overlay
    cat_text = "SOFTWARE ENGINEERING"
    cat_bbox = font_sub.getbbox(cat_text)
    cat_w = cat_bbox[2] - cat_bbox[0]
    draw.text(((width - cat_w) // 2, 220), cat_text, fill=(147, 197, 253, 255), font=font_sub)

    words = title_clean.split()[:6]
    lines = []
    curr = ""
    for w in words:
        test = f"{curr} {w}".strip()
        bbox = font_main.getbbox(test)
        if (bbox[2] - bbox[0]) > (width - 160):
            lines.append(curr)
            curr = w
        else:
            curr = test
    if curr:
        lines.append(curr)

    start_y = 280
    for line in lines[:2]:
        bbox = font_main.getbbox(line)
        line_w = bbox[2] - bbox[0]
        draw.text(((width - line_w) // 2, start_y), line, fill=(255, 255, 255, 255), font=font_main)
        start_y += 62

    final = base.convert("RGB")
    out = io.BytesIO()
    final.save(out, format="JPEG", quality=95)
    return out.getvalue()

def create_professional_cover_image(title: str, category: str = "SOFTWARE ENGINEERING", post_topic: str = "") -> bytes:
    return generate_tech_illustration(title, post_topic)

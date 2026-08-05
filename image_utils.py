import os
import io
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

def fetch_background_image(bg_prompt: str) -> Image.Image:
    width, height = 1200, 630
    if bg_prompt:
        clean_prompt = f"Simple minimal professional photography of {bg_prompt}, soft natural lighting, neutral colors, clean background, 8k"
        encoded = urllib.parse.quote(clean_prompt)
        poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&model=flux&nologo=true"
        try:
            print(f"[INFO] Fetching minimal background image from Pollinations...")
            res = requests.get(poll_url, timeout=25)
            if res.status_code == 200 and len(res.content) > 2000:
                img = Image.open(io.BytesIO(res.content)).convert("RGBA")
                return img.resize((width, height), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"[WARN] Failed to fetch AI background image: {e}")

    # Fallback to sleek slate-navy gradient
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw_bg = ImageDraw.Draw(base)
    for y in range(height):
        r = int(15 + (y / height) * 20)
        g = int(23 + (y / height) * 25)
        b = int(42 + (y / height) * 45)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base

def create_professional_cover_image(
    title: str,
    category: str = "MOBILE AI NEWS",
    bg_prompt: str = ""
) -> bytes:
    """Creates a professional 1200x630 cover image with a simple background and bold headline text.
    Returns JPEG bytes.
    """
    width, height = 1200, 630
    base_img = fetch_background_image(bg_prompt)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Dark semi-transparent card overlay
    card_margin_x = 70
    card_margin_y = 110
    card_w = width - (card_margin_x * 2)
    card_h = height - (card_margin_y * 2)

    draw.rounded_rectangle(
        [(card_margin_x, card_margin_y), (card_margin_x + card_w, card_margin_y + card_h)],
        radius=20,
        fill=(10, 15, 30, 215),
        outline=(59, 130, 246, 255),
        width=3
    )

    # Font setup
    font_path = ensure_font_downloaded()
    if font_path and os.path.exists(font_path):
        font_main = ImageFont.truetype(font_path, 44)
        font_sub = ImageFont.truetype(font_path, 22)
    else:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Category tag
    category_text = category.strip().upper() if category else "MOBILE AI NEWS"
    draw.text((card_margin_x + 40, card_margin_y + 35), category_text, fill=(96, 165, 250, 255), font=font_sub)

    # Multi-line title wrap
    clean_title = title.strip().upper()
    words = clean_title.split()
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
    for line in lines[:3]:
        draw.text((card_margin_x + 40, line_y), line, fill=(255, 255, 255, 255), font=font_main)
        line_y += 58

    final = Image.alpha_composite(base_img, overlay).convert("RGB")
    out = io.BytesIO()
    final.save(out, format="JPEG", quality=95)
    return out.getvalue()

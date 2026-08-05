import os
import random
import urllib.parse
import requests

STYLE_PRESETS = [
    "3D isometric tech illustration, dark futuristic UI with glowing neon cyan and purple accents, glassmorphic card containers, Octane render 8k, professional tech banner",
    "Sleek minimalist tech graphic, dark mode UI concept, glowing gradient waves, floating mobile app mockup elements, photorealistic studio lighting, 8k resolution",
    "Abstract artificial intelligence neural network nodes in 3D space, deep blue and electric violet color palette, frosted glass materials, premium tech design, 8k",
    "Modern mobile AI architecture concept, clean vector isometric artwork, dark theme UI components, glowing AI core, Octane 3D render, highly detailed 8k"
]

def engineer_image_prompt(base_prompt: str) -> str:
    cleaned = base_prompt.strip()
    style = random.choice(STYLE_PRESETS)
    return f"{cleaned}, {style}, no text overlay, high quality wallpaper"

def generate_ai_image(prompt: str, zai_api_key: str = None) -> tuple[str, bytes]:
    """Generates a high-quality AI cover image using HF FLUX, Z.ai CogView-3, or Pollinations FLUX.
    Returns (image_url, image_bytes).
    """
    enhanced_prompt = engineer_image_prompt(prompt)
    print(f"[INFO] Enhanced image prompt: '{enhanced_prompt}'")
    
    # 1. HuggingFace Inference API (if HF_TOKEN is configured)
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        hf_models = [
            "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        ]
        headers = {"Authorization": f"Bearer {hf_token}"}
        for hf_url in hf_models:
            try:
                res = requests.post(hf_url, headers=headers, json={"inputs": enhanced_prompt}, timeout=30)
                if res.status_code == 200 and len(res.content) > 2000:
                    print(f"[INFO] Image generated successfully via HuggingFace ({hf_url})")
                    return hf_url, res.content
            except Exception as e:
                print(f"[WARN] HuggingFace image generation error on {hf_url}: {e}")

    # 2. Z.ai CogView-3 Plus (if key provided)
    if zai_api_key:
        endpoints = [
            "https://api.z.ai/api/paas/v4/images/generations",
            "https://open.bigmodel.cn/api/paas/v4/images/generations"
        ]
        headers = {
            "Authorization": f"Bearer {zai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "cogview-3-plus",
            "prompt": enhanced_prompt,
            "size": "1024x1024"
        }
        for ep in endpoints:
            try:
                res = requests.post(ep, headers=headers, json=payload, timeout=35)
                if res.status_code == 200:
                    data = res.json()
                    img_url = data.get("data", [{}])[0].get("url")
                    if img_url:
                        img_res = requests.get(img_url, timeout=20)
                        if img_res.status_code == 200:
                            print(f"[INFO] Image generated successfully via Z.ai CogView-3 from {ep}")
                            return img_url, img_res.content
            except Exception as e:
                print(f"[WARN] Z.ai CogView image generation error on {ep}: {e}")

    # 3. Pollinations.ai FLUX (High-Quality free fallback)
    seed = random.randint(1000, 999999)
    encoded = urllib.parse.quote(enhanced_prompt)
    poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&seed={seed}&model=flux&nologo=true"
    try:
        print(f"[INFO] Fetching image from Pollinations.ai FLUX (seed={seed})...")
        res = requests.get(poll_url, timeout=30)
        if res.status_code == 200 and len(res.content) > 2000:
            return poll_url, res.content
    except Exception as e:
        print(f"[WARN] Pollinations.ai image generation error: {e}")

    # Fallback default image
    default_url = "https://picsum.photos/1200/630"
    res = requests.get(default_url, timeout=15)
    return default_url, res.content

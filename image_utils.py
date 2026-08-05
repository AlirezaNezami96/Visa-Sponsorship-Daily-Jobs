import os
import random
import urllib.parse
import requests

def generate_ai_image(prompt: str, zai_api_key: str = None) -> tuple[str, bytes]:
    """Generates an AI image using Z.ai CogView-3 (if key provided) or Pollinations.ai (free Flux).
    Returns (image_url, image_bytes).
    """
    clean_prompt = prompt.strip()
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
            "prompt": clean_prompt,
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
                print(f"[WARN] Z.ai CogView image generation failed on {ep}: {e}")

    # Fallback to Pollinations.ai (Flux model, 100% free)
    seed = random.randint(1000, 999999)
    encoded = urllib.parse.quote(clean_prompt)
    poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&seed={seed}&model=flux&nologo=true"
    try:
        print(f"[INFO] Fetching image from Pollinations.ai (seed={seed})...")
        res = requests.get(poll_url, timeout=25)
        if res.status_code == 200 and len(res.content) > 1000:
            return poll_url, res.content
    except Exception as e:
        print(f"[WARN] Pollinations.ai image generation error: {e}")

    # Ultimate fallback generic tech cover image if service unavailable
    default_url = "https://picsum.photos/1200/630"
    res = requests.get(default_url, timeout=15)
    return default_url, res.content

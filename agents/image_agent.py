"""
Image generation agent — free-tier only, 3 sources:
1. HuggingFace Inference API (FLUX.1-schnell or SDXL) — free with/without token
2. Pollinations.ai  — free, no key, retry on 530
3. Unsplash photo   — guaranteed fallback (real photo, no AI)
OpenAI skipped — billing_hard_limit_reached.
"""
import asyncio
import logging
import random
import time
import urllib.parse

import requests
from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Optional HF token — improves rate limits but not required
import os
HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

HF_HEADERS = {"Content-Type": "application/json"}
if HF_TOKEN:
    HF_HEADERS["Authorization"] = f"Bearer {HF_TOKEN}"

# HuggingFace models to try in order
HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "runwayml/stable-diffusion-v1-5",
]

IMAGE_STYLES = {
    "entrepreneurial": (
        "bold cinematic entrepreneur aesthetic, dark premium background, "
        "vibrant gradient accents electric blue deep purple gold, "
        "high contrast dramatic lighting, no people no text, abstract concept, ultra HD"
    ),
    "tech_minimal": (
        "clean minimal tech aesthetic, white light grey background, "
        "subtle geometric shapes circuit patterns, accent color electric blue, "
        "premium Apple-level design, no text no people, ultra sharp"
    ),
    "creative_dark": (
        "dark mode neon glow aesthetic, deep black navy background, "
        "neon purple cyan gold accents, abstract futuristic, "
        "glassmorphism cyberpunk professional, ultra detailed"
    ),
}


def _is_valid_image(data: bytes) -> bool:
    return len(data) > 4000 and (
        data[:2] == b'\xff\xd8'          # JPEG
        or data[:8] == b'\x89PNG\r\n\x1a\n'  # PNG
        or data[:4] == b'RIFF'           # WebP
        or b'GIF8' in data[:6]           # GIF
    )


def _fetch_huggingface(prompt: str) -> bytes:
    """Try HF models one by one. Waits 20s on 503 (model loading)."""
    short = prompt[:400]
    for model in HF_MODELS:
        url = f"https://api-inference.huggingface.co/models/{model}"
        logger.info(f"HuggingFace: trying {model}…")
        for attempt in range(2):
            try:
                resp = requests.post(
                    url,
                    headers=HF_HEADERS,
                    json={"inputs": short, "options": {"wait_for_model": True}},
                    timeout=90,
                )
                if resp.status_code == 200:
                    data = resp.content
                    if _is_valid_image(data):
                        logger.info(f"✅ HuggingFace {model} → {len(data)} bytes")
                        return data
                    logger.warning(f"HF {model}: response not valid image ({len(data)} bytes), CT={resp.headers.get('Content-Type')}")
                    break  # try next model
                elif resp.status_code == 503:
                    if attempt == 0:
                        logger.info(f"HF {model}: model loading, waiting 25s…")
                        time.sleep(25)
                    else:
                        logger.warning(f"HF {model}: still 503 after wait")
                        break
                elif resp.status_code == 401:
                    logger.warning(f"HF {model}: 401 — needs token. Add HUGGINGFACE_TOKEN to .env")
                    break
                else:
                    logger.warning(f"HF {model}: HTTP {resp.status_code} {resp.text[:80]}")
                    break
            except Exception as e:
                logger.warning(f"HF {model} attempt {attempt+1} error: {e}")
                break
    raise RuntimeError("HuggingFace: all models failed")


def _fetch_pollinations(prompt: str) -> bytes:
    """Pollinations.ai — retry 3x, shorten prompt each time."""
    short = prompt[:150] # Keep prompt very short
    for attempt in range(3):
        seed    = random.randint(1, 99999)
        encoded = urllib.parse.quote(short, safe="")
        # Minimal parameters to avoid 530 error
        url     = f"https://image.pollinations.ai/prompt/{encoded}?seed={seed}&width=1024&height=1024"
        logger.info(f"Pollinations attempt {attempt+1}: {url[:90]}…")
        try:
            resp = requests.get(url, timeout=90, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                data = resp.content
                if _is_valid_image(data):
                    logger.info(f"✅ Pollinations → {len(data)} bytes")
                    return data
                logger.warning(f"Pollinations: not a valid image ({resp.status_code}, {len(data)}B, CT={resp.headers.get('Content-Type')})")
            else:
                logger.warning(f"Pollinations HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Pollinations attempt {attempt+1} error: {e}")
        short = short[:max(30, len(short) // 2)]
        if attempt < 2:
            time.sleep(3)
    raise RuntimeError("Pollinations: all 3 attempts failed")


def _fetch_picsum(topic: str) -> bytes:
    """
    Picsum Fallback — guaranteed photo (not AI-generated but always works).
    Returns a random high-res photo.
    """
    url = f"https://picsum.photos/1024/768?random={random.randint(1, 1000)}"
    logger.info(f"Picsum fallback: {url}")
    resp = requests.get(url, timeout=30, allow_redirects=True)
    if resp.status_code == 200 and _is_valid_image(resp.content):
        logger.info(f"✅ Picsum photo → {len(resp.content)} bytes")
        return resp.content
    raise RuntimeError(f"Picsum failed: HTTP {resp.status_code}")


class ImageAgent:
    """Generate images. Order: HuggingFace → Pollinations → Picsum photo."""

    def _build_prompt(self, topic: str, style: str, custom_prompt: str) -> str:
        style_desc = IMAGE_STYLES.get(style, IMAGE_STYLES["entrepreneurial"])
        if custom_prompt:
            return f"{custom_prompt}, {style_desc}"
        return f"stunning social media image for '{topic}', {style_desc}, premium quality"

    async def generate(
        self,
        topic: str,
        style: str = "entrepreneurial",
        custom_prompt: str = "",
    ) -> tuple[bytes, str]:
        """Returns (image_bytes, prompt_used). Tries 3 sources until one works."""
        loop   = asyncio.get_event_loop()
        prompt = self._build_prompt(topic, style, custom_prompt)

        # 1️⃣  HuggingFace (FLUX.1-schnell / SDXL / SD1.5)
        try:
            data = await loop.run_in_executor(None, _fetch_huggingface, prompt)
            return data, prompt
        except Exception as e:
            logger.warning(f"HuggingFace failed: {e}")

        # 2️⃣  Pollinations.ai
        try:
            data = await loop.run_in_executor(None, _fetch_pollinations, prompt)
            return data, prompt
        except Exception as e:
            logger.warning(f"Pollinations failed: {e}")

        # 3️⃣  Picsum (real photo — always works)
        try:
            data = await loop.run_in_executor(None, lambda: _fetch_picsum(topic))
            return data, f"picsum:{topic}"
        except Exception as e:
            logger.error(f"Picsum also failed: {e}")

        raise RuntimeError(
            "Image generation unavailable right now (HuggingFace loading, Pollinations down). "
            "Post will continue without image."
        )

    def get_style_menu(self) -> dict[str, str]:
        return {
            "entrepreneurial": "🔥 Bold Entrepreneur",
            "tech_minimal":    "⚡ Tech Minimal",
            "creative_dark":   "🌌 Creative Dark",
        }

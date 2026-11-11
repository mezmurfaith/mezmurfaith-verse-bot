"""Makes the charcoal illustration, either with OpenAI or (for testing) a simple placeholder drawing.

The image model is told never to draw text. All words on the poster are added by render.py.
"""
import base64
import io
import logging
import math
import os
import random
import re

from PIL import Image, ImageDraw, ImageFilter, ImageStat

log = logging.getLogger("illustrate")

# Newest models per OpenAI's docs (checked Nov 2026). Falls back if the first isn't available.
MODELS = ["gpt-image-2.6-sunburst", "gpt-image-2.5-sunburst"]
SIZE = "1536x1024"  # landscape: fills the lower part of the poster

STYLE = (
    "Hand-drawn charcoal and graphite pencil illustration on warm cream textured paper. "
    "Black, charcoal and soft gray tones only. Traditional Christian art print. "
    "It must look like a real hand drawing: visible pencil strokes, cross-hatching and smudged charcoal shading, "
    "not glossy, not digital, not a painting, not a photo. "
    "The subject sits in the lower two thirds; leave the top third as plain empty paper. "
    "Strictly monochrome: no yellow, gold, blue, red, or any other colour. "
    "Absolutely NO text, letters, words, numbers, signatures, symbols, logos or watermarks anywhere."
)


class IllustrationError(Exception):
    pass


def build_prompt(scene: str) -> str:
    return f"Scene: {scene}.\n\nStyle: {STYLE}"


def quality_problems(img: Image.Image) -> list[str]:
    """Cheap automatic checks so a broken image is never posted."""
    out = []
    if img.width < 1000 or img.height < 600:
        out.append(f"image too small ({img.width}x{img.height})")
    g = img.convert("L")
    st = ImageStat.Stat(g)
    if st.stddev[0] < 12:
        out.append("image is almost blank / one flat tone")
    if st.mean[0] < 70:
        out.append("image is far too dark")
    # how much drawing is in the lower half (should have a subject there)
    lower = g.crop((0, g.height // 2, g.width, g.height))
    if ImageStat.Stat(lower).stddev[0] < 10:
        out.append("no visible drawing in the lower half")
    return out


HINTS = {
    "insufficient_quota": "Your OpenAI account has no credit left. Add credit at platform.openai.com → Settings → Billing.",
    "billing_hard_limit_reached": "Your OpenAI monthly spending limit was reached. Raise it at platform.openai.com → Settings → Limits.",
    "invalid_api_key": "The OPENAI_API_KEY secret is wrong. Create a new key and update the secret on GitHub.",
}


def describe(e: Exception) -> str:
    """Readable reason from an OpenAI error (never includes the key)."""
    code = getattr(e, "code", None)
    status = getattr(e, "status_code", None)
    msg = ""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        msg = body.get("message") or (body.get("error") or {}).get("message", "")
    msg = re.sub(r"sk-[A-Za-z0-9_*-]+", "sk-***", str(msg))[:300]
    text = f"{type(e).__name__} (HTTP {status}, code={code}): {msg}".strip()
    if code in HINTS:
        return f"{text}\n→ {HINTS[code]}"
    if "Limit 0" in msg:
        return (f"{text}\n→ Your OpenAI account isn't allowed to make images yet (free tier). "
                "Add credit at platform.openai.com → Settings → Billing; it unlocks within a few minutes. "
                "If it still fails, verify your organization under Settings → Organization → General.")
    return text


def generate_openai(scene: str) -> Image.Image:
    from openai import OpenAI, NotFoundError, BadRequestError, PermissionDeniedError

    if not os.environ.get("OPENAI_API_KEY"):
        raise IllustrationError("OPENAI_API_KEY is not set")
    client = OpenAI()
    prompt = build_prompt(scene)
    last_err = None
    for model in MODELS:
        try:
            res = client.images.generate(model=model, prompt=prompt, size=SIZE, quality="high", output_format="png", n=1)
            data = base64.b64decode(res.data[0].b64_json)
            log.info("Illustration made with %s", model)
            return Image.open(io.BytesIO(data)).convert("RGB")
        except (NotFoundError, BadRequestError, PermissionDeniedError) as e:  # model not available → try next
            last_err = e
            log.warning("Model %s not usable: %s", model, describe(e))
        except Exception as e:
            if getattr(e, "code", None) in HINTS:  # account problem: retrying won't help
                raise IllustrationError(describe(e)) from None
            raise
    raise IllustrationError(f"No image model worked: {describe(last_err) if last_err else 'unknown'}")


def get_illustration(scene: str, placeholder: bool = False, attempts: int = 2) -> Image.Image:
    """Try, check, retry once. Raise IllustrationError if still bad (caller skips the day)."""
    if placeholder:
        return placeholder_drawing(seed=len(scene))
    problems = []
    for i in range(attempts):
        try:
            img = generate_openai(scene)
        except IllustrationError:
            raise
        except Exception as e:  # network / API hiccup
            problems = [f"API error: {describe(e)}"]
            log.warning("Attempt %d failed: %s", i + 1, problems[0])
            continue
        problems = quality_problems(img)
        if not problems:
            return img
        log.warning("Attempt %d rejected: %s", i + 1, "; ".join(problems))
    raise IllustrationError("Illustration failed after retry: " + "; ".join(problems))


# ---------------- placeholder (for testing without an API key) ----------------

def _stroke(d, pts, shade, width=1):
    d.line(pts, fill=shade, width=width)


def placeholder_drawing(seed: int = 1, w: int = 1536, h: int = 1024) -> Image.Image:
    """A rough pencil-style hillside with a shepherd and sheep. Only a stand-in for the AI image."""
    rnd = random.Random(seed)
    s = 2
    W, H = w * s, h * s
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)

    def ridge(x, base, amp, freq, phase):
        return base + amp * math.sin(x / W * math.pi * freq + phase) + 0.3 * amp * math.sin(x / W * 9 + phase * 2)

    # three hill layers, back to front, shaded with hatching
    layers = [(0.50, 60, 1.6, 0.4, 205, 0.55), (0.62, 80, 1.2, 2.0, 170, 0.75), (0.80, 50, 2.1, 1.0, 120, 1.0)]
    for base, amp, freq, ph, shade, density in layers:
        b = base * H
        for x in range(0, W, max(2, int(9 / density))):
            top = ridge(x, b, amp * s, freq, ph)
            length = rnd.uniform(0.25, 0.9) * (H - top)
            ang = rnd.uniform(-0.25, -0.1)
            x2 = x + length * math.sin(ang)
            _stroke(d, [(x, top + rnd.uniform(0, 6)), (x2, top + length)], shade + rnd.randint(-20, 20), width=s)
        pts = [(x, ridge(x, b, amp * s, freq, ph)) for x in range(0, W + 1, 8)]
        d.line(pts, fill=max(0, shade - 90), width=2 * s)

    # shepherd on the middle hill
    sx, gy = int(W * 0.30), int(ridge(W * 0.30, 0.62 * H, 80 * s, 1.2, 2.0))
    body_h = 300 * s
    d.polygon([(sx - 55 * s, gy), (sx + 55 * s, gy), (sx + 25 * s, gy - body_h), (sx - 25 * s, gy - body_h)], fill=70)
    for _ in range(400):  # cloth hatching
        yy = rnd.uniform(gy - body_h, gy)
        xx = sx + rnd.uniform(-45, 45) * s * (yy - (gy - body_h)) / body_h
        _stroke(d, [(xx, yy), (xx + rnd.uniform(-8, 8) * s, yy + 30 * s)], rnd.randint(20, 90), width=s)
    d.ellipse([sx - 26 * s, gy - body_h - 58 * s, sx + 26 * s, gy - body_h], fill=60)
    staff_x = sx + 75 * s
    d.line([(staff_x, gy + 10 * s), (staff_x, gy - body_h - 70 * s)], fill=35, width=5 * s)
    d.arc([staff_x - 50 * s, gy - body_h - 120 * s, staff_x, gy - body_h - 30 * s], 180, 360, fill=35, width=5 * s)

    # sheep scattered on the front hill
    for _ in range(9):
        x = rnd.uniform(0.45, 0.95) * W
        y = ridge(x, 0.80 * H, 50 * s, 2.1, 1.0) + rnd.uniform(10, 120) * s
        r = rnd.uniform(38, 55) * s
        for _ in range(26):
            a = rnd.uniform(0, math.tau)
            cx, cy = x + math.cos(a) * r * 0.7, y + math.sin(a) * r * 0.35
            d.ellipse([cx - r * 0.35, cy - r * 0.3, cx + r * 0.35, cy + r * 0.3], outline=rnd.randint(60, 120), width=s)
        d.ellipse([x + r * 0.7, y - r * 0.35, x + r * 1.1, y + r * 0.05], fill=55)
        d.line([(x - r * 0.4, y + r * 0.3), (x - r * 0.4, y + r * 0.75)], fill=50, width=3 * s)
        d.line([(x + r * 0.4, y + r * 0.3), (x + r * 0.4, y + r * 0.75)], fill=50, width=3 * s)

    im = im.filter(ImageFilter.GaussianBlur(1.2)).resize((w, h), Image.LANCZOS)
    grain = Image.effect_noise((w, h), 18)
    im = Image.blend(im, grain, 0.08)
    return im.convert("RGB")

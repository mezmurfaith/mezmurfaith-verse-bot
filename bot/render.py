"""Builds the 1080x1350 poster: paper, logo, verses, references and illustration.

All text is drawn here with real font files. The image model never draws text.
"""
import pathlib
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
LOGO = ROOT / "assets" / "logo.png"

W, H = 1080, 1350
PAPER = (244, 238, 226)        # warm cream
INK = (0x1F, 0x1E, 0x1C)       # #1F1E1C near-black (Tigrinya verse, logo)
CHARCOAL = (0x3B, 0x39, 0x35)  # #3B3935 charcoal gray (English verse, wordmark)
GRAY = (0x4A, 0x47, 0x44)      # #4A4744 gray (references)
RULE = (150, 144, 136)

SIDE_MARGIN = 110
MAX_TEXT_W = W - 2 * SIDE_MARGIN
HEADER_TOP = 58
ILLUS_TOP = 650                # illustration starts here (fully faded at this line)
FADE = 250                     # height of the soft fade from paper into drawing
TEXT_LIMIT = ILLUS_TOP + 20    # text must end above this line
MIN_SCALE = 0.62               # never shrink text below 62% of normal size

# Tigrinya is the main text and must always be larger than the English.
# Everything shrinks by the same factor, so this ratio holds at every size.
BASE = {"tig": 56, "tig_ref": 28, "eng": 38, "eng_ref": 25}
assert BASE["tig"] > BASE["eng"]


class VerseTooLong(Exception):
    pass


def _font(name: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size, layout_engine=ImageFont.Layout.RAQM)
    axes = f.get_variation_axes()
    f.set_variation_by_axes([weight if a["name"] == b"Weight" else a["default"] for a in axes])
    return f


def fonts(scale: float = 1.0) -> dict:
    s = lambda k: max(12, round(BASE[k] * scale))
    return {
        "tig": _font("NotoSerifEthiopic.ttf", s("tig"), 500),          # medium weight
        "tig_ref": _font("NotoSerifEthiopic.ttf", s("tig_ref"), 400),
        "eng": _font("EBGaramond-Italic.ttf", s("eng"), 400),
        "eng_ref": _font("EBGaramond-Italic.ttf", s("eng_ref"), 400),
        "wordmark": _font("EBGaramond.ttf", 25, 500),
    }


# ---------- text wrapping ----------

def _wrap_greedy(words, font, max_w):
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


BREAK_AFTER = ("፣", "፤", "፥", "፡", ";", ",", ":")  # natural places to end a line


def wrap(text: str, font, max_w: int) -> list[str]:
    """Word-wrap, then balance line lengths so there's no lonely last word.
    Only line breaks change — the words themselves are never altered."""
    words = text.split()
    lines = _wrap_greedy(words, font, max_w)
    if len(lines) <= 1:
        return lines
    if len(lines) == 2:
        # prefer breaking after a comma/semicolon if both halves fit and look balanced
        best_pb, best_diff = None, None
        for i in range(1, len(words)):
            if words[i - 1].endswith(BREAK_AFTER):
                a, b = " ".join(words[:i]), " ".join(words[i:])
                la, lb = font.getlength(a), font.getlength(b)
                if la <= max_w and lb <= max_w and min(la, lb) >= 0.45 * max(la, lb):
                    diff = abs(la - lb)
                    if best_diff is None or diff < best_diff:
                        best_pb, best_diff = [a, b], diff
        if best_pb:
            return best_pb
    lo, hi = max_w * 0.4, max_w
    best = lines
    for _ in range(14):
        mid = (lo + hi) / 2
        trial = _wrap_greedy(words, font, mid)
        if len(trial) == len(lines) and all(font.getlength(l) <= mid for l in trial):
            best, hi = trial, mid
        else:
            lo = mid
    return best


# ---------- layout ----------

def layout(verse: dict, scale: float):
    f = fonts(scale)
    tig_lines = wrap(verse["tigrinya_text"], f["tig"], MAX_TEXT_W)
    eng_lines = wrap(verse["english_text"], f["eng"], MAX_TEXT_W)
    tig_lh = f["tig"].size * 1.55
    eng_lh = f["eng"].size * 1.3
    items = []  # (kind, text, font, line_height, gap_after)
    # 1. Tigrinya verse (main text)
    for l in tig_lines:
        items.append(("tig", l, f["tig"], tig_lh, 0))
    items[-1] = items[-1][:4] + (f["tig"].size * 0.3,)
    # 2. Tigrinya reference with rules
    items.append(("tig_ref", verse["tigrinya_ref"], f["tig_ref"], f["tig_ref"].size * 1.6, f["eng"].size * 1.0))
    # 3. English verse (smaller)
    for l in eng_lines:
        items.append(("eng", l, f["eng"], eng_lh, 0))
    items[-1] = items[-1][:4] + (f["eng"].size * 0.3,)
    # 4. English reference
    items.append(("eng_ref", verse["english_ref"], f["eng_ref"], f["eng_ref"].size * 1.5, 0))
    total = sum(it[3] + it[4] for it in items)
    return items, total


def fit(verse: dict, top: int):
    """Largest text size that fits between the header and the illustration."""
    avail = TEXT_LIMIT - top
    step = 0
    while (scale := round(1.0 - 0.02 * step, 2)) >= MIN_SCALE:
        items, total = layout(verse, scale)
        widest = max(it[2].getlength(it[1]) for it in items)
        if total <= avail and widest <= MAX_TEXT_W:
            return items, total, scale
        step += 1
    raise VerseTooLong(
        f"Verse {verse.get('id')} is too long to fit even at the smallest readable size."
    )


# ---------- drawing pieces ----------

def paper(seed: int) -> Image.Image:
    random.seed(seed)
    fine = Image.effect_noise((W, H), 22).filter(ImageFilter.GaussianBlur(0.6))
    coarse = Image.effect_noise((W // 8, H // 8), 30).resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    tex = ImageChops.blend(fine, coarse, 0.5)
    tex = ImageOps.colorize(tex, black=(226, 218, 203), white=(255, 251, 242))
    base = Image.new("RGB", (W, H), PAPER)
    img = Image.blend(base, tex, 0.32)
    # gentle vignette so the edges feel like an art print
    vign = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vign).rounded_rectangle([40, 40, W - 40, H - 40], radius=120, fill=255)
    vign = vign.filter(ImageFilter.GaussianBlur(120))
    darker = ImageChops.multiply(img, Image.new("RGB", (W, H), (236, 230, 220)))
    return Image.composite(img, darker, vign)


def draw_rules(d, cx, cy, half_text_w, length, gap=20, color=RULE):
    y = round(cy)
    d.line([(cx - half_text_w - gap - length, y), (cx - half_text_w - gap, y)], fill=color, width=1)
    d.line([(cx + half_text_w + gap, y), (cx + half_text_w + gap + length, y)], fill=color, width=1)


def draw_tracked(d, cx, cy, text, font, fill, tracking):
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        d.text((x, cy), c, font=font, fill=fill, anchor="lm")
        x += w + tracking
    return total


def placeholder_logo(size=72) -> Image.Image:
    """Simple stand-in until assets/logo.png is added: Orthodox cross + music note."""
    s = 4  # draw big, shrink for smooth edges
    im = Image.new("LA", (size * s, size * s), (0, 0))
    d = ImageDraw.Draw(im)
    c = INK[0]
    w = 5 * s
    cx = size * s * 0.42
    top, bot = 6 * s, size * s - 6 * s
    d.line([(cx, top), (cx, bot)], fill=(c, 255), width=w)
    d.line([(cx - 9 * s, top + 9 * s), (cx + 9 * s, top + 9 * s)], fill=(c, 255), width=w - s)
    d.line([(cx - 17 * s, top + 22 * s), (cx + 17 * s, top + 22 * s)], fill=(c, 255), width=w)
    d.line([(cx - 10 * s, bot - 18 * s), (cx + 10 * s, bot - 10 * s)], fill=(c, 255), width=w - s)
    nx, ny = size * s * 0.78, size * s * 0.55
    d.line([(nx, ny - 26 * s), (nx, ny + 10 * s)], fill=(c, 255), width=3 * s)
    d.line([(nx, ny - 26 * s), (nx + 9 * s, ny - 18 * s)], fill=(c, 255), width=3 * s)
    d.ellipse([nx - 10 * s, ny + 4 * s, nx + 2 * s, ny + 13 * s], fill=(c, 255))
    return im.resize((size, size), Image.LANCZOS).convert("RGBA")


def load_logo(height=118) -> Image.Image:
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGBA")
        # turn any colour in the logo into near-black ink, keep transparency
        alpha = lg.getchannel("A")
        gray = ImageOps.grayscale(lg)
        if alpha.getextrema() == (255, 255):  # no transparency: treat light pixels as paper
            alpha = ImageOps.invert(gray).point(lambda v: min(255, int(v * 1.6)))
        ink = Image.new("RGBA", lg.size, INK + (0,))
        ink.putalpha(alpha)
        lg = ink
    else:
        lg = placeholder_logo(height)
    ratio = height / lg.height
    return lg.resize((max(1, round(lg.width * ratio)), height), Image.LANCZOS)


def text_top() -> int:
    """Where the verse block may start (just below logo + wordmark)."""
    return HEADER_TOP + load_logo().height + 30 + 20 + 40


def check_fits(verse: dict) -> None:
    """Raise VerseTooLong before spending money on an illustration."""
    fit(verse, text_top())


def prepare_illustration(img: Image.Image) -> Image.Image:
    """Force pure charcoal tones (no colour can slip through) and fit to the lower area."""
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=(1, 0.5))
    area_h = H - ILLUS_TOP
    g = ImageOps.fit(g, (W, area_h), Image.LANCZOS, centering=(0.5, 0.65))
    # map to ink tones, white = no change when multiplied onto the paper
    return ImageOps.colorize(g, black=(38, 36, 34), mid=(140, 136, 130), white=(255, 255, 255))


def illustration_mask() -> Image.Image:
    area_h = H - ILLUS_TOP
    m = Image.new("L", (W, area_h), 255)
    px = m.load()
    for y in range(min(FADE, area_h)):
        t = y / FADE
        v = round(255 * (t * t * (3 - 2 * t)))  # smoothstep
        for x in range(W):
            px[x, y] = v
    side = Image.new("L", (W, area_h), 0)
    ImageDraw.Draw(side).rectangle([30, 0, W - 30, area_h], fill=255)
    side = side.filter(ImageFilter.GaussianBlur(28))
    return ImageChops.multiply(m, side)


# ---------- main entry ----------

def render(verse: dict, illustration: Image.Image, wordmark: str = "mezmurfaith", seed: int = 7) -> tuple[Image.Image, dict]:
    img = paper(seed)

    # illustration, multiplied onto the paper so the texture shows through
    ill = prepare_illustration(illustration)
    region = img.crop((0, ILLUS_TOP, W, H))
    inked = ImageChops.multiply(region, ill)
    img.paste(Image.composite(inked, region, illustration_mask()), (0, ILLUS_TOP))

    d = ImageDraw.Draw(img)
    cx = W / 2

    # header: logo, then wordmark between thin rules
    logo = load_logo()
    img.paste(logo, (round(cx - logo.width / 2), HEADER_TOP), logo)
    f = fonts(1.0)
    wm_y = HEADER_TOP + logo.height + 30
    wm_w = draw_tracked(d, cx, wm_y, wordmark, f["wordmark"], CHARCOAL, tracking=5)
    draw_rules(d, cx, wm_y + 1, wm_w / 2, length=46, gap=18)
    header_bottom = wm_y + 20

    # verse block, auto-shrunk to fit, centred in the space above the illustration
    top = header_bottom + 40
    items, total, scale = fit(verse, top)
    y = top + (TEXT_LIMIT - top - total) * 0.42
    colors = {"tig": INK, "tig_ref": GRAY, "eng": CHARCOAL, "eng_ref": GRAY}
    for kind, text, font, lh, gap in items:
        cy = y + lh / 2
        if kind == "tig_ref":
            d.text((cx, cy), text, font=font, fill=colors[kind], anchor="mm")
            draw_rules(d, cx, cy + 1, font.getlength(text) / 2, length=70, gap=24)
        else:
            d.text((cx, cy), text, font=font, fill=colors[kind], anchor="mm")
        y += lh + gap

    sizes = {it[0]: it[2].size for it in items}
    info = {"scale": round(scale, 2), "text_bottom": round(y), "text_limit": TEXT_LIMIT,
            "tig_size": sizes["tig"], "eng_size": sizes["eng"]}
    return img, info


def save_jpeg(img: Image.Image, path) -> None:
    img.convert("RGB").save(path, "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)

"""Removes the cream background from the logo and makes the poster version.

Usage:  .venv/bin/python scripts/make_logo.py [assets/logo-original.jpg]

Creates:
  assets/logo-transparent.png   full-colour logo, background removed (for your other uses)
  assets/logo.png               charcoal-only version used on the posters
"""
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "logo-original.jpg"

img = Image.open(src).convert("RGB")
a = np.asarray(img).astype(np.float32)
h, w, _ = a.shape

# 1. Find the smooth background: areas with almost no edges that touch the image border.
smooth = ndimage.gaussian_filter(a, sigma=(1.5, 1.5, 0))
grad = sum(np.hypot(ndimage.sobel(smooth[..., c], 0), ndimage.sobel(smooth[..., c], 1)) for c in range(3))
flat = grad < 28
labels, _ = ndimage.label(flat)
border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
bg_mask = np.isin(labels, border[border > 0])
bg_mask = ndimage.binary_erosion(bg_mask, iterations=3)

# 2. Estimate the background colour everywhere (also behind the artwork) by smooth interpolation.
m = bg_mask.astype(np.float32)
sig = 40
num = np.stack([ndimage.gaussian_filter(a[..., c] * m, sig) for c in range(3)], -1)
den = ndimage.gaussian_filter(m, sig)[..., None]
bg = num / np.maximum(den, 1e-4)
for _ in range(4):  # fill any remaining gaps with wider blurs
    hole = den[..., 0] < 0.02
    if not hole.any():
        break
    sig *= 2
    num = np.stack([ndimage.gaussian_filter(a[..., c] * m, sig) for c in range(3)], -1)
    den2 = ndimage.gaussian_filter(m, sig)[..., None]
    bg[hole] = (num / np.maximum(den2, 1e-4))[hole]

# 3. Alpha = how different each pixel is from the background behind it.
diff = np.abs(a - bg).max(axis=2)
alpha = np.clip((diff - 10) / 60, 0, 1)
alpha[bg_mask] = 0

# Remove stray specks (e.g. vignette remnants at the edges): keep only sizeable pieces.
lab, n = ndimage.label(alpha > 0.05)
sizes = ndimage.sum(np.ones_like(alpha), lab, range(1, n + 1))
keep = np.isin(lab, 1 + np.flatnonzero(sizes > 0.002 * h * w))
alpha[~keep] = 0
bg_mask |= ~keep & (alpha == 0)

# Make small enclosed areas solid (book pages, gaps inside the instruments),
# so the colour logo isn't see-through there. Large open areas stay transparent.
solid = alpha > 0.3
holes = ndimage.binary_fill_holes(solid) & ~solid
hl, hn = ndimage.label(holes)
hsizes = ndimage.sum(np.ones_like(alpha), hl, range(1, hn + 1))
small_holes = np.isin(hl, 1 + np.flatnonzero(hsizes < 0.004 * h * w))
alpha_color = alpha.copy()
alpha_color[small_holes] = 1.0

alpha = ndimage.gaussian_filter(alpha, 0.6)
alpha_color = ndimage.gaussian_filter(alpha_color, 0.6)

# Full-colour transparent version: un-mix the background from semi-transparent edges.
al = np.maximum(alpha_color[..., None], 1e-3)
fg = np.clip((a - (1 - al) * bg) / al, 0, 255)
color = np.dstack([fg, alpha_color * 255]).astype(np.uint8)
out_color = Image.fromarray(color, "RGBA")
bbox = out_color.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
out_color = out_color.crop(bbox)
out_color.save(ROOT / "assets" / "logo-transparent.png")

# Charcoal version: ink amount = how much darker than the paper behind it (keeps all detail).
lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
lum_bg = bg @ np.array([0.299, 0.587, 0.114], np.float32)
ink = np.clip(1 - lum / np.maximum(lum_bg, 1), 0, 1)
ink = np.clip(ink * 1.35, 0, 1)            # a bit stronger so it reads at small size
ink = np.maximum(ink, alpha * 0.18)        # keep faint light parts (book pages) just visible
ink[bg_mask] = 0
charcoal = np.zeros((h, w, 4), np.uint8)
charcoal[..., :3] = (0x1F, 0x1E, 0x1C)
charcoal[..., 3] = (ink * 255).astype(np.uint8)
out = Image.fromarray(charcoal, "RGBA").crop(bbox)
out.save(ROOT / "assets" / "logo.png")
print("saved", out.size, "bbox", bbox, "background share", round(float(bg_mask.mean()), 2))

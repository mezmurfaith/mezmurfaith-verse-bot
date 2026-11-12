"""Safety tests for the text on the poster.

Run with:  .venv/bin/python -m pytest
"""
import pathlib

import pytest
from fontTools.ttLib import TTFont

from bot import render, verses

FONTS = pathlib.Path(__file__).resolve().parent.parent / "fonts"
ALL = verses.load()


def _has_real_glyph(font: TTFont, ch: str) -> bool:
    """True if the font has a drawn glyph for ch (not missing, not an empty box)."""
    cmap = font.getBestCmap()
    name = cmap.get(ord(ch))
    if name is None or name == ".notdef":
        return False
    if ch.isspace():
        return True
    gs = font.getGlyphSet()
    from fontTools.pens.boundsPen import BoundsPen
    pen = BoundsPen(gs)
    gs[name].draw(pen)
    return pen.bounds is not None


@pytest.mark.parametrize("v", ALL, ids=[v.get("id", "?") for v in ALL])
def test_every_tigrinya_character_has_a_glyph(v):
    font = TTFont(FONTS / "NotoSerifEthiopic.ttf")
    text = (v.get("tigrinya_text") or "") + (v.get("tigrinya_ref") or "")
    missing = sorted({c for c in text if not _has_real_glyph(font, c)})
    assert not missing, f"{v['id']}: no glyph for {[f'U+{ord(c):04X} {c}' for c in missing]}"


@pytest.mark.parametrize("v", ALL, ids=[v.get("id", "?") for v in ALL])
def test_every_english_character_has_a_glyph(v):
    italic = TTFont(FONTS / "EBGaramond-Italic.ttf")
    regular = TTFont(FONTS / "EBGaramond.ttf")
    missing = {c for c in v["english_text"] if not _has_real_glyph(italic, c)}
    missing |= {c for c in v["english_ref"] + "mezmurfaith" if not _has_real_glyph(regular, c)}
    assert not missing, f"{v['id']}: no glyph for {missing}"


@pytest.mark.parametrize("v", ALL, ids=[v.get("id", "?") for v in ALL])
def test_text_never_overlaps_illustration(v):
    try:
        items, total, scale = render.fit(v, top=render.text_top())
    except render.VerseTooLong:
        pytest.fail(f"{v['id']} is too long for one poster — shorten it or split it")
        return
    assert scale >= render.MIN_SCALE
    widest = max(it[2].getlength(it[1]) for it in items)
    assert widest <= render.MAX_TEXT_W


def test_long_verse_shrinks_instead_of_overlapping():
    # Layout stress test only: reuses the verified starter text 3 times (never posted).
    base = ALL[0]
    long = dict(base, english_text=" ".join([base["english_text"]] * 3),
                tigrinya_text=" ".join([base["tigrinya_text"]] * 3))
    img, info = render.render(long, render.Image.new("RGB", (1536, 1024), "white"))
    assert info["scale"] < 1.0
    assert info["text_bottom"] <= info["text_limit"]


@pytest.mark.parametrize("scale", [1.0, 0.8, render.MIN_SCALE])
def test_tigrinya_always_larger_than_english(scale):
    f = render.fonts(scale)
    assert f["tig"].size > f["eng"].size


def test_long_verse_keeps_tigrinya_larger():
    base = ALL[0]
    long = dict(base, english_text=" ".join([base["english_text"]] * 3),
                tigrinya_text=" ".join([base["tigrinya_text"]] * 3))
    _, info = render.render(long, render.Image.new("RGB", (1536, 1024), "white"))
    assert info["tig_size"] > info["eng_size"]


@pytest.mark.parametrize("v", ALL, ids=[v.get("id", "?") for v in ALL])
def test_caption_tigrinya_first_and_exact(v):
    from bot.caption import build_caption
    cap = build_caption(v)
    assert cap.startswith(v["tigrinya_text"])  # copied exactly, and first
    assert cap.index(v["tigrinya_ref"]) < cap.index(v["english_text"])
    assert cap.index(v["english_ref"]) < cap.index("#")


def test_missing_tigrinya_is_skipped():
    base = dict(ALL[0], posted=False)
    good = dict(base, id="good")
    no_tig = dict(base, id="no-tig", tigrinya_text="")
    latin = dict(base, id="latin", tigrinya_text="The Lord is my shepherd")
    assert verses.next_verse([no_tig, latin, good])["id"] == "good"
    assert verses.next_verse([no_tig, latin]) is None


def test_verses_file_is_valid():
    errors, _ = verses.validate(ALL)
    assert not errors

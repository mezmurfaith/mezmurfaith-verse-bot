"""Loading, checking and picking verses from verses.json.

IMPORTANT: Tigrinya text is never created, translated or changed here.
It is read from verses.json exactly as written. If it's missing, the verse is skipped.
"""
import json
import logging
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSES_FILE = ROOT / "verses.json"

REQUIRED = ["id", "english_text", "english_ref", "tigrinya_text", "tigrinya_ref", "scene_prompt", "posted"]

# Unicode blocks for Ethiopic (Ge'ez) script.
ETHIOPIC_RANGES = [(0x1200, 0x139F), (0x2D80, 0x2DDF), (0xAB00, 0xAB2F), (0x1E7E0, 0x1E7FF)]

log = logging.getLogger("verses")


def is_ethiopic(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ETHIOPIC_RANGES)


def load(path=None) -> list[dict]:
    path = path or VERSES_FILE
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(verses: list[dict], path=None) -> None:
    path = path or VERSES_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False, indent=2)
        f.write("\n")


def problems(v: dict) -> list[str]:
    """Reasons this verse must NOT be posted (empty list = OK)."""
    out = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(v.get("id") or "")):
        out.append("'id' must use only lowercase English letters, numbers and dashes (e.g. psalm-23-1)")
    for key in REQUIRED:
        if key not in v:
            out.append(f"missing field '{key}'")
    for key in ["english_text", "english_ref", "scene_prompt"]:
        if not str(v.get(key) or "").strip():
            out.append(f"'{key}' is empty")
    for key in ["tigrinya_text", "tigrinya_ref"]:
        val = str(v.get(key) or "").strip()
        if not val:
            out.append(f"'{key}' is empty (Tigrinya must come from a verified Bible)")
        elif not any(is_ethiopic(c) for c in val):
            out.append(f"'{key}' contains no Tigrinya (Ge'ez) letters")
    ref = str(v.get("tigrinya_ref") or "")
    if ref and ":" in ref:
        out.append("'tigrinya_ref' uses ':' — use the Ethiopic separator ፥ (e.g. ዳዊት 23፥1)")
    return out


def validate(verses: list[dict]) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings) for the whole file."""
    errors, warnings = [], []
    if not isinstance(verses, list):
        return ["verses.json must be a list [ ... ] of verse entries"], []
    seen = set()
    for i, v in enumerate(verses):
        label = v.get("id") or f"entry #{i + 1}"
        if v.get("id") in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(v.get("id"))
        for p in problems(v):
            warnings.append(f"{label}: {p} — this verse will be skipped")
    return errors, warnings


def next_verse(verses: list[dict], exclude_ids=()) -> dict | None:
    """First unposted verse that passes all checks. Bad ones are skipped with a warning."""
    for v in verses:
        if v.get("posted") or v.get("id") in exclude_ids:
            continue
        p = problems(v)
        if p:
            log.warning("Skipping %s: %s", v.get("id"), "; ".join(p))
            continue
        return v
    return None


def mark_posted(verse_id: str, date_str: str, path=None) -> None:
    verses = load(path)
    for v in verses:
        if v.get("id") == verse_id:
            v["posted"] = True
            v["posted_date"] = date_str
    save(verses, path)

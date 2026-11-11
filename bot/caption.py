"""Instagram caption: Tigrinya verse + reference first, then English, then hashtags.

The Tigrinya text is copied exactly from verses.json, never changed.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"

MAX_CAPTION = 2200   # Instagram's caption limit
MAX_HASHTAGS = 30    # Instagram's hashtag limit


def load_config(path=CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_caption(verse: dict, config: dict | None = None) -> str:
    config = config or load_config()
    tags = [t if t.startswith("#") else f"#{t}" for t in config.get("hashtags", [])][:MAX_HASHTAGS]
    parts = [
        f"{verse['tigrinya_text']}\n— {verse['tigrinya_ref']}",
        f"“{verse['english_text']}”\n— {verse['english_ref']}",
    ]
    if tags:
        parts.append(" ".join(tags))
    caption = "\n\n".join(parts)
    if len(caption) > MAX_CAPTION:
        raise ValueError(f"Caption is {len(caption)} characters; Instagram allows {MAX_CAPTION}.")
    return caption

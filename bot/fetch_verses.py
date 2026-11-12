"""Fills verses.json from published Bibles online — the text is COPIED, never generated.

- Tigrinya: copied word for word from bible.club (the same Tigrinya Bible text as the
  verified starter verse, ዳዊት 23፥1). The Tigrinya book name in the reference is taken
  from the page heading, not written by us.
- English: King James Version (public domain) from bible-api.com.

Safety checks before a verse is added:
  * the Tigrinya and English chapters have the same number of verses (so verse numbers
    line up between the two Bibles),
  * the Tigrinya text contains Ge'ez letters,
  * the verse fits on a poster.
Anything that fails is skipped with a warning — never guessed.

The list of which verses to use (and the drawing idea for each) is data/verse_plan.json.
"""
import html
import json
import logging
import pathlib
import re
import time

import requests

from bot import render, verses

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAN = ROOT / "data" / "verse_plan.json"
TIG_URL = "https://www.bible.club/tigrigna/{book}/chapter-{chapter}.html"
KJV_URL = "https://bible-api.com/{query}?translation=kjv"
# Second, independent site with the same Tigrinya Bible — used only to double-check.
GEEZ_URL = "http://bibleonline.geezexperience.com/tigrinya/list.php?book={num}&chapter={chapter}"
BOOKS = ("genesis exodus leviticus numbers deuteronomy joshua judges ruth 1-samuel 2-samuel 1-kings 2-kings "
         "1-chronicles 2-chronicles ezra nehemiah esther job psalms proverbs ecclesiastes song-of-solomon isaiah "
         "jeremiah lamentations ezekiel daniel hosea joel amos obadiah jonah micah nahum habakkuk zephaniah haggai "
         "zechariah malachi matthew mark luke john acts romans 1-corinthians 2-corinthians galatians ephesians "
         "philippians colossians 1-thessalonians 2-thessalonians 1-timothy 2-timothy titus philemon hebrews james "
         "1-peter 2-peter 1-john 2-john 3-john jude revelation").split()
assert len(BOOKS) == 66 and BOOKS[18] == "psalms"


def clean_tigrinya_char(c: str) -> bool:
    """Only Ge'ez letters, Ge'ez punctuation and spaces are allowed in a verse."""
    return c == " " or verses.is_ethiopic(c)
HEADERS = {"User-Agent": "MezmurFaithVerseBot/1.0"}

log = logging.getLogger("fetch")


class FetchError(Exception):
    pass


def _get(url: str) -> requests.Response:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            raise FetchError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            if attempt == 2:
                raise FetchError(f"{type(e).__name__} for {url}") from None
            time.sleep(2)
    raise FetchError(f"Gave up on {url}")


def parse_tigrinya_chapter(page: str) -> tuple[str, dict[tuple[int, int], str]]:
    """Returns (Tigrinya book name from the page heading, {(first, last) verse: text}).

    This Tigrinya translation sometimes joins verses into one sentence, shown as "7-8";
    those come back as (7, 8). Single verses come back as (n, n)."""
    m = re.search(r'<div id="content_page"\s*>(.*?)</div>', page, re.S)
    if not m:
        raise FetchError("Tigrinya page layout not recognised")
    block = m.group(1)
    h1 = re.search(r"<h1>(.*?)</h1>", block, re.S)
    if not h1:
        raise FetchError("Tigrinya chapter heading not found")
    heading = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
    book_name = re.sub(r"\s*\d+\s*$", "", heading).strip()  # "ዳዊት 23" → "ዳዊት"
    found = {}
    for first, last, text in re.findall(r"<p>\s*(\d+)(?:\s*-\s*(\d+))?\s+(.*?)</p>", block, re.S):
        clean = " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())
        found[(int(first), int(last or first))] = clean
    if not found:
        raise FetchError("No verses found on Tigrinya page")
    return book_name, found


_CMAP = None


def has_glyph(ch: str) -> bool:
    """True if the Tigrinya font can draw this character (so no empty boxes on the poster)."""
    global _CMAP
    if _CMAP is None:
        from fontTools.ttLib import TTFont
        _CMAP = TTFont(ROOT / "fonts" / "NotoSerifEthiopic.ttf").getBestCmap()
    return ch.isspace() or ord(ch) in _CMAP


def tidy_english(text: str) -> str:
    text = " ".join(text.split())
    # KJV prints the divine name in small capitals; show it as normal words on the poster.
    return re.sub(r"\bLORD\b", "Lord", re.sub(r"\bGOD\b", "God", text))


class Fetcher:
    def __init__(self, pause: float = 1.0):
        self.pause = pause
        self._tig, self._kjv, self._geez = {}, {}, {}

    def tigrinya_chapter(self, book: str, chapter: int):
        key = (book, chapter)
        if key not in self._tig:
            url = TIG_URL.format(book=book, chapter=chapter)
            self._tig[key] = (*parse_tigrinya_chapter(_get(url).text), url)
            time.sleep(self.pause)
        return self._tig[key]

    def kjv_chapter(self, book: str, chapter: int) -> dict[int, str]:
        key = (book, chapter)
        if key not in self._kjv:
            query = f"{book.replace('-', ' ')} {chapter}"
            data = _get(KJV_URL.format(query=requests.utils.quote(query))).json()
            self._kjv[key] = {int(v["verse"]): v["text"] for v in data.get("verses", [])}
            if not self._kjv[key]:
                raise FetchError(f"No English verses for {query}")
            time.sleep(self.pause)
        return self._kjv[key]

    def second_source(self, book: str, chapter: int) -> dict[str, str]:
        """The same chapter from a second, independent Tigrinya Bible website: {"7-8": text}."""
        key = (book, chapter)
        if key not in self._geez:
            num = BOOKS.index(book) + 1
            page = _get(GEEZ_URL.format(num=num, chapter=chapter)).text
            out = {}
            for n, t in re.findall(r'<dt\s*>\s*([0-9]+(?:-[0-9]+)?)\s*</dt>\s*<dd\s*>\s*<span class="geez">(.*?)</span>',
                                   page, re.S):
                out[n] = " ".join(html.unescape(re.sub(r"<[^>]+>", "", t)).split())
            if not out:
                raise FetchError("second Tigrinya source returned no verses")
            self._geez[key] = out
            time.sleep(self.pause)
        return self._geez[key]

    def build_entry(self, item: dict) -> dict:
        book, ch, vs = item["book"], int(item["chapter"]), int(item["verse"])
        tig_book, tig_units, tig_url = self.tigrinya_chapter(book, ch)
        eng_verses = self.kjv_chapter(book, ch)
        covered = set()
        for a, b in tig_units:
            covered.update(range(a, b + 1))
        if covered != set(eng_verses):
            raise FetchError(f"verse numbering differs between the two Bibles in {item['ref'].rsplit(':', 1)[0]} "
                             f"({len(covered)} Tigrinya vs {len(eng_verses)} English verses)")
        unit = next(((a, b) for a, b in tig_units if a <= vs <= b), None)
        if unit is None:
            raise FetchError(f"verse {vs} missing")
        a, b = unit
        if b - a > 2:
            raise FetchError(f"verse {vs} is joined into a long passage ({a}-{b})")
        nums = f"{a}" if a == b else f"{a}-{b}"
        tig_text = tig_units[unit]
        odd = sorted({c for c in tig_text if not clean_tigrinya_char(c)})
        if odd:
            raise FetchError("Tigrinya text has unexpected characters " + " ".join(repr(c) for c in odd))
        other = self.second_source(book, ch).get(nums)
        if other != tig_text:
            raise FetchError("the two Tigrinya Bible websites don't agree letter for letter")
        english = " ".join(tidy_english(eng_verses[n]) for n in range(a, b + 1))
        eng_ref = f"{item['ref'].rsplit(':', 1)[0]}:{nums}"
        return {
            "id": re.sub(r"[^a-z0-9]+", "-", eng_ref.lower()).strip("-"),
            "english_text": english,
            "english_ref": eng_ref,
            "tigrinya_text": tig_text,
            "tigrinya_ref": f"{tig_book} {ch}፥{nums}",
            "scene_prompt": item["scene_prompt"],
            "posted": False,
            "posted_date": None,
            "source": {"tigrinya": tig_url,
                       "tigrinya_check": GEEZ_URL.format(num=BOOKS.index(book) + 1, chapter=ch),
                       "english": "King James Version (public domain), bible-api.com"},
        }


def import_verses(limit: int | None = None, fetcher: Fetcher | None = None) -> tuple[int, list[str]]:
    """Adds plan verses that aren't in verses.json yet. Returns (added, warnings)."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    current = verses.load()
    have = {v["id"] for v in current}
    fetcher = fetcher or Fetcher()
    added, warnings = 0, []
    for item in plan:
        if limit is not None and added >= limit:
            break
        vid = re.sub(r"[^a-z0-9]+", "-", item["ref"].lower()).strip("-")
        if vid in have or any(h.startswith(vid + "-") for h in have):
            continue
        try:
            entry = fetcher.build_entry(item)
            if entry["id"] in have:  # e.g. 7-8 already added via verse 8
                continue
            bad = verses.problems(entry)
            missing = [c for c in entry["tigrinya_text"] + entry["tigrinya_ref"] if not has_glyph(c)]
            if missing:
                bad.append("the font can't draw " + ", ".join(sorted({f"U+{ord(c):04X}" for c in missing})))
            if bad:
                raise FetchError("; ".join(bad))
            render.check_fits(entry)
        except (FetchError, render.VerseTooLong) as e:
            warnings.append(f"{item['ref']}: skipped — {e}")
            log.warning("%s: skipped — %s", item["ref"], e)
            continue
        current.append(entry)
        have.add(vid)
        added += 1
        log.info("Added %s / %s", entry["english_ref"], entry["tigrinya_ref"])
    if added:
        verses.save(current)
    return added, warnings

"""Tests for copying verses from the online Bibles (no internet needed)."""
import pytest

from bot import fetch_verses, verses

STARTER = verses.load()[0]  # the verified Psalm 23:1


def page(units: list[tuple[str, str]], heading: str = "ዳዊት 23") -> str:
    ps = "".join(f"<p>{n} {t}</p>" for n, t in units)
    return f'<div id="content_page" ><h1>{heading}</h1>{ps}<br clear=\'all\' /></div>'


def test_parser_copies_tigrinya_exactly():
    book, units = fetch_verses.parse_tigrinya_chapter(page([("1", STARTER["tigrinya_text"])]))
    assert book == "ዳዊት"
    assert units[(1, 1)] == STARTER["tigrinya_text"]


def test_parser_reads_joined_verses():
    _, units = fetch_verses.parse_tigrinya_chapter(page([("1", "ሀ"), ("2-3", "ለ"), ("4", "ሐ")]))
    assert set(units) == {(1, 1), (2, 3), (4, 4)}


class FakeFetcher(fetch_verses.Fetcher):
    def __init__(self, tig_units, eng, second=None):
        super().__init__(pause=0)
        self.t, self.e = tig_units, eng
        self.s = second if second is not None else {
            (f"{a}" if a == b else f"{a}-{b}"): t for (a, b), t in tig_units.items()}

    def tigrinya_chapter(self, book, chapter):
        return "ዳዊት", self.t, "https://example.test"

    def kjv_chapter(self, book, chapter):
        return self.e

    def second_source(self, book, chapter):
        return self.s


ITEM = {"ref": "Psalm 23:2", "book": "psalms", "chapter": 23, "verse": 2, "scene_prompt": "hills"}


def test_joined_verse_uses_both_languages_together():
    f = FakeFetcher({(1, 1): "ሀ", (2, 3): "ለ ሐ"}, {1: "One.", 2: "Two,", 3: "three."})
    e = f.build_entry(ITEM)
    assert e["english_ref"] == "Psalm 23:2-3" and e["tigrinya_ref"] == "ዳዊት 23፥2-3"
    assert e["english_text"] == "Two, three." and e["tigrinya_text"] == "ለ ሐ"


def test_mismatched_numbering_is_refused():
    f = FakeFetcher({(1, 1): "ሀ", (2, 2): "ለ"}, {1: "One.", 2: "Two.", 3: "Three."})
    with pytest.raises(fetch_verses.FetchError):
        f.build_entry(ITEM)


def test_sites_that_disagree_are_refused():
    f = FakeFetcher({(1, 1): "ሀ", (2, 2): "ለ"}, {1: "One.", 2: "Two."}, second={"1": "ሀ", "2": "ለለ"})
    with pytest.raises(fetch_verses.FetchError, match="don't agree"):
        f.build_entry(ITEM)


def test_stray_characters_are_refused_not_edited():
    f = FakeFetcher({(1, 1): "ሀ", (2, 2): "- ለ"}, {1: "One.", 2: "Two."})
    with pytest.raises(fetch_verses.FetchError, match="unexpected characters"):
        f.build_entry(ITEM)


def test_lord_in_capitals_is_tidied():
    assert fetch_verses.tidy_english("The LORD\nis my shepherd") == "The Lord is my shepherd"


def test_every_imported_verse_has_its_source():
    for v in verses.load()[1:]:
        assert "bible.club" in v["source"]["tigrinya"]

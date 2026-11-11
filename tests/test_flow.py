"""End-to-end test of the daily flow with a fake Instagram (nothing is really posted)."""
import json
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot import instagram, main, verses


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    shutil.copy(verses.VERSES_FILE, tmp_path / "verses.json")
    monkeypatch.setattr(verses, "VERSES_FILE", tmp_path / "verses.json")
    for name in ["DOCS", "POSTERS", "QUEUE", "API", "STATE", "OUTPUT"]:
        rel = getattr(main, name).relative_to(main.ROOT)
        monkeypatch.setattr(main, name, tmp_path / rel)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    from bot import notify
    monkeypatch.setattr(notify, "FLAG", tmp_path / "state" / "notified")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("IG_USER_ID", "123")
    monkeypatch.setattr(main, "load_config", lambda: {**json.load(open("config.json")), "public_base_url": "https://example.test"})
    return tmp_path


class FakeIG:
    posted = []

    def __init__(self, token, user_id, version):
        assert token == "fake-token"

    def create_image_container(self, url, caption, alt_text=None, ai_generated=False):
        FakeIG.posted.append((url, caption))
        return "c1"

    def wait_until_ready(self, cid):
        pass

    def publish(self, cid):
        return "m1"

    def permalink(self, mid):
        return "https://instagram.com/p/fake"


def test_prepare_then_publish(sandbox, monkeypatch):
    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    monkeypatch.setattr(instagram, "wait_until_public", lambda url: None)
    FakeIG.posted.clear()

    assert main.main(["prepare", "--force", "--placeholder"]) == 0
    pending = json.load(open(sandbox / "state" / "pending.json"))
    assert (sandbox / pending["image_path"]).exists()

    assert main.main(["publish"]) == 0
    url, caption = FakeIG.posted[0]
    assert url == f"https://example.test/{pending['image_path']}"
    v = verses.load()[0]
    assert caption.startswith(v["tigrinya_text"])
    assert v["posted"] is True

    today = json.load(open(sandbox / "docs" / "api" / "today.json"))
    assert today["tigrinya_text"] == v["tigrinya_text"]
    assert today["instagram_url"] == "https://instagram.com/p/fake"

    # A second run the same day must not post again.
    assert main.main(["prepare", "--force", "--placeholder"]) == 0
    assert not (sandbox / "state" / "pending.json").exists()
    assert len(FakeIG.posted) == 1


def test_dry_run_never_posts(sandbox, monkeypatch):
    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    FakeIG.posted.clear()
    assert main.main(["prepare", "--force", "--placeholder", "--dry-run"]) == 0
    assert not (sandbox / "state" / "pending.json").exists()
    assert list((sandbox / "output").glob("dry-run-*.jpg"))
    assert verses.load()[0]["posted"] is False


def test_preview_then_daily_uses_approved_poster(sandbox, monkeypatch):
    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    monkeypatch.setattr(instagram, "wait_until_public", lambda url: None)
    FakeIG.posted.clear()
    assert main.main(["preview", "--days", "1", "--placeholder"]) == 0
    queued = list((sandbox / "docs" / "queue").glob("*.json"))
    assert len(queued) == 1
    # pretend that day has arrived
    day = queued[0].stem
    fake_now = datetime.fromisoformat(day + "T07:05").replace(tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(main, "now_local", lambda cfg: fake_now)
    assert main.main(["prepare"]) == 0
    assert main.main(["publish"]) == 0
    assert len(FakeIG.posted) == 1
    assert not (sandbox / "docs" / "queue" / f"{day}.jpg").exists()


def test_before_post_time_does_nothing(sandbox, monkeypatch):
    early = datetime(2026, 11, 12, 6, 0, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(main, "now_local", lambda cfg: early)
    assert main.main(["prepare", "--placeholder"]) == 0
    assert not (sandbox / "state" / "pending.json").exists()


def test_unified_token_uses_facebook_host():
    assert instagram.Instagram("EAAxyz", "1").host == instagram.FB_HOST
    assert instagram.Instagram("IGAAxyz", "1").host == instagram.HOST


def test_token_never_in_error_text():
    err = instagram._scrub("bad token abc123 in url ?access_token=abc123", "abc123")
    assert "abc123" not in err

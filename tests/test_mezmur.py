"""Daily Finish the Mezmur Reel — tested with a fake Instagram (nothing is really posted)."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot import instagram, mezmur
from bot import notify as notify_mod

CFG = {**json.load(open("config.json")), "mezmur_paused": False}
AT_8 = datetime(2026, 11, 14, 8, 5, tzinfo=ZoneInfo("America/Chicago"))


class FakeIG:
    calls, published, fail_audio = [], [], False

    def __init__(self, token, user_id, version):
        pass

    def create_reel(self, video, caption, audio_id=None):
        if audio_id and FakeIG.fail_audio:
            raise instagram.InstagramError("audio not allowed")
        FakeIG.calls.append((video.name, caption, audio_id))
        return "c1"

    def wait_until_ready(self, cid, timeout=300):
        pass

    def publish(self, cid):
        FakeIG.published.append(cid)
        return "m1"

    def permalink(self, mid):
        return "https://instagram.com/reel/fake"


@pytest.fixture
def box(tmp_path, monkeypatch):
    q = tmp_path / "queue"
    q.mkdir()
    for n in ("04", "05", "08"):
        (q / f"{n}.mp4").write_bytes(b"video")
    monkeypatch.setattr(mezmur, "QUEUE", q)
    monkeypatch.setattr(mezmur, "POSTED", tmp_path / "posted")
    monkeypatch.setattr(mezmur, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(notify_mod, "FLAG", tmp_path / "notified")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    FakeIG.calls, FakeIG.published, FakeIG.fail_audio = [], [], False
    return tmp_path


def test_posts_next_video_with_saved_song_and_removes_it(box):
    assert mezmur.run(CFG, now=AT_8) == 0
    name, caption, audio = FakeIG.calls[0]
    assert name == "04.mp4" and audio == CFG["mezmur_audio_id"]
    assert caption.startswith("How well do you know this mezmur?")
    assert not (box / "queue" / "04.mp4").exists() and (box / "posted" / "04.mp4").exists()
    assert json.loads((box / "history.json").read_text())[0]["video"] == "04.mp4"


def test_only_once_per_day(box):
    mezmur.run(CFG, now=AT_8)
    mezmur.run(CFG, now=AT_8)
    assert len(FakeIG.published) == 1


def test_waits_until_8am(box):
    assert mezmur.run(CFG, now=AT_8.replace(hour=7, minute=30)) == 0
    assert not FakeIG.calls


def test_next_day_posts_the_next_video(box):
    mezmur.run(CFG, now=AT_8)
    mezmur.run(CFG, now=AT_8.replace(day=15))
    assert [c[0] for c in FakeIG.calls] == ["04.mp4", "05.mp4"]


def test_safe_test_does_not_publish_or_remove(box):
    assert mezmur.run(CFG, test=True, now=AT_8) == 0
    assert FakeIG.calls and not FakeIG.published
    assert (box / "queue" / "04.mp4").exists()


def test_falls_back_to_own_sound_if_song_rejected(box):
    FakeIG.fail_audio = True
    assert mezmur.run(CFG, now=AT_8) == 0
    assert FakeIG.calls[0][2] is None and len(FakeIG.published) == 1


def test_all_waiting_videos_are_reel_files():
    vids = mezmur.waiting()
    assert vids, "mezmur_reels/queue is empty"
    assert all(v.stat().st_size > 100_000 for v in vids)

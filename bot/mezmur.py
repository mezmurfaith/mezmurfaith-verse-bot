"""Daily "Finish the Mezmur" Reel.

Each day at 8:00 AM Chicago time, the next video in mezmur_reels/queue/ is posted to
Instagram as a Reel with the "Finish the Mezmur" caption. Instagram adds the saved mezmur
song (config "mezmur_audio_id") and the video's own sound is turned down. After posting,
the video is moved to mezmur_reels/posted/ so it is never posted twice.

Instagram only. The verse post (7:00 AM) is separate and stays a picture.
"""
import json
import logging
import os
import pathlib
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.notify import notify

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "mezmur_reels"
QUEUE = BASE / "queue"
POSTED = BASE / "posted"
HISTORY = BASE / "history.json"

log = logging.getLogger("mezmur")


def history() -> list:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def waiting() -> list[pathlib.Path]:
    return sorted(QUEUE.glob("*.mp4"))


def run(cfg: dict, force: bool = False, dry_run: bool = False, test: bool = False, now: datetime | None = None) -> int:
    from bot.instagram import Instagram, InstagramError

    now = now or datetime.now(ZoneInfo(cfg["timezone"]))
    today = now.date().isoformat()
    if cfg.get("mezmur_paused") and not (dry_run or test):
        log.info("Mezmur posts are paused (\"mezmur_paused\": true).")
        return 0
    if not (force or test) and now.strftime("%H:%M") < cfg.get("mezmur_post_time", "08:00"):
        log.info("Before %s in %s — nothing to do yet.", cfg.get("mezmur_post_time"), cfg["timezone"])
        return 0
    if not test and any(h["date"] == today for h in history()):
        log.info("Mezmur already posted today (%s).", today)
        return 0
    videos = waiting()
    if not videos:
        notify("Out of Finish the Mezmur videos",
               "All videos in mezmur_reels/queue have been posted. Ask Claude to add the next batch.")
        return 0
    video = videos[0]
    log.info("Next mezmur video: %s (%d waiting)", video.name, len(videos))
    if dry_run:
        print(f"Would post {video.name} with caption:\n{cfg['mezmur_caption']}")
        return 0

    try:
        ig = Instagram(os.environ.get("IG_ACCESS_TOKEN", "").strip(), os.environ.get("IG_USER_ID", "").strip(),
                       cfg["instagram_api_version"])
        audio_id, used_audio = cfg.get("mezmur_audio_id"), True
        try:
            cid = ig.create_reel(video, cfg["mezmur_caption"], audio_id=audio_id)
            ig.wait_until_ready(cid, timeout=600)
        except InstagramError as e:
            if not audio_id:
                raise
            # Never miss a day: post the video with its own sound instead.
            log.warning("Saved song could not be attached (%s); posting with the video's own sound.", e)
            used_audio = False
            cid = ig.create_reel(video, cfg["mezmur_caption"])
            ig.wait_until_ready(cid, timeout=600)
            if not test:
                notify(f"Mezmur Reel posted without the saved song on {today}",
                       f"{e}\n\nThe video was posted with its own sound instead.")
        if test:
            print(f"Safe test OK: Instagram accepted {video.name}"
                  f"{' with the saved song' if used_audio else ' (own sound only)'}. NOT published.")
            return 0
        media_id = ig.publish(cid)
        link = ig.permalink(media_id)
    except InstagramError as e:
        notify(f"Finish the Mezmur post failed on {today}", f"{e}\n\nThe video {video.name} stays in the queue for tomorrow.")
        return 1

    POSTED.mkdir(parents=True, exist_ok=True)
    shutil.move(str(video), POSTED / video.name)
    record = {"date": today, "video": video.name, "instagram_url": link,
              "audio_id": audio_id if used_audio else None}
    HISTORY.write_text(json.dumps([record] + history(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("Posted %s: %s", video.name, link or media_id)
    return 0

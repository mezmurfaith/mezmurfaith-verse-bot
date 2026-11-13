"""MezmurFaith daily verse bot — command line.

  python -m bot.main validate                 check verses.json
  python -m bot.main render --placeholder     make a test poster in output/ (no API key needed)
  python -m bot.main prepare [--dry-run]      daily step 1: pick verse, make poster
  python -m bot.main publish                  daily step 2: post the prepared poster to Instagram
  python -m bot.main preview --days 7         make the next 7 posters for your approval
  python -m bot.main check-instagram          test the Instagram connection (token + user id)
  python -m bot.main refresh-token --out F    get a fresh Instagram token, write it to file F
"""
import argparse
import json
import logging
import os
import pathlib
import shutil
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot import illustrate, render, verses
from bot.caption import build_caption, load_config
from bot.notify import notify

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
POSTERS = DOCS / "posters"        # every posted image (public, used by Instagram + your app)
QUEUE = DOCS / "queue"            # pre-made posters waiting for their day (review mode)
API = DOCS / "api"                # today.json + history.json for your app
STATE = ROOT / "state"            # temporary hand-off between steps (not committed)
OUTPUT = ROOT / "output"          # local test posters (not committed)

log = logging.getLogger("bot")


# ---------- helpers ----------

def now_local(cfg) -> datetime:
    return datetime.now(ZoneInfo(cfg["timezone"]))


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def set_output(name: str, value: str):
    """Pass a value to the next GitHub Actions step."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{name}={value}\n")


def public_base_url(cfg) -> str:
    if cfg.get("public_base_url"):
        return cfg["public_base_url"].rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("Set public_base_url in config.json (or run inside GitHub Actions).")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}"


def history() -> list:
    return read_json(API / "history.json", [])


def queued_entries() -> dict:
    return {p.stem: read_json(p, {}) for p in sorted(QUEUE.glob("*.json"))}


def same_verse(a: dict, b: dict) -> bool:
    keys = ["english_text", "english_ref", "tigrinya_text", "tigrinya_ref"]
    return all(a.get(k) == b.get(k) for k in keys)


def pick_and_draw(all_verses, exclude, placeholder):
    """Next postable verse that fits on a poster + its illustration. Raises on failure."""
    skipped = set(exclude)
    while True:
        v = verses.next_verse(all_verses, exclude_ids=skipped)
        if v is None:
            return None, None
        try:
            render.check_fits(v)
        except render.VerseTooLong as e:
            notify(f"Verse {v['id']} is too long for a poster", f"{e}\nIt was skipped. Shorten it or split it in verses.json.")
            skipped.add(v["id"])
            continue
        return v, illustrate.get_illustration(v["scene_prompt"], placeholder=placeholder)


def make_poster(v, illustration, path, cfg):
    img, info = render.render(v, illustration, wordmark=cfg.get("brand_wordmark", "mezmurfaith"))
    path.parent.mkdir(parents=True, exist_ok=True)
    render.save_jpeg(img, path)
    log.info("Poster saved: %s (%s)", path.relative_to(ROOT), info)


# ---------- commands ----------

def cmd_validate(args):
    vs = verses.load()
    errors, warnings = verses.validate(vs)
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:", e)
    left = sum(1 for v in vs if not v.get("posted") and not verses.problems(v))
    print(f"{len(vs)} verses, {left} ready to post." + (" All good!" if not errors and not warnings else ""))
    return 1 if errors else 0


def cmd_render(args):
    cfg = load_config()
    vs = verses.load()
    v = next((x for x in vs if x["id"] == args.verse), None) if args.verse else verses.next_verse(vs)
    if not v:
        print("No verse found.")
        return 1
    ill = illustrate.get_illustration(v["scene_prompt"], placeholder=args.placeholder)
    path = OUTPUT / f"poster-{v['id']}.jpg"
    make_poster(v, ill, path, cfg)
    print(build_caption(v, cfg))
    print(f"\nSaved {path}")
    return 0


def cmd_prepare(args):
    cfg = load_config()
    now = now_local(cfg)
    today = now.date().isoformat()
    set_output("ready", "false")

    if cfg.get("paused") and not args.dry_run:
        log.info("Posting is paused (\"paused\": true in config.json). Test runs still work.")
        return 0

    if not args.force and now.strftime("%H:%M") < cfg["post_time"]:
        log.info("It's %s in %s — before %s, nothing to do yet.", now.strftime("%H:%M"), cfg["timezone"], cfg["post_time"])
        return 0
    if any(h["date"] == today for h in history()):
        log.info("Already posted today (%s).", today)
        return 0

    all_verses = verses.load()
    queue = queued_entries()
    v, image_src = None, None

    # 1. An approved poster made in advance for today?
    q = queue.get(today)
    if q:
        match = next((x for x in all_verses if x["id"] == q.get("verse_id")), None)
        if match and not match.get("posted") and not verses.problems(match) and same_verse(match, q):
            v, image_src = match, QUEUE / f"{today}.jpg"
            log.info("Using approved poster for %s: %s", today, v["id"])
        else:
            log.warning("Queued poster for %s no longer matches verses.json — making a fresh one.", today)

    # 2. Today's poster already made by an earlier run that failed to post?
    if not v:
        for p in sorted(POSTERS.glob(f"{today}-*.jpg")):
            vid = p.stem[len(today) + 1:]
            match = next((x for x in all_verses if x["id"] == vid and not x.get("posted")), None)
            if match and not verses.problems(match):
                v, image_src = match, p
                log.info("Reusing today's poster from an earlier attempt: %s", p.name)
                break

    # 3. Otherwise make a fresh one (unless you want to approve everything first).
    if not v:
        if cfg.get("require_approval") and not args.dry_run:
            notify(f"No approved poster for {today}",
                   "Approval is required (require_approval = true) and nothing was approved for today, so nothing was posted. "
                   "Run the 'Preview week' workflow and merge its pull request.")
            return 0
        future = {e.get("verse_id") for d, e in queue.items() if d > today}
        try:
            v, ill = pick_and_draw(all_verses, future, args.placeholder)
        except illustrate.IllustrationError as e:
            notify(f"No post on {today}: illustration failed", f"{e}\n\nNothing was posted today. It will try again tomorrow.")
            return 1
        if v is None:
            notify("Out of verses", "Every verse in verses.json has been posted (or skipped). Add more verses to keep posting.")
            return 0
        if args.dry_run:
            path = OUTPUT / f"dry-run-{today}-{v['id']}.jpg"
            make_poster(v, ill, path, cfg)
            print(build_caption(v, cfg))
            return 0
        image_src = POSTERS / f"{today}-{v['id']}.jpg"
        make_poster(v, ill, image_src, cfg)

    if args.dry_run:
        dest = OUTPUT / f"dry-run-{today}-{v['id']}.jpg"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(image_src, dest)
        print(build_caption(v, cfg))
        return 0

    poster = POSTERS / f"{today}-{v['id']}.jpg"
    if image_src != poster:
        poster.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(image_src, poster)
    write_json(STATE / "pending.json", {
        "date": today, "verse_id": v["id"],
        "image_path": str(poster.relative_to(ROOT)),
        "caption": build_caption(v, cfg),
    })
    set_output("ready", "true")
    return 0


def cmd_publish(args):
    from bot.instagram import Instagram, InstagramError, wait_until_public

    cfg = load_config()
    pending = read_json(STATE / "pending.json", None)
    if not pending:
        log.info("Nothing prepared to publish.")
        return 0
    if any(h["date"] == pending["date"] for h in history()):
        log.info("Already posted for %s.", pending["date"])
        return 0
    v = next(x for x in verses.load() if x["id"] == pending["verse_id"])
    url = f"{public_base_url(cfg)}/{pending['image_path']}"
    try:
        wait_until_public(url)
        ig = Instagram(os.environ.get("IG_ACCESS_TOKEN", ""), os.environ.get("IG_USER_ID", ""), cfg["instagram_api_version"])
        cid = ig.create_image_container(
            url, pending["caption"],
            alt_text=f"{v['english_text']} — {v['english_ref']}. Charcoal drawing: {v['scene_prompt']}.",
            ai_generated=cfg.get("label_ai_generated", False),
        )
        ig.wait_until_ready(cid)
        media_id = ig.publish(cid)
    except InstagramError as e:
        notify(f"Instagram post failed on {pending['date']}", f"{e}\n\nThe poster is saved in `{pending['image_path']}`. "
               "If the token expired, follow 'Get a new Instagram token' in the README.")
        return 1
    link = ig.permalink(media_id)
    log.info("Posted! %s", link or media_id)

    # Record it: verses.json, history + today for your app, and clear the queue entry.
    verses.mark_posted(v["id"], pending["date"])
    record = {
        "date": pending["date"], "id": v["id"],
        "english_text": v["english_text"], "english_ref": v["english_ref"],
        "tigrinya_text": v["tigrinya_text"], "tigrinya_ref": v["tigrinya_ref"],
        "image_url": url, "instagram_url": link,
    }
    write_json(API / "history.json", [record] + history())
    write_json(API / "today.json", record)
    for ext in ("jpg", "json"):
        (QUEUE / f"{pending['date']}.{ext}").unlink(missing_ok=True)
    (STATE / "pending.json").unlink(missing_ok=True)
    return 0


def cmd_preview(args):
    cfg = load_config()
    now = now_local(cfg)
    today = now.date()
    posted_dates = {h["date"] for h in history()}
    start = today if (now.strftime("%H:%M") < cfg["post_time"] and today.isoformat() not in posted_dates) else today + timedelta(days=1)
    all_verses = verses.load()
    queue = queued_entries()
    taken = {e.get("verse_id") for e in queue.values()}
    made = []
    d = start
    while len(made) < args.days:
        ds = d.isoformat()
        d += timedelta(days=1)
        if ds in queue or ds in posted_dates:
            continue
        try:
            v, ill = pick_and_draw(all_verses, taken, args.placeholder)
        except illustrate.IllustrationError as e:
            notify(f"Preview: illustration failed for {ds}", str(e))
            continue
        if v is None:
            log.warning("Ran out of verses after %d posters.", len(made))
            break
        make_poster(v, ill, QUEUE / f"{ds}.jpg", cfg)
        write_json(QUEUE / f"{ds}.json", {
            "date": ds, "verse_id": v["id"], "caption": build_caption(v, cfg),
            **{k: v[k] for k in ["english_text", "english_ref", "tigrinya_text", "tigrinya_ref"]},
        })
        taken.add(v["id"])
        made.append((ds, v))

    # Summary used as the pull-request description
    base = os.environ.get("PREVIEW_IMAGE_BASE", "")
    lines = ["## Posters waiting for your approval", "",
             "**Merge this pull request to approve all of them.** To reject one day, delete its two files "
             "(`docs/queue/DATE.jpg` and `.json`) in this pull request before merging — that day will get a fresh poster.", ""]
    for ds, v in made:
        lines += [f"### {date.fromisoformat(ds).strftime('%A, %B %-d')} — {v['english_ref']}", ""]
        if base:
            lines += [f"<img src=\"{base}/docs/queue/{ds}.jpg\" width=\"360\">", ""]
        lines += ["```", build_caption(v, cfg), "```", ""]
    STATE.mkdir(exist_ok=True)
    (STATE / "preview.md").write_text("\n".join(lines), encoding="utf-8")
    set_output("count", str(len(made)))
    print(f"Made {len(made)} posters in docs/queue/")
    return 0


def _expiry_text(exp):
    if exp is None:
        return "unknown"
    if exp == 0:
        return "never expires"
    days = (exp - datetime.now().timestamp()) / 86400
    return f"expires in {days:.0f} days ({datetime.fromtimestamp(exp).date()})"


def cmd_check_instagram(args):
    from bot.instagram import Instagram, InstagramError
    cfg = load_config()
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    uid = os.environ.get("IG_USER_ID", "").strip()
    kind = ("Unified-login system-user token (graph.facebook.com)" if tok.startswith("EAA") else
            "Instagram-login token (graph.instagram.com)" if tok.startswith("IG") else "unknown token type")
    print(f"Token type: {kind}")
    try:
        ig = Instagram(tok, uid, cfg["instagram_api_version"])
        accts = ig.accounts()
    except InstagramError as e:
        print("Instagram check failed:", e)
        return 1
    if not accts:
        print("The token works, but no Instagram account is assigned to it.")
        return 1
    for a in accts:
        print(f"Can post to: @{a.get('username')} — Instagram account ID {a.get('id')}")
    print(f"Token {_expiry_text(ig.token_expiry())}.")
    ids = {str(a.get("id")) for a in accts}
    if uid not in ids:
        print(f"PROBLEM: the IG_USER_ID secret doesn't match. Set IG_USER_ID to the account ID shown above.")
        return 1
    print("IG_USER_ID matches. Ready to post.")
    return 0


def cmd_refresh_token(args):
    """Instagram-login tokens: get a fresh 60-day token. Unified-login tokens: check they still work
    and warn 2 weeks before any expiry (they normally never expire)."""
    from bot.instagram import Instagram, InstagramError, is_unified, refresh_token
    cfg = load_config()
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if is_unified(tok):
        try:
            ig = Instagram(tok, os.environ.get("IG_USER_ID", "").strip(), cfg["instagram_api_version"])
            ig.accounts()
            exp = ig.token_expiry()
        except InstagramError as e:
            notify("Instagram token stopped working", f"{e}\n\nFollow 'Get a new Instagram token' in the README.")
            return 1
        print(f"Token works and {_expiry_text(exp)}.")
        if exp and exp - datetime.now().timestamp() < 14 * 86400:
            notify("Instagram token expires soon", f"The token {_expiry_text(exp)}. "
                   "Follow 'Get a new Instagram token' in the README.")
        return 0
    try:
        new, expires_in = refresh_token(tok)
    except InstagramError as e:
        notify("Instagram token refresh failed", f"{e}\n\nPosting will stop when the token expires. "
               "Follow 'Get a new Instagram token' in the README.")
        return 1
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{new}")
    pathlib.Path(args.out).write_text(new)
    print(f"Token refreshed; valid for about {expires_in // 86400} more days.")
    return 0


def cmd_mezmur(args):
    from bot import mezmur
    return mezmur.run(load_config(), force=args.force, dry_run=args.dry_run, test=args.test)


def cmd_import_verses(args):
    from bot.fetch_verses import import_verses
    waiting = sum(1 for v in verses.load() if not v.get("posted") and not verses.problems(v))
    if args.min_waiting is not None and waiting >= args.min_waiting:
        print(f"{waiting} verses waiting — no top-up needed.")
        return 0
    added, warnings = import_verses(limit=args.limit)
    print(f"Added {added} verses from the online Bibles ({len(warnings)} skipped).")
    left = sum(1 for v in verses.load() if not v.get("posted") and not verses.problems(v))
    if left == 0:
        notify("Out of verses", "Every verse in data/verse_plan.json has been posted. Ask Claude to add more references to the plan.")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    r = sub.add_parser("render")
    r.add_argument("--verse")
    r.add_argument("--placeholder", action="store_true", help="use a test drawing instead of OpenAI")
    pr = sub.add_parser("prepare")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--force", action="store_true", help="ignore the posting-time check")
    pr.add_argument("--placeholder", action="store_true")
    sub.add_parser("publish")
    pv = sub.add_parser("preview")
    pv.add_argument("--days", type=int, default=7)
    pv.add_argument("--placeholder", action="store_true")
    sub.add_parser("check-instagram")
    rt = sub.add_parser("refresh-token")
    rt.add_argument("--out", required=True)
    mz = sub.add_parser("mezmur")
    mz.add_argument("--force", action="store_true", help="ignore the 8:00 AM time check")
    mz.add_argument("--dry-run", action="store_true", help="only say which video would be posted")
    mz.add_argument("--test", action="store_true", help="upload to Instagram but do NOT publish")
    iv = sub.add_parser("import-verses")
    iv.add_argument("--limit", type=int, help="add at most this many")
    iv.add_argument("--min-waiting", type=int, help="only import if fewer than this many verses are waiting")
    args = p.parse_args(argv)
    fn = {"validate": cmd_validate, "render": cmd_render, "prepare": cmd_prepare, "publish": cmd_publish,
          "preview": cmd_preview, "check-instagram": cmd_check_instagram, "refresh-token": cmd_refresh_token,
          "import-verses": cmd_import_verses, "mezmur": cmd_mezmur}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())

"""Tells you when something needs attention, by opening a GitHub Issue on the repo.

GitHub emails you about new issues on your own repository, so these reach your inbox
and phone (GitHub app) without any extra service.
"""
import logging
import os
import pathlib

import requests

log = logging.getLogger("notify")


FLAG = pathlib.Path(__file__).resolve().parent.parent / "state" / "notified"


def notify(title: str, body: str) -> None:
    log.warning("NOTIFY: %s — %s", title, body)
    try:  # lets the workflow know you were already told (avoids duplicate issues)
        FLAG.parent.mkdir(exist_ok=True)
        FLAG.touch()
    except OSError:
        pass
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return  # running locally: the log line above is enough
    run = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run = f"\n\n[See the full log]({os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']})"
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"title": f"[verse bot] {title}", "body": body + run},
            timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        log.error("Could not open GitHub issue: %s", type(e).__name__)

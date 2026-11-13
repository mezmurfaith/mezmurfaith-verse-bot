"""Instagram API — works with both kinds of Meta token:

- Unified login (new apps, token starts with "EAA"): graph.facebook.com.
  This is a system-user token; by default it never expires.
- Instagram login (older apps, token starts with "IG"): graph.instagram.com.
  Lasts 60 days and is refreshed weekly.

Posting = 1) create a media container from a public JPEG URL, 2) wait until it's ready,
3) publish it. Tokens are never printed: any error text has the token removed.
"""
import logging
import time

import requests

HOST = "https://graph.instagram.com"       # Instagram login
FB_HOST = "https://graph.facebook.com"     # Unified login
log = logging.getLogger("instagram")


def is_unified(token: str) -> bool:
    return token.startswith("EAA")


class InstagramError(Exception):
    pass


def _scrub(text: str, *secrets) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


class Instagram:
    def __init__(self, token: str, user_id: str, version: str = "v27.0"):
        if not token:
            raise InstagramError("IG_ACCESS_TOKEN is not set")
        self.token, self.user_id, self.version = token, user_id, version
        self.unified = is_unified(token)
        self.host = FB_HOST if self.unified else HOST

    def _call(self, method: str, path: str, **kw) -> dict:
        url = f"{self.host}/{self.version}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            r = requests.request(method, url, headers=headers, timeout=60, **kw)
            data = r.json() if r.content else {}
        except Exception as e:
            raise InstagramError(_scrub(f"Network error calling Instagram: {e}", self.token)) from None
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            msg = err.get("message") or r.text[:300]
            raise InstagramError(_scrub(f"Instagram API error {r.status_code} ({err.get('code')}): {msg}", self.token))
        return data

    def accounts(self) -> list[dict]:
        """Instagram accounts this token can post to: [{'id': ..., 'username': ...}]."""
        if self.unified:
            data = self._call("GET", "me/assigned_instagram_accounts", params={"fields": "id,username"})
            return data.get("data", [])
        data = self._call("GET", "me", params={"fields": "user_id,username"})
        if "data" in data and data["data"]:  # docs show both shapes
            data = data["data"][0]
        return [{"id": str(data.get("user_id")), "username": data.get("username")}]

    def token_expiry(self) -> int | None:
        """Unix time the token expires; 0 = never; None = unknown."""
        if not self.unified:
            return None
        try:
            d = self._call("GET", "debug_token", params={"input_token": self.token}).get("data", {})
            return int(d.get("expires_at", 0) or 0) if d else None
        except InstagramError:
            return None

    def publishing_quota(self) -> dict:
        return self._call("GET", f"{self.user_id}/content_publishing_limit", params={"fields": "config,quota_usage"})

    def create_image_container(self, image_url: str, caption: str, alt_text: str | None = None,
                               ai_generated: bool = False) -> str:
        body: dict = {"image_url": image_url, "caption": caption}
        if alt_text:
            body["alt_text"] = alt_text[:1000]
        if ai_generated:
            body["is_ai_generated"] = True
        return self._call("POST", f"{self.user_id}/media", json=body)["id"]

    def create_reel(self, video_path, caption: str, audio_id: str | None = None) -> str:
        """Upload a Reel video straight to Instagram (no public hosting needed). Returns the container id.
        With audio_id, Instagram adds that song from its music library and the video's own sound is turned down."""
        import json as _json
        import os as _os
        body: dict = {"media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true"}
        if audio_id:
            body["audio_configuration"] = _json.dumps({"audio_id": str(audio_id), "audio_volume": 100, "video_volume": 1})
        res = self._call("POST", f"{self.user_id}/media", data=body)
        cid = res["id"]
        uri = res.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.version}/{cid}"
        size = _os.path.getsize(video_path)
        try:
            with open(video_path, "rb") as f:
                r = requests.post(uri, data=f, timeout=300, headers={
                    "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)})
        except Exception as e:
            raise InstagramError(_scrub(f"Video upload failed: {type(e).__name__}: {e}", self.token)) from None
        if r.status_code >= 400:
            raise InstagramError(_scrub(f"Video upload failed ({r.status_code}): {r.text[:300]}", self.token))
        return cid

    def wait_until_ready(self, container_id: str, timeout: int = 300, every: int = 20) -> None:
        deadline = time.time() + timeout
        while True:
            d = self._call("GET", container_id, params={"fields": "status_code,status"})
            status = d.get("status_code")
            log.info("Container status: %s", status)
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram could not process the media (status {status}: {d.get('status')}).")
            if time.time() > deadline:
                raise InstagramError("Instagram took too long to process the image.")
            time.sleep(every)

    def publish(self, container_id: str) -> str:
        return self._call("POST", f"{self.user_id}/media_publish", json={"creation_id": container_id})["id"]

    def permalink(self, media_id: str) -> str | None:
        try:
            return self._call("GET", media_id, params={"fields": "permalink"}).get("permalink")
        except InstagramError:
            return None


def refresh_token(token: str) -> tuple[str, int]:
    """Get a fresh 60-day token. The old one must be at least 24 hours old and still valid."""
    try:
        r = requests.get(f"{HOST}/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=60)
        data = r.json()
    except Exception as e:
        raise InstagramError(_scrub(f"Network error refreshing token: {e}", token)) from None
    if r.status_code >= 400 or "access_token" not in data:
        msg = (data.get("error") or {}).get("message", "unknown error")
        raise InstagramError(_scrub(f"Token refresh failed ({r.status_code}): {msg}", token))
    return data["access_token"], int(data.get("expires_in", 0))


def wait_until_public(url: str, timeout: int = 600, every: int = 15) -> None:
    """Instagram downloads the image from this URL, so wait until it's really online."""
    deadline = time.time() + timeout
    while True:
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 10_000 and r.content[:3] == b"\xff\xd8\xff":
                return
            log.info("Image not public yet (HTTP %s), waiting…", r.status_code)
        except requests.RequestException as e:
            log.info("Image not reachable yet (%s), waiting…", type(e).__name__)
        if time.time() > deadline:
            raise InstagramError(f"Image never became publicly reachable: {url}")
        time.sleep(every)

"""YouTube Music: ytmusicapi for search, browsing and radio; yt-dlp for the audio stream URLs.

`yt` is replaced when someone signs in or out, so read it as youtube.yt, not `from .youtube import yt`."""
import asyncio
import threading
import time

import yt_dlp
from fastapi import HTTPException
from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicUserError

from .config import AUTH_FILE, FAIL_TTL, NODE, QUALITY, URL_TTL
from .settings import settings

yt = YTMusic(str(AUTH_FILE)) if AUTH_FILE.exists() else YTMusic()

ydl = yt_dlp.YoutubeDL({
    "format": QUALITY.get(settings["quality"], QUALITY["best"]),
    "quiet": True, "no_warnings": True, "noplaylist": True,
    "js_runtimes": {"node": {"path": str(NODE)}},
})
ydl_lock = threading.Lock()


def set_quality(quality: str):
    """Streams resolved from now on use this quality (blocking: call it in a thread)."""
    with ydl_lock:
        ydl.params["format"] = QUALITY[quality]
        ydl.format_selector = ydl.build_format_selector(QUALITY[quality])   # built once in __init__, not from params


def track_from(item: dict) -> dict | None:
    """Normalises any ytmusicapi song-like dict into the fields the UI needs."""
    vid = item.get("videoId")
    if not vid:
        return None
    named = [a for a in item.get("artists") or [] if a.get("name")]
    thumbs = item.get("thumbnails") or item.get("thumbnail") or []
    album = item.get("album")
    return {
        "videoId": vid,
        "title": item.get("title", ""),
        "artist": ", ".join(a["name"] for a in named),
        "album": album.get("name") if isinstance(album, dict) else (album or ""),
        "duration": item.get("duration") or item.get("length") or "",
        "thumb": thumbs[-1]["url"] if thumbs else "",
        # for "Go to artist / album": the first artist that has a page (YouTube leaves some without one)
        "artistId": next((a["id"] for a in named if (a.get("id") or "").startswith("UC")), ""),
        "albumId": (album.get("id") or "") if isinstance(album, dict) else "",
    }


def thumb_of(x: dict) -> str:
    """The biggest of an item's thumbnails (ytmusicapi lists them smallest first), or ""."""
    thumbs = x.get("thumbnails") or []
    return thumbs[-1].get("url", "") if thumbs else ""


def album_card(x: dict) -> dict:
    return {"type": "album", "id": x.get("browseId"), "title": x.get("title"),
            "subtitle": ", ".join(a["name"] for a in x.get("artists") or [] if a.get("name")),
            "thumb": thumb_of(x)}


async def yt_get(what: str, fn, *args, **kw):
    """A YouTube Music lookup; a bad or gone ID (or YouTube failing) becomes a readable 404/502, not a 500."""
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except (YTMusicUserError, KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise HTTPException(404, f"Couldn't find that {what} on YouTube Music")
    except Exception as e:
        if "404" in str(e) or "400" in str(e):
            raise HTTPException(404, f"Couldn't find that {what} on YouTube Music")
        raise HTTPException(502, f"YouTube Music didn't answer: {str(e)[:120]}")


_browse_cache: dict[str, tuple[float, object]] = {}


async def cached(key: str, fn, ttl: float = 3600):
    """YouTube Music's explore pages change slowly: fetch them at most once an hour."""
    hit = _browse_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = await fn()
    _browse_cache[key] = (time.time(), data)
    return data


async def radio_for(vid: str, limit: int = 30) -> list[dict]:
    """YouTube Music's own radio for a song (without the song itself); [] when it has none."""
    try:
        radio = await asyncio.to_thread(yt.get_watch_playlist, vid, radio=True, limit=limit)
    except Exception:
        return []
    return [t for t in map(track_from, radio.get("tracks", [])) if t and t["videoId"] != vid]


class Resolver:
    """Resolves videoIds to stream URLs in the background and caches them."""

    def __init__(self):
        self.cache: dict[str, tuple[float, str]] = {}
        self.pending: dict[str, asyncio.Future] = {}
        self.failed: dict[str, float] = {}   # videoId -> when it last failed to resolve

    def _extract(self, vid: str) -> str:
        with ydl_lock:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={vid}", download=False)
        return info["url"]

    async def get(self, vid: str, retry: bool = True) -> str:
        """retry=False (background work) gives up at once on a videoId that failed in the last FAIL_TTL s."""
        hit = self.cache.get(vid)
        if hit and time.time() - hit[0] < URL_TTL:
            return hit[1]
        if not retry and time.time() - self.failed.get(vid, 0) < FAIL_TTL:
            raise RuntimeError("failed recently")
        if vid not in self.pending:
            loop = asyncio.get_running_loop()
            self.pending[vid] = loop.run_in_executor(None, self._extract, vid)
        try:
            url = await self.pending[vid]
        except Exception:
            self.failed[vid] = time.time()
            raise
        finally:
            self.pending.pop(vid, None)
        self.failed.pop(vid, None)
        self.cache[vid] = (time.time(), url)
        return url

    def prefetch(self, vid: str) -> None:
        asyncio.get_running_loop().create_task(self._quiet(vid))

    async def _quiet(self, vid: str) -> None:
        try:
            await self.get(vid, retry=False)
        except Exception:
            pass

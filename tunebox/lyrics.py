"""Lyrics: LRCLIB (free, open, often time-synced) first, YouTube Music's own as the fallback."""
import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import youtube

lyrics_cache: dict[str, dict] = {}
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def secs(duration: str) -> int:
    try:
        n = 0
        for part in str(duration).split(":"):
            n = n * 60 + int(part)
        return n
    except ValueError:
        return 0


def clean_title(t: str) -> str:
    t = re.sub(r"\s*[\(\[][^)\]]*(remaster|version|live|edit|mix|mono|stereo|feat\.?|ft\.)[^)\]]*[\)\]]", "", t, flags=re.I)
    return re.sub(r"\s+-\s+.*(remaster|version|edit).*$", "", t, flags=re.I).strip()


def lrclib(path: str, params: dict):
    url = f"https://lrclib.net/api/{path}?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    req = urllib.request.Request(url, headers={"User-Agent": "Tunebox/1.0 (home music server)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def parse_lrc(text: str) -> list:
    out = []
    for line in text.splitlines():
        m = LRC_LINE.match(line.strip())
        if m:
            out.append([round(int(m[1]) * 60 + float(m[2]), 2), m[3].strip()])
    return out


def fetch_lyrics(vid: str, title: str, artist: str, album: str, duration: str) -> dict:
    artist1 = (artist or "").split(",")[0].strip()
    dur = secs(duration)
    hit = None
    try:
        hit = lrclib("get", {"track_name": title, "artist_name": artist1, "album_name": album, "duration": dur})
        if not hit or not (hit.get("syncedLyrics") or hit.get("plainLyrics")):
            found = lrclib("search", {"track_name": clean_title(title), "artist_name": artist1}) or []
            found = [f for f in found if f.get("syncedLyrics") or f.get("plainLyrics")]
            found.sort(key=lambda f: (not f.get("syncedLyrics"), abs((f.get("duration") or 0) - dur) if dur else 0))
            hit = found[0] if found and (not dur or abs((found[0].get("duration") or 0) - dur) < 15) else None
    except Exception:
        hit = None
    if hit and hit.get("instrumental"):
        return {"instrumental": True, "source": "LRCLIB"}
    if hit:
        synced = parse_lrc(hit.get("syncedLyrics") or "")
        return {"synced": synced or None, "plain": hit.get("plainLyrics") or "", "source": "LRCLIB"}
    try:
        w = youtube.yt.get_watch_playlist(vid, limit=1)
        if w.get("lyrics"):
            l = youtube.yt.get_lyrics(w["lyrics"])
            if l and l.get("lyrics"):
                return {"synced": None, "plain": l["lyrics"], "source": l.get("source") or "YouTube Music"}
    except Exception:
        pass
    return {"none": True}


async def lyrics_for(vid: str, title: str, artist: str, album: str, duration: str) -> dict:
    """Cached per song: the drawer, the canvas and the wall all ask for the same one."""
    if vid not in lyrics_cache:
        res = await asyncio.to_thread(fetch_lyrics, vid, title, artist, album, duration)
        if len(lyrics_cache) > 300:
            lyrics_cache.clear()
        lyrics_cache[vid] = res
    return lyrics_cache[vid]

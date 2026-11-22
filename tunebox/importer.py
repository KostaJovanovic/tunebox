"""Importing a playlist from a file: an m3u, a CSV (TuneMyMusic, Exportify and the like) or plain text,
one song per line. parse() turns the file into rows; a Job searches YouTube Music for each row in the
background, about one a second, and keeps the best match with a few others for the page's review.
Saving is the playlists' own routes: a job only finds songs.

Jobs live in memory (a restart forgets them) and are forgotten a day after they finish."""
import asyncio
import csv
import difflib
import io
import re
import secrets
import time
import unicodedata
import urllib.parse

from . import blocklist, house, local, youtube
from .youtube import track_from, yt_get

MAX_ROWS = 2000
PACE = 0.6                                    # seconds between searches, so YouTube doesn't start refusing
KEEP = 24 * 3600                              # a finished job is forgotten after this
SURE = 0.85                                   # how alike two titles must be to need no review

# ---------- reading the file ----------
YT_LINK = re.compile(r"(?:youtube\.com/(?:watch\?\S*?v=|shorts/)|youtu\.be/)([\w-]{11})")
NUMBERING = re.compile(r"^\s*\d{1,4}\s*[.)\-–]\s+")
DURATION = re.compile(r"\s*[(\[]?\d{1,2}:\d{2}(?::\d{2})?[)\]]?\s*$")
DASH = re.compile(r"\s+[-–—]\s+")


def _row(text: str, title: str = "", artist: str = "", album: str = "", isrc: str = "", playlist: str = "") -> dict:
    m = YT_LINK.search(text)
    return {"text": text, "title": title, "artist": artist, "album": album, "isrc": isrc.strip().upper(),
            "playlist": playlist, "videoId": m.group(1) if m else ""}


def _line(s: str, playlist: str = "") -> dict | None:
    """One line of text: "Artist - Title", "1. Artist - Title 3:45", a bare title, or a YouTube link."""
    s = DURATION.sub("", NUMBERING.sub("", s)).strip()
    if not s or s.startswith("#"):
        return None
    parts = DASH.split(s, maxsplit=1)
    return _row(s, parts[1], parts[0], playlist=playlist) if len(parts) == 2 else _row(s, s, playlist=playlist)


def _m3u(lines: list[str]) -> list[dict]:
    rows, name, extinf = [], "", ""
    for s in lines:
        s = s.strip()
        if s.upper().startswith("#PLAYLIST:"):
            name = s[10:].strip()
        elif s.upper().startswith("#EXTINF"):
            extinf = s.partition(",")[2].strip()
        elif s and not s.startswith("#"):
            if YT_LINK.search(s):
                rows.append(_row(s))
            else:                             # a path or a URL: the EXTINF text, or else the file's own name
                stem = urllib.parse.unquote(re.split(r"[/\\]", s.split("?")[0])[-1]).rpartition(".")
                r = _line(extinf or stem[0] or stem[2])
                if r:
                    rows.append(r)
            extinf = ""
    for r in rows:
        r["playlist"] = name
    return rows


def _key(h: str) -> str:
    return re.sub(r"[^a-z]", "", h.lower())


def _csv(text: str) -> list[dict] | None:
    """A table with a header naming the columns, in any order; None when it isn't one."""
    first = text.split("\n", 1)[0]
    delim = max(",;\t", key=first.count)
    if not first.count(delim):
        return None
    table = list(csv.reader(io.StringIO(text), delimiter=delim))
    head = [_key(h) for h in table[0]]

    def col(*names, start=False):
        return next((i for i, h in enumerate(head) for n in names if h == n or (start and h.startswith(n))), None)
    title = col("trackname", "track", "title", "songname", "song", "name", "tracktitle")
    if title is None:
        return None
    artist, album = col("artist", start=True), col("albumname", "album")
    isrc, playlist = col("isrc"), col("playlist", start=True)
    rows = []
    for cells in table[1:]:
        get = lambda i: cells[i].strip() if i is not None and i < len(cells) else ""   # noqa: E731
        if get(title):
            rows.append(_row(" - ".join(filter(None, (get(artist), get(title)))), get(title), get(artist),
                             get(album), get(isrc), get(playlist)))
    return rows


def parse(text: str) -> list[dict]:
    """The songs in an m3u, a CSV or plain text, in order. Each row knows the playlist it came from
    ("" when the file doesn't say)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines[0].strip().upper().startswith("#EXTM3U") or any(s.upper().startswith("#EXTINF") for s in lines[:50]):
        rows = _m3u(lines)
    else:
        rows = _csv(text)
        if rows is None:
            rows = [r for r in map(_line, lines) if r]
    return rows[:MAX_ROWS]


# ---------- how alike two songs are ----------
VERSION = (r"(?:\d{4} )?remaster(?:ed)?(?: version)?(?: \d{4})?|single version(?: / remastered)?|album version|"
           r"radio edit|mono|stereo|original mix|bonus track|explicit|clean")
FEAT = re.compile(r"[(\[]\s*(?:feat|ft|with)\b[^)\]]*[)\]]|\s(?:feat|ft)\.?\s.*$", re.I)


def norm(title: str) -> str:
    """For comparing titles: no "(feat. ...)", no "- 2010 Remaster" or "(Single Version)", no punctuation.
    No accents either. "(Sped Up)", "(Live)" and the like stay, so another version of a song doesn't pass for it."""
    t = unicodedata.normalize("NFKD", FEAT.sub(" ", title.lower()).replace("đ", "d").replace("ø", "o"))
    t = "".join(c for c in t if not unicodedata.combining(c))     # Savic and Savić are the same name
    t = re.sub(rf"\s[-–—]\s(?:{VERSION})\s*$|[(\[]\s*(?:{VERSION})\s*[)\]]", " ", t)
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def _artist_ok(want: str, got: str) -> bool:
    if not want:
        return False
    w, g = norm(want), norm(got)
    first = norm(re.split(r",| & | x | and |;", want.lower())[0])
    return bool(w and g) and (w in g or g in w or (first and first in g))


def score(row: dict, t: dict) -> float:
    """0 to 1: the title's likeness, which counts only half when the artist isn't the one asked for."""
    a, b = norm(row["title"]), norm(t["title"])
    alike = difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0
    if a and b and (a in b or b in a) and min(len(a), len(b)) >= 4:
        alike = max(alike, 0.9)
    return alike if _artist_ok(row["artist"], t["artist"]) else alike / 2


# ---------- the jobs ----------
jobs: dict[str, dict] = {}
_found: dict[str, list[dict]] = {}            # query -> songs, so a second import of the same file is quick
_tasks: dict[str, asyncio.Task] = {}


async def _search(q: str) -> tuple[list[dict], bool]:
    """Songs for q (local songs first when they're on), and whether YouTube was asked."""
    if q in _found:
        return _found[q], False
    mine = local.search(q, 3) if house.on("local") else []
    res = await yt_get("search", youtube.yt.search, q, filter="songs", limit=10)
    out = [t for t in mine + [track_from(r) for r in res] if t and not blocklist.blocked(t)]
    if len(_found) >= 3000:
        del _found[next(iter(_found))]
    _found[q] = out
    return out, True


async def match(row: dict) -> bool:
    """Fills in the row's match; True when YouTube was asked (the caller then waits a little)."""
    asked = False
    if row["videoId"]:
        w = await yt_get("song", youtube.yt.get_watch_playlist, row["videoId"], limit=1)
        t = track_from((w.get("tracks") or [{}])[0])
        row.update(track=t, alts=[], state="sure" if t and not blocklist.blocked(t) else "none")
        return True
    if row["isrc"]:                           # the exact recording, when YouTube knows the code
        found, asked = await _search(row["isrc"])
        if found and difflib.SequenceMatcher(None, norm(row["title"]), norm(found[0]["title"])).ratio() >= 0.8:
            row.update(track=found[0], alts=[], state="sure")
            return asked
    q = " ".join(filter(None, (row["artist"], row["title"])))
    found, more = await _search(q)
    ranked = sorted(found, key=lambda t: -score(row, t))       # sorted() keeps YouTube's order for ties
    best = ranked[0] if ranked else None
    row.update(track=best, alts=[t for t in found if t is not best][:5],
               state="none" if not best else "sure" if score(row, best) >= SURE else "unsure")
    return asked or more


async def _run(job: dict):
    try:
        for row in job["rows"]:
            for tries in range(3):
                try:
                    if await match(row):
                        await asyncio.sleep(PACE)
                    break
                except Exception as exc:      # YouTube refusing or away: wait, try again, then give up on this row
                    if tries == 2 or getattr(exc, "status_code", 0) == 404:
                        row.update(track=None, alts=[], state="none", error=getattr(exc, "detail", "") or youtube.short_error(exc))
                        break
                    await asyncio.sleep(5 * (tries + 1))
            job["done"] += 1
        job["status"] = "done"
    finally:
        job["finished"] = time.time()
        _tasks.pop(job["id"], None)


def tidy():
    now = time.time()
    for jid in [j for j, job in jobs.items() if job.get("finished") and now - job["finished"] > KEEP]:
        del jobs[jid]


def start(rows: list[dict], name: str, owner: str) -> dict:
    tidy()
    jid = secrets.token_hex(6)
    names = list(dict.fromkeys(r["playlist"] for r in rows if r["playlist"]))
    for r in rows:
        r.update(state="wait", track=None, alts=[])
    jobs[jid] = {"id": jid, "name": name, "owner": owner, "names": names, "rows": rows, "done": 0,
                 "status": "running", "created": time.time(), "finished": None}
    _tasks[jid] = asyncio.get_running_loop().create_task(_run(jobs[jid]))
    return jobs[jid]


def forget(jid: str):
    t = _tasks.pop(jid, None)
    if t:
        t.cancel()
    jobs.pop(jid, None)


def summary(job: dict) -> dict:
    count = lambda s: sum(r["state"] == s for r in job["rows"])   # noqa: E731
    return {k: job[k] for k in ("id", "name", "owner", "names", "done", "status", "created")} | {
        "total": len(job["rows"]), "sure": count("sure"), "unsure": count("unsure"), "none": count("none")}

"""Quick self-check of the logic that is easy to break and hard to notice: the same-site guard, fair
turns, rewriting the play log, Top 30, the house's setup, the lyrics cache and reading imported playlists. Plain asserts, no test framework.

    .venv\\Scripts\\python dev\\check.py      (or: .venv/bin/python dev/check.py)

It runs on an empty data folder of its own (TUNEBOX_DATA), never on the real one."""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["TUNEBOX_DATA"] = tempfile.mkdtemp(prefix="tunebox-check-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from tunebox import house, importer, lyrics, plays  # noqa: E402
from tunebox.api import stats  # noqa: E402
from tunebox.api.house import HouseBody, change  # noqa: E402
from tunebox.player import Player  # noqa: E402
from tunebox.web import host_ok  # noqa: E402


def check_host_ok():
    for h in ("localhost:8888", "127.0.0.1", "192.168.1.5:8888", "10.0.0.2", "[::1]:8888", "100.64.0.1", "ele.local", "pi.tail1.ts.net"):
        assert host_ok(h), h
    for h in ("evil.com", "evil.com:8888", "8.8.8.8", "[2001:4860::8888]:80", "", None, "localhost.evil.com"):
        assert not host_ok(h), h


def check_turns():
    """A adds 3, then B 2, then C 1: they take turns, A B C A B A."""
    p = Player()
    p.queue, p.index = [{"videoId": "cur", "by": "", "src": "user"}], 0
    for by in "AAABBC":
        p.queue.insert(p.turn_slot(by), {"videoId": by, "by": by, "src": "user"})
    assert [t["by"] for t in p.queue[1:]] == list("ABCABA"), [t["by"] for t in p.queue]


def check_import():
    """The three kinds of file, as TuneMyMusic, players and people write them."""
    csv_ = ('﻿Track name,Artist name,Album,Playlist name,Type,ISRC,Spotify - id\n'
            '"Call It Fate, Call It Karma","The Strokes","Comedown Machine","valjdaslike","Playlist","USRC11300085","3Y4r"\n'
            '"Where This Flower Blooms (feat. Frank Ocean)","Tyler, The Creator","Flower Boy","Rektorat","Playlist","x","y"\n')
    a, b = importer.parse(csv_)
    assert (a["title"], a["artist"], a["isrc"], a["playlist"]) == ("Call It Fate, Call It Karma", "The Strokes", "USRC11300085", "valjdaslike"), a
    assert (b["artist"], b["playlist"]) == ("Tyler, The Creator", "Rektorat"), b
    txt = "﻿Blondie - Heart Of Glass - Single Version / Remastered\n\n01. Men I Trust - Show Me How 3:35\nJust A Title"
    r = importer.parse(txt)
    assert [(x["artist"], x["title"]) for x in r] == [("Blondie", "Heart Of Glass - Single Version / Remastered"),
                                                      ("Men I Trust", "Show Me How"), ("", "Just A Title")], r
    m3u = ("#EXTM3U\n#PLAYLIST:Car\n#EXTINF:213,Arctic Monkeys - Jet Skis On The Moat\nC:\\Music\\a.mp3\n"
           "/music/Vansire%20-%20From%20the%20Subway%20Train.flac\nhttps://youtu.be/dQw4w9WgXcQ\n")
    r = importer.parse(m3u)
    assert [(x["artist"], x["title"], x["videoId"], x["playlist"]) for x in r] == [
        ("Arctic Monkeys", "Jet Skis On The Moat", "", "Car"), ("Vansire", "From the Subway Train", "", "Car"),
        ("", "", "dQw4w9WgXcQ", "Car")], r
    assert importer.norm("Heart Of Glass - Single Version / Remastered") == importer.norm("Heart of Glass") == "heart of glass"
    assert importer.norm("Woman - Remastered 2010") == "woman"
    assert importer.norm("Snežana Savić Đavoli") == importer.norm("Snezana Savic Davoli")
    assert importer.norm("Holding My Heart (Sped Up)") != importer.norm("Holding My Heart")
    row = {"title": "Lady Brown (feat. Cise Starr from CYNE)", "artist": "Nujabes"}
    assert importer.score(row, {"title": "Lady Brown", "artist": "Nujabes, Cise Starr"}) >= importer.SURE
    assert importer.score(row, {"title": "Lady Brown", "artist": "Someone Else"}) < importer.SURE


def play(t, v, by="", s=200):
    return {"t": t, "v": v, "ti": v, "ar": "", "al": "", "th": "", "ai": "", "d": 200, "s": s, "by": by, "sem": [], "src": "user", "a": 0}


def check_rewrite_and_top():
    now = int(time.time())
    plays.PLAYS_DIR.mkdir(parents=True, exist_ok=True)
    log = [play(now - 300, "aaaaaaaaaaa", "x"), play(now - 200, "bbbbbbbbbbb", "y"), play(now - 100, "bbbbbbbbbbb", "y"),
           play(now - 50, "ccccccccccc", "y", s=3)]     # c: skipped after 3 s, no play
    plays.month_file(now).write_text("".join(json.dumps(p) + "\n" for p in log), encoding="utf-8")
    top = stats.most_played(30)
    assert [(n, t["videoId"]) for n, t in top] == [(2, "bbbbbbbbbbb"), (1, "aaaaaaaaaaa")], top
    assert plays.rewrite(lambda p: None if p["by"] == "x" else p) == 1
    assert [p["v"] for p in plays.read(0)] == ["bbbbbbbbbbb", "bbbbbbbbbbb", "ccccccccccc"]
    assert plays.rewrite(lambda p: {**p, "by": "z"} if p["by"] == "y" else p) == 3
    assert {p["by"] for p in plays.read(0)} == {"z"}


def check_house_change():
    """A refused value changes nothing, not even the good ones sent with it."""
    name = house.house["name"]
    try:
        change(HouseBody(name="Elsewhere", quiet={"max": "loud"}))
        raise AssertionError("a volume that isn't a number was taken")
    except HTTPException as exc:
        assert exc.status_code == 400
    assert house.house["name"] == name
    change(HouseBody(name="Elsewhere", quiet={"hours": "22:00-07:00", "max": "25"}))
    assert house.house["name"] == "Elsewhere" and house.house["quiet"] == {"hours": "22:00-07:00", "max": 25}


async def check_lyrics_cache():
    """A "none" from a network failure is asked again; a sure one is kept, per title (a renamed song asks again)."""
    asked, answers = [], [({"none": True}, False), ({"plain": "la", "source": "LRCLIB"}, True)]
    real, lyrics.fetch_lyrics = lyrics.fetch_lyrics, lambda *a: (asked.append(a[1]), answers[min(len(asked), 2) - 1])[1]
    try:
        assert (await lyrics.lyrics_for("local:0123456789abcdef", "Untitled", "", "", ""))["none"]
        assert (await lyrics.lyrics_for("local:0123456789abcdef", "Untitled", "", "", ""))["plain"] == "la"
        await lyrics.lyrics_for("local:0123456789abcdef", "Untitled", "", "", "")
        assert asked == ["Untitled", "Untitled"], asked       # the sure answer was kept
        await lyrics.lyrics_for("local:0123456789abcdef", "Real Title", "", "", "")
        assert asked[-1] == "Real Title"
    finally:
        lyrics.fetch_lyrics = real


async def main():
    check_host_ok()
    check_turns()
    check_import()
    check_rewrite_and_top()
    check_house_change()
    await check_lyrics_cache()
    print("ok")


asyncio.run(main())

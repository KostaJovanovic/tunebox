"""Records the music for the demo: what a real Tunebox answers for search, Home, Explore, moods, albums,
artists, playlists, the radio and lyrics, saved to dev/demo/music.json. The demo's service worker
(dev/demo/sw.js) plays these answers back, so the pages get exactly the shapes the server sends.

Start a silent Tunebox first, then point this at it:
  python dev/emulate.py --silent --no-browser --port 8777 --data %TEMP%\\tb-capture
  python dev/demo/capture.py http://127.0.0.1:8777/music/
Standard library only. Run it again to refresh the music; it takes a few minutes.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8777/music/").rstrip("/") + "/"
OUT = Path(__file__).with_name("music.json")
ARTISTS = ["Daft Punk", "Fleetwood Mac", "Radiohead", "Kendrick Lamar", "Massive Attack", "Bonobo", "Nina Simone",
           "Tame Impala", "Beyonce", "Arctic Monkeys", "Bjork", "Khruangbin", "Phoebe Bridgers", "The Beatles",
           "Miles Davis", "Dua Lipa", "Rosalia", "Bad Bunny", "Fela Kuti", "Air", "Portishead", "Amy Winehouse",
           "Stevie Wonder", "Billie Eilish"]
KINDS = ["songs", "albums", "artists", "playlists"]

pages: dict[str, object] = {}


def get(path: str):
    """One answer from the server, stored under its path; None when it failed (it is left out)."""
    if path in pages:
        return pages[path]
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as r:
            pages[path] = json.load(r)
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        print(f"  skipped {path}: {exc}", file=sys.stderr)
        return None
    return pages[path]


def many(paths):
    paths = [p for p in dict.fromkeys(paths) if p not in pages]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(get, paths))
    print(f"  {len(pages)} answers so far")


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def items_of(x) -> list:
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return (x.get("items") or []) + (x.get("tracks") or []) + (x.get("albums") or []) + (x.get("releases") or [])
    return []


def main():
    print("home, explore, moods")
    many(["api/home", "api/explore"])
    moods = [m["params"] for g in (pages.get("api/explore") or {}).get("moods", []) for m in g["items"]]
    many([f"api/mood?params={q(m)}" for m in moods[:30]])

    print("search")
    many([f"api/search?q={q(a)}&kind={k}" for a in ARTISTS for k in KINDS])

    print("artists, albums, playlists")
    first = lambda path, n: [x for x in (pages.get(path) or []) if x.get("id")][:n]
    many([f"api/artist/{q(x['id'])}" for a in ARTISTS for x in first(f"api/search?q={q(a)}&kind=artists", 1)])
    many([f"api/album/{q(x['id'])}" for a in ARTISTS for x in first(f"api/search?q={q(a)}&kind=albums", 4)])
    many([f"api/playlist/{q(x['id'])}" for a in ARTISTS for x in first(f"api/search?q={q(a)}&kind=playlists", 2)])
    shelf = [i for s in pages.get("api/home") or [] for i in s["items"]]
    shelf += [i for k, v in pages.items() if k.startswith(("api/mood", "api/explore")) for i in items_of(v)[:8]]
    shelf += [i for k, v in list(pages.items()) if k.startswith("api/artist/") for i in v.get("albums", [])]
    many([f"api/{i['type']}/{q(i['id'])}" for i in shelf if i.get("type") in ("album", "playlist") and i.get("id")])

    # the songs the demo's house plays: each artist's best few
    songs = {}
    for a in ARTISTS:
        for t in (pages.get(f"api/search?q={q(a)}&kind=songs") or [])[:6]:
            songs.setdefault(t["videoId"], t)
    seeds = list(songs.values())
    print(f"radio for {len(seeds)} songs")
    many([f"api/playlist/RDAMVM{t['videoId']}" for t in seeds])
    print("lyrics")
    many(["api/lyrics?" + urllib.parse.urlencode({k: t.get(k, "") for k in ("videoId", "title", "artist", "album", "duration")})
          for t in seeds])

    radio = {k[len("api/playlist/RDAMVM"):]: [t for t in v["tracks"] if t["videoId"] != k[len("api/playlist/RDAMVM"):]]
             for k, v in pages.items() if k.startswith("api/playlist/RDAMVM")}
    lyrics = {urllib.parse.parse_qs(k.split("?", 1)[1])["videoId"][0]: v for k, v in pages.items() if k.startswith("api/lyrics?")}
    browse = {k: v for k, v in pages.items() if not k.startswith(("api/playlist/RDAMVM", "api/lyrics?"))}
    out = {"artists": ARTISTS, "seeds": [t["videoId"] for t in seeds], "pages": browse, "radio": radio,
           "lyrics": {k: v for k, v in lyrics.items() if not v.get("none")}}
    write(out)


def write(out: dict):
    """Long playlists and radios are cut short: the demo downloads this file whole."""
    for k, v in out["pages"].items():
        if k.startswith("api/playlist/") and isinstance(v, dict):
            v["tracks"] = v["tracks"][:40]
    out["radio"] = {k: v[:25] for k, v in out["radio"].items()}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(out['pages'])} pages, {len(out['radio'])} radios, {len(out['lyrics'])} lyrics")


if __name__ == "__main__":
    main()

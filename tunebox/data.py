"""What the house shares: play history, playlists, people and play counts, each in its own JSON file.

The containers are changed in place and never replaced, so other modules can import them. The
revision numbers are replaced, so read them as data.lists_rev / data.people_rev."""
import re
import sys
import time

from .config import (HISTORY_FILE, HISTORY_MAX, LIKED_ID, LISTS_FILE, PEOPLE_FILE, SEMINAR_COLORS, SEMINARS,
                     SEMINARS_FILE, STATS_DAYS, STATS_FILE)
from . import local
from .files import read_json, write_json

VIDEO_ID = re.compile(r"[\w-]{11}")          # YouTube's video IDs: always 11 of these
TRACK_KEYS = ("videoId", "title", "artist", "album", "duration", "thumb", "artistId", "albumId")


def clean_track(t: dict) -> dict | None:
    """Only the fields a song needs, as short strings (anything else a client sends is dropped).
    A local song is looked up: what it is called is the server's to say, and one that was removed is no song."""
    if isinstance(t, dict) and local.is_local(t.get("videoId")):
        return local.track_of(t["videoId"])
    if not isinstance(t, dict) or not VIDEO_ID.fullmatch(str(t.get("videoId") or "")):
        return None
    return {k: str(t.get(k) or "")[:300] for k in TRACK_KEYS}


# ---------- history: recently played, newest first ----------
history: list[dict] = read_json(HISTORY_FILE, [])


def add_history(track: dict | None):
    if not track or (history and history[0]["videoId"] == track["videoId"]):
        return
    count_play(track)
    history.insert(0, {**track, "playedAt": int(time.time())})
    del history[HISTORY_MAX:]
    try:
        write_json(HISTORY_FILE, history)
    except OSError:
        pass


def clear_history():
    history.clear()
    write_json(HISTORY_FILE, history)


# ---------- playlists, including the built-in Liked songs ----------
playlists: dict[str, dict] = read_json(LISTS_FILE, {})


def ensure_liked():
    if LIKED_ID not in playlists:
        playlists[LIKED_ID] = {"id": LIKED_ID, "name": "Liked songs", "tracks": [], "created": int(time.time()), "updated": int(time.time())}


ensure_liked()
lists_rev = time.time_ns() // 1_000_000        # bumped on every playlist change, so clients refresh their liked hearts


def save_lists():
    global lists_rev
    lists_rev += 1
    write_json(LISTS_FILE, playlists)


def sorted_lists():
    """Liked songs first, then the most recently changed."""
    return sorted(playlists.values(), key=lambda p: (p["id"] != LIKED_ID, -p["updated"]))


def list_summary(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "count": len(p["tracks"]), "updated": p["updated"],
            "thumbs": [t["thumb"] for t in p["tracks"][:4]], "liked": p["id"] == LIKED_ID, "owner": p.get("owner", ""), "auto": bool(p.get("auto"))}


# ---------- people: names picked per device ----------
people: dict[str, dict] = read_json(PEOPLE_FILE, {})
people_rev = time.time_ns() // 1_000_000       # bumped when names change, so clients refresh their chips


def save_people():
    global people_rev
    people_rev += 1
    write_json(PEOPLE_FILE, people)


# ---------- groups: {id: {id, name, color}}. The code calls them seminars, which they were in the house
# this began in; what a house calls them is in house.json ----------
def load_seminars() -> dict:
    """The groups as saved. A file from before the admin could edit them holds only the added ones:
    the three built-in ones go with it."""
    saved = read_json(SEMINARS_FILE, None)
    if isinstance(saved, dict) and saved.get("v") == 2:
        return dict(saved.get("groups") or {})
    return {**SEMINARS, **(saved if isinstance(saved, dict) else {})}


seminars: dict[str, dict] = load_seminars()


def save_seminars():
    write_json(SEMINARS_FILE, {"v": 2, "groups": seminars})
    save_people()                             # bumps people_rev: clients reload names and groups together


def find_seminar(name: str) -> str | None:
    """A group's id, by id or by name (any case)."""
    low = name.strip().lower()
    return low if low in seminars else next((k for k, s in seminars.items() if s["name"].lower() == low), None)


def add_seminar(name: str) -> dict:
    """A new group, in the next colour. Its id is its name in lower case (made unique if need be)."""
    name = " ".join(name.split())[:24]
    sid = base = re.sub(r"[^\w]+", "-", name.lower()).strip("-") or "group"
    n = 1
    while sid in seminars:
        n += 1
        sid = f"{base}-{n}"
    seminars[sid] = {"id": sid, "name": name, "color": SEMINAR_COLORS[len(seminars) % len(SEMINAR_COLORS)]}
    save_seminars()
    return seminars[sid]


def seminars_of(pid: str) -> list[str]:
    return list((people.get(pid) or {}).get("seminars") or [])


# ---------- play counts for "Most played", last STATS_DAYS days ----------
stats: dict[str, dict] = read_json(STATS_FILE, {})   # {videoId: {"track": {...}, "plays": [ts, ...]}}
_stats_dirty = False


def count_play(track: dict, when: float | None = None):
    """Remembers when a song played; saved with the session every minute (spares the SD card)."""
    global _stats_dirty
    s = stats.setdefault(track["videoId"], {"plays": []})
    s["track"] = clean_track(track)
    s["plays"].append(int(when or time.time()))
    _stats_dirty = True


def most_played(n: int) -> list[tuple[int, dict]]:
    """The n songs played most in the last STATS_DAYS days, as (plays, track); on a tie, the one played last first."""
    now = time.time()
    counts = []
    for s in stats.values():
        recent = [t for t in s["plays"] if now - t < STATS_DAYS * 86400]
        if recent and s.get("track"):
            counts.append((len(recent), max(recent), s["track"]))
    counts.sort(key=lambda c: (-c[0], -c[1]))
    return [(c[0], c[2]) for c in counts[:n]]


def save_stats(force: bool = False):
    global _stats_dirty
    if not (_stats_dirty or force):
        return
    cutoff = time.time() - STATS_DAYS * 86400
    for vid in list(stats):
        stats[vid]["plays"] = [t for t in stats[vid]["plays"] if t > cutoff][-500:]
        if not stats[vid]["plays"]:
            del stats[vid]
    try:
        write_json(STATS_FILE, stats)
        _stats_dirty = False
    except OSError as exc:
        print(f"tunebox: cannot save stats: {exc}", file=sys.stderr)


if not STATS_FILE.exists():                   # first start: begin with what the history already knows
    for h in reversed(history):
        if h.get("videoId") and time.time() - h.get("playedAt", 0) < STATS_DAYS * 86400:
            count_play(h, h["playedAt"])


"""What the house shares: play history, playlists, people and play counts, each in its own JSON file.

The containers are changed in place and never replaced, so other modules can import them. The
revision numbers are replaced, so read them as data.lists_rev / data.people_rev."""
import re
import sys
import time

from .config import (HISTORY_FILE, HISTORY_MAX, LIKED_ID, LISTS_FILE, PEOPLE_FILE, SEMINAR_COLORS, SEMINARS,
                     SEMINARS_FILE, STATS_DAYS, STATS_FILE)
from .files import read_json, write_json

VIDEO_ID = re.compile(r"[\w-]{11}")          # YouTube's video IDs: always 11 of these
TRACK_KEYS = ("videoId", "title", "artist", "album", "duration", "thumb", "artistId", "albumId")


def clean_track(t: dict) -> dict | None:
    """Only the fields a song needs, as short strings (anything else a client sends is dropped)."""
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
if LIKED_ID not in playlists:
    playlists[LIKED_ID] = {"id": LIKED_ID, "name": "Liked songs", "tracks": [], "created": int(time.time()), "updated": int(time.time())}
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
            "thumbs": [t["thumb"] for t in p["tracks"][:4]], "liked": p["id"] == LIKED_ID}


# ---------- people: names picked per device ----------
people: dict[str, dict] = read_json(PEOPLE_FILE, {})
people_rev = time.time_ns() // 1_000_000       # bumped when names change, so clients refresh their chips


def save_people():
    global people_rev
    people_rev += 1
    write_json(PEOPLE_FILE, people)


# ---------- seminars: every person is in at least one ----------
seminars: dict[str, dict] = {**SEMINARS, **read_json(SEMINARS_FILE, {})}   # {id: {id, name, color}}; id = name.lower()


def add_seminar(name: str) -> dict:
    """A seminar someone typed under Other (3 letters or digits); the next free colour."""
    sid = name.lower()
    if sid not in seminars:
        custom = {k: v for k, v in seminars.items() if k not in SEMINARS}
        seminars[sid] = {"id": sid, "name": name[:1].upper() + name[1:].lower(),
                         "color": SEMINAR_COLORS[len(custom) % len(SEMINAR_COLORS)]}
        write_json(SEMINARS_FILE, {k: v for k, v in seminars.items() if k not in SEMINARS})
        save_people()                         # bumps people_rev: clients reload names and seminars together
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


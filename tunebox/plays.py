"""The play log: every song that played, kept for good (Stats and the recap read it).

One JSON line per play, in a file per month (plays/2026-09.jsonl), only ever appended to:
  {"t": started, "v": videoId, "ti": title, "ar": artist, "al": album, "th": thumb, "ai": artistId,
   "d": length (s), "s": seconds actually heard (pauses don't count), "by": person id or "",
   "sem": their seminars then, "src": "user" or "auto" (radio)}
The song playing is counted in memory; finished plays are written with the session, at most once a
minute (spares an SD card)."""
import json
import sys
import time
from pathlib import Path

from . import data
from .config import PLAYS_DIR

_open: dict | None = None                      # the play going on now
_done: list[dict] = []                         # finished, not written yet


def secs(duration) -> int:
    """ "3:45" or "1:02:03" in seconds (0 if it isn't one)."""
    n = 0
    for part in str(duration or "").split(":"):
        if not part.isdigit():
            return 0
        n = n * 60 + int(part)
    return n


def begin(track: dict):
    """A song started playing (it opened its stream)."""
    global _open
    finish()
    by = track.get("by") or ""
    _open = {"t": int(time.time()), "v": track["videoId"], "ti": track.get("title", ""), "ar": track.get("artist", ""),
             "al": track.get("album", ""), "th": track.get("thumb", ""), "ai": track.get("artistId", ""),
             "d": secs(track.get("duration")), "s": 0.0, "by": by, "sem": data.seminars_of(by),
             "src": track.get("src") or "user"}


def heard(vid: str, seconds: float):
    """The song playing now was audible for `seconds` more."""
    if _open and _open["v"] == vid:
        _open["s"] += seconds


def finish():
    """The song playing stopped, ended or was skipped: it goes into the log."""
    global _open
    if _open:
        _open["s"] = round(_open["s"])
        if _open["s"] >= 1:
            _done.append(_open)
        _open = None


def month_file(ts: float) -> Path:
    return PLAYS_DIR / (time.strftime("%Y-%m", time.localtime(ts)) + ".jsonl")


def flush():
    """Appends the finished plays to their month's file."""
    if not _done:
        return
    try:
        PLAYS_DIR.mkdir(parents=True, exist_ok=True)
        by_file: dict[Path, list[str]] = {}
        for p in _done:
            by_file.setdefault(month_file(p["t"]), []).append(json.dumps(p, ensure_ascii=False))
        for f, lines in by_file.items():
            with open(f, "a", encoding="utf-8") as out:
                out.write("\n".join(lines) + "\n")
        _done.clear()
    except OSError as exc:
        print(f"tunebox: cannot write the play log: {exc}", file=sys.stderr)


def read(since: float = 0, until: float | None = None) -> list[dict]:
    """Every play that started in [since, until), oldest first, including ones not written yet."""
    until = until or time.time() + 1
    out = []
    if PLAYS_DIR.exists():
        first, last = month_file(since).name if since else "", month_file(until).name
        for f in sorted(PLAYS_DIR.glob("*.jsonl")):
            if first <= f.name <= last:
                for line in f.read_text(encoding="utf-8").splitlines():
                    try:
                        p = json.loads(line)
                    except ValueError:
                        continue                  # a line cut short by a power cut
                    if since <= p.get("t", 0) < until:
                        out.append(p)
    out += [p for p in _done + ([{**_open, "s": round(_open["s"])}] if _open else []) if since <= p["t"] < until]
    return out


def seed():
    """First start with a play log: begin it with what the history and play counts remember."""
    if PLAYS_DIR.exists():
        return
    seen = set()
    for h in data.history:
        if h.get("videoId") and h.get("playedAt"):
            seen.add((h["videoId"], h["playedAt"] // 10))
            _done.append({"t": h["playedAt"], "v": h["videoId"], "ti": h.get("title", ""), "ar": h.get("artist", ""),
                          "al": h.get("album", ""), "th": h.get("thumb", ""), "ai": h.get("artistId", ""),
                          "d": secs(h.get("duration")), "s": secs(h.get("duration")), "by": h.get("by") or "",
                          "sem": data.seminars_of(h.get("by") or ""), "src": h.get("src") or "user"})
    for vid, st in data.stats.items():
        t = st.get("track") or {}
        for ts in st.get("plays", []):
            if (vid, ts // 10) not in seen:
                _done.append({"t": ts, "v": vid, "ti": t.get("title", ""), "ar": t.get("artist", ""),
                              "al": t.get("album", ""), "th": t.get("thumb", ""), "ai": t.get("artistId", ""),
                              "d": secs(t.get("duration")), "s": secs(t.get("duration")), "by": "", "sem": [], "src": "user"})
    _done.sort(key=lambda p: p["t"])
    PLAYS_DIR.mkdir(parents=True, exist_ok=True)
    flush()

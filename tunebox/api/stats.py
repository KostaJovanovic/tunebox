"""Stats and the recap, from the play log: for any period, for the house, one person or one seminar."""
import datetime
import time
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from .. import data, plays
from ..settings import settings

router = APIRouter()


def counted(p: dict) -> bool:
    """A play counts once 30 s were heard (or half of a shorter song)."""
    return p["s"] >= 30 or (p["d"] and p["s"] >= p["d"] / 2)


def track_of(p: dict) -> dict:
    return {"videoId": p["v"], "title": p["ti"], "artist": p["ar"], "album": p["al"], "thumb": p["th"], "artistId": p.get("ai", "")}


def summary(ps: list[dict], earlier: set[str], tz) -> dict:
    """Everything the Stats page and the recap show, for these plays (all counted ones)."""
    songs, artists = Counter(), Counter()
    song_min, artist_min = Counter(), Counter()
    artist_thumb, artist_id, first_track = {}, {}, {}
    hours, weekdays, days = [0.0] * 24, [0.0] * 7, Counter()
    months = Counter()
    for p in ps:
        m = p["s"] / 60
        songs[p["v"]] += 1
        song_min[p["v"]] += m
        first_track.setdefault(p["v"], p)
        for a in [x.strip() for x in (p["ar"] or "").split(",") if x.strip()][:1]:   # the main artist
            artists[a] += 1
            artist_min[a] += m
            artist_thumb.setdefault(a, p["th"])
            if p.get("ai"):
                artist_id.setdefault(a, p["ai"])
        when = datetime.datetime.fromtimestamp(p["t"], tz)
        hours[when.hour] += m
        weekdays[when.weekday()] += m
        days[when.date().isoformat()] += m
        months[when.strftime("%Y-%m")] += m
    new_songs = [v for v in songs if v not in earlier]
    streak = best = 0
    prev = None
    for d in sorted(days):
        day = datetime.date.fromisoformat(d)
        streak = streak + 1 if prev and (day - prev).days == 1 else 1
        best, prev = max(best, streak), day
    busiest = max(days.items(), key=lambda kv: kv[1]) if days else None
    return {
        "plays": len(ps), "minutes": round(sum(p["s"] for p in ps) / 60),
        "songs": len(songs), "artists": len(artists), "days": len(days), "newSongs": len(new_songs),
        "radioShare": round(100 * sum(1 for p in ps if p["src"] == "auto") / len(ps)) if ps else 0,
        "streak": best,
        "busiestDay": {"date": busiest[0], "minutes": round(busiest[1])} if busiest else None,
        "topSongs": [{**track_of(first_track[v]), "plays": n, "minutes": round(song_min[v])} for v, n in songs.most_common(10)],
        "topArtists": [{"name": a, "plays": n, "minutes": round(artist_min[a]), "thumb": artist_thumb[a], "id": artist_id.get(a, "")}
                       for a, n in artists.most_common(10)],
        "hours": [round(h) for h in hours], "weekdays": [round(w) for w in weekdays],
        "months": [{"month": k, "minutes": round(v)} for k, v in sorted(months.items())],
    }


@router.get("/api/stats")
async def stats(since: float = 0, until: float = 0, who: str = ""):
    """who: "" the house, a person's id, or "sem:<id>" for a seminar. since/until: Unix times."""
    until = until or time.time() + 1
    if who and not who.startswith("sem:") and who not in data.people:
        raise HTTPException(404, "No such person")
    try:
        tz = ZoneInfo(settings["alarm"].get("tz") or "UTC")
    except Exception:
        tz = datetime.timezone.utc
    everything = [p for p in plays.read(0, until) if counted(p)]

    def mine(p):
        if not who:
            return True
        return who[4:] in (p.get("sem") or []) if who.startswith("sem:") else p["by"] == who
    ps = [p for p in everything if p["t"] >= since and mine(p)]
    earlier = {p["v"] for p in everything if p["t"] < since and mine(p)}
    out = summary(ps, earlier, tz)
    people_min, sem_min = defaultdict(float), defaultdict(float)
    for p in (q for q in everything if q["t"] >= since):
        if p["by"] in data.people:
            people_min[p["by"]] += p["s"] / 60
        for s in p.get("sem") or []:
            if s in data.seminars:
                sem_min[s] += p["s"] / 60
    out["people"] = [{"id": k, "minutes": round(v)} for k, v in sorted(people_min.items(), key=lambda kv: -kv[1]) if round(v)]
    out["seminars"] = [{"id": k, "minutes": round(v)} for k, v in sorted(sem_min.items(), key=lambda kv: -kv[1]) if round(v)]
    out["first"] = min((p["t"] for p in everything), default=None)   # the log's first play, for "All time"
    return out

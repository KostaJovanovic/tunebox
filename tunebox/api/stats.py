"""Stats and the recap, from the play log: for any period, for the house, one person or one group.
Also a song's own numbers (its menu), the log as CSV, last week's digest and "On this day" (Home)."""
import csv
import datetime
import io
import time
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import admin, data, house, plays, wall
from ..plays import counted
from ..web import feature, need_feature

router = APIRouter(dependencies=[feature("stats", "recap")])


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


NIGHT = range(0, 5)                           # hours that make a Night owl
# the awards the house view hands out: key in a person's row, name, what it is for, what is counted
AWARDS = [("added", "The DJ", "added the most songs", "song"),
          ("again", "On repeat", "added the same song the most times", "time"),
          ("skips", "Itchy finger", "skipped the most songs", "skip"),
          ("cuts", "Can't wait", "cut the most songs short with Play now", "time"),
          ("skipped", "Tough crowd", "had the most songs skipped by others", "skip"),
          ("night", "Night owl", "had the most minutes after midnight", "minute"),
          ("artists", "Explorer", "added the most different artists", "artist")]


def fun(ps: list[dict], tz, shown) -> dict:
    """The fun numbers, per person, from every play in the period (skipped ones too, which Stats
    otherwise leaves out). shown(pid): whether that person is in view."""
    adds: dict[str, set] = defaultdict(set)
    again: dict[str, Counter] = defaultdict(Counter)
    artists: dict[str, set] = defaultdict(set)
    rows: dict[str, Counter] = defaultdict(Counter)
    first_track, skips, cuts = {}, 0, 0
    for p in ps:
        by, x, xb = p["by"], p.get("x"), p.get("xb") or ""
        if by and p["src"] == "user":
            add = (p["v"], p.get("a") or p["t"])      # older plays have no add time: each one was an add
            if add not in adds[by]:
                adds[by].add(add)
                again[by][p["v"]] += 1
                first_track.setdefault(p["v"], p)
            if x == "skip" and xb != by:
                rows[by]["skipped"] += 1
            if counted(p):
                if datetime.datetime.fromtimestamp(p["t"], tz).hour in NIGHT:
                    rows[by]["night"] += p["s"] / 60
                artists[by].update(a.strip() for a in (p["ar"] or "").split(",")[:1] if a.strip())
        if x and (shown(xb) or not xb and shown(None)):
            skips, cuts = skips + (x == "skip"), cuts + (x == "cut")
        if x and xb:
            rows[xb]["skips" if x == "skip" else "cuts"] += 1
            if x == "skip" and xb == by:
                rows[xb]["ownSkips"] += 1
    people = []
    for pid in set(rows) | set(adds):
        if pid not in data.people or not shown(pid):
            continue
        r = rows[pid]
        v, n = again[pid].most_common(1)[0] if again[pid] else ("", 0)
        people.append({"id": pid, "added": len(adds[pid]), "skips": r["skips"], "ownSkips": r["ownSkips"], "cuts": r["cuts"],
                       "skipped": r["skipped"], "night": round(r["night"]), "artists": len(artists[pid]),
                       "again": n if n > 1 else 0, "againTrack": track_of(first_track[v]) if n > 1 else None})
    people.sort(key=lambda r: (-r["added"], data.people[r["id"]]["name"].lower()))
    awards = []
    for key, title, what, unit in AWARDS:
        best = max((r[key] for r in people), default=0)
        if best:
            won = [r for r in people if r[key] == best]
            same = key == "again" and len({r["againTrack"]["videoId"] for r in won}) == 1   # a tie over two songs names none
            awards.append({"key": key, "title": title, "what": what, "unit": unit, "n": best, "ids": [r["id"] for r in won],
                           "track": won[0]["againTrack"] if same else None})
    return {"skips": skips, "cuts": cuts, "people": people, "awards": awards}


@router.get("/api/stats")
async def stats(request: Request, since: float = 0, until: float = 0, who: str = ""):
    """who: "" the house, a person's id, or "sem:<id>" for a group. since/until: Unix times."""
    until = until or time.time() + 1
    if who.startswith("sem:"):
        need_feature(request, "groups")
    elif who:
        need_feature(request, "people")
        if who not in data.people:
            raise HTTPException(404, "No such person")
    tz = house.tz()
    raw = plays.read(0, until)
    everything = [p for p in raw if counted(p)]

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
    is_admin = admin.is_admin(request, touch=False)
    if not (house.on("people") or is_admin):
        out["people"] = []
    if not (house.on("groups") or is_admin):
        out["seminars"] = []

    def shown(pid):                           # None: skips and cuts by nobody in particular
        if who.startswith("sem:"):
            return bool(pid) and who[4:] in data.seminars_of(pid)
        return pid == who if who else True
    out["fun"] = fun([p for p in raw if p["t"] >= since], tz, shown)
    if not (house.on("people") or is_admin):
        out["fun"].update(people=[], awards=[])
    elif who and not who.startswith("sem:"):
        out["fun"]["awards"] = []             # one person wins everything they are in
    out["first"] = min((p["t"] for p in everything), default=None)   # the log's first play, for "All time"
    out["wallAdds"] = wall.count(since, until) if not who else 0      # songs added on the wall: the house's, nobody's
    return out


# ---------- a song's own numbers, for its menu ----------
_log = {"at": 0.0, "plays": []}


def counted_log() -> list[dict]:
    """Every counted play, oldest first; read again at most every 30 s (a menu opens often)."""
    if time.time() - _log["at"] > 30:
        _log.update(at=time.time(), plays=[p for p in plays.read(0) if counted(p)])
    return _log["plays"]


@router.get("/api/stats/song/{video_id}")
async def song_stats(video_id: str, request: Request):
    ps = [p for p in counted_log() if p["v"] == video_id]
    if not ps:
        return {"plays": 0}
    adders = Counter(p["by"] for p in ps if p["src"] == "user" and p["by"] in data.people)
    top = adders.most_common(1)[0][0] if adders and (house.on("people") or admin.is_admin(request, touch=False)) else ""
    return {"plays": len(ps), "first": ps[0]["t"], "last": ps[-1]["t"], "by": top, "radio": sum(1 for p in ps if p["src"] == "auto")}


# ---------- the play log as CSV, for a period and whoever Stats shows ----------
@router.get("/api/stats/export.csv")
async def export_csv(request: Request, since: float = 0, until: float = 0, who: str = ""):
    tz, until = house.tz(), until or time.time() + 1
    names = house.on("people") or admin.is_admin(request, touch=False)

    def mine(p):
        if not who:
            return True
        return who[4:] in (p.get("sem") or []) if who.startswith("sem:") else p["by"] == who
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time", "title", "artist", "album", "seconds heard", "length", "added by", "from", "ended"])
    for p in plays.read(since, until):
        if not mine(p):
            continue
        by = (data.people.get(p["by"]) or {}).get("name", "") if names else ""
        w.writerow([datetime.datetime.fromtimestamp(p["t"], tz).strftime("%Y-%m-%d %H:%M"), p["ti"], p["ar"], p["al"],
                    round(p["s"]), p["d"] or "", by, "radio" if p["src"] == "auto" else "added", p.get("x") or "played"])
    day = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",   # the BOM: Excel reads the accents right
                    headers={"Content-Disposition": f'attachment; filename="tunebox-plays-{day}.csv"'})


# ---------- last week, for the card on Home ----------
def week_bounds(tz) -> tuple[float, float]:
    """Monday 00:00 of last week and of this week, by the house's clock."""
    now = datetime.datetime.now(tz)
    this = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (this - datetime.timedelta(days=7)).timestamp(), this.timestamp()


@router.get("/api/digest")
async def digest(request: Request):
    tz = house.tz()
    since, until = week_bounds(tz)
    log = counted_log()
    ps = [p for p in log if since <= p["t"] < until]
    if not ps:
        return {"since": since, "plays": 0}
    before = {p["v"] for p in log if p["t"] < since}
    songs = Counter(p["v"] for p in ps)
    first = {}
    for p in ps:
        first.setdefault(p["v"], p)
    new = [v for v, _ in songs.most_common() if v not in before]
    by_min = Counter()
    for p in ps:
        if p["src"] == "user" and p["by"] in data.people:
            by_min[p["by"]] += p["s"] / 60
    top_v, n = songs.most_common(1)[0]
    new = [v for v in new if v != top_v]       # the top song isn't also the new find
    out = {"since": since, "until": until, "plays": len(ps), "minutes": round(sum(p["s"] for p in ps) / 60),
           "song": {**track_of(first[top_v]), "plays": n},
           "found": {**track_of(first[new[0]]), "plays": songs[new[0]]} if new else None, "person": None}
    if by_min and (house.on("people") or admin.is_admin(request, touch=False)):
        pid, m = by_min.most_common(1)[0]
        out["person"] = {"id": pid, "minutes": round(m)}
    return out


# ---------- On this day: what played on this date a year ago (or a month ago), for Home ----------
def on_this_day() -> dict | None:
    tz = house.tz()
    now = datetime.datetime.now(tz)
    for months, label in ((12, "A year ago today"), (1, "A month ago today")):
        y, m = now.year, now.month - months
        while m < 1:
            m, y = m + 12, y - 1
        try:
            day = now.replace(year=y, month=m, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:                    # the 31st, in a shorter month
            continue
        start = day.timestamp()
        ps = [p for p in counted_log() if start <= p["t"] < start + 86400]
        songs = Counter(p["v"] for p in ps)
        if len(songs) >= 3:
            first = {}
            for p in ps:
                first.setdefault(p["v"], p)
            return {"key": "onthisday", "title": "On this day", "subtitle": f"{label}, {day.day} {day.strftime('%B %Y')}",
                    "items": [track_of(first[v]) for v, _ in songs.most_common(30)]}
    return None

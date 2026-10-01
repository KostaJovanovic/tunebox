"""Finding music: search, YouTube Music's home and explore pages, albums, playlists, artists,
pasted links, and the house's own "For you" shelves."""
import asyncio
import random
import re
import urllib.parse

from fastapi import APIRouter, HTTPException, Request

from .. import admin, blocklist, data, house, local, youtube
from .stats import on_this_day
from ..config import LIKED_ID, STATS_DAYS
from ..web import feature
from ..youtube import album_card, cached, radio_for, thumb_of, track_from, yt_get

router = APIRouter()


@router.get("/api/search")
async def search(q: str, request: Request, kind: str = "songs"):
    """Songs: the house's own local songs that match come first."""
    if not q.strip():
        return []
    filt = kind if kind in ("songs", "albums", "artists", "playlists") else "songs"
    mine = [{"type": "song", **t} for t in local.search(q)] if filt == "songs" and (house.on("local") or admin.is_admin(request, touch=False)) else []
    try:
        res = await yt_get("search", youtube.yt.search, q, filter=filt, limit=30)
    except HTTPException:
        if not mine:
            raise
        res = []                              # YouTube can't be reached: the local songs are still there
    out = mine
    for r in res:
        if filt == "songs":
            t = track_from(r)
            if t:
                out.append({"type": "song", **t})
        elif filt == "albums":
            out.append({"type": "album", "id": r.get("browseId"), "title": r.get("title"),
                        "subtitle": ", ".join(a["name"] for a in r.get("artists") or []) + (f" · {r['year']}" if r.get("year") else ""),
                        "thumb": thumb_of(r)})
        elif filt == "artists":
            out.append({"type": "artist", "id": r.get("browseId"), "title": r.get("artist"),
                        "subtitle": "Artist", "thumb": thumb_of(r)})
        else:
            out.append({"type": "playlist", "id": r.get("browseId"), "title": r.get("title"),
                        "subtitle": r.get("author") or "Playlist", "thumb": thumb_of(r)})
    return [o for o in out if o.get("videoId") or o.get("id")]


@router.get("/api/home", dependencies=[feature("browse")])
async def home():
    shelves = await yt_get("home page", youtube.yt.get_home, limit=6)
    out = []
    for shelf in shelves:
        items = []
        for c in shelf.get("contents", []):
            thumb = thumb_of(c)
            if c.get("videoId"):
                t = track_from(c)
                items.append({"type": "song", **t})
            elif c.get("playlistId") or (c.get("browseId") or "").startswith(("VL", "RD", "PL")):
                items.append({"type": "playlist", "id": c.get("playlistId") or c.get("browseId"),
                              "title": c.get("title"), "subtitle": c.get("description") or "", "thumb": thumb})
            elif (c.get("browseId") or "").startswith("MPRE"):
                items.append({"type": "album", "id": c["browseId"], "title": c.get("title"),
                              "subtitle": c.get("year") or "", "thumb": thumb})
        if items:
            out.append({"title": shelf.get("title"), "items": items[:12]})
    return out


@router.get("/api/album/{browse_id}")
async def album(browse_id: str):
    a = await yt_get("album", youtube.yt.get_album, browse_id)
    thumbs = a.get("thumbnails") or []
    tracks = [t for t in (track_from({**x, "album": {"name": a.get("title"), "id": browse_id},
                                      "thumbnails": x.get("thumbnails") or thumbs})
                          for x in a.get("tracks", [])) if t]
    artists = a.get("artists") or []
    return {"title": a.get("title"), "subtitle": ", ".join(x["name"] for x in artists),
            "artistId": next((x["id"] for x in artists if (x.get("id") or "").startswith("UC")), ""),
            "thumb": thumb_of(a), "tracks": tracks}


@router.get("/api/playlist/{playlist_id}")
async def playlist(playlist_id: str):
    pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
    if pid.startswith("RD") and not pid.startswith("RDCLAK"):      # a radio mix; RDCLAK are curated playlists
        w = await yt_get("mix", youtube.yt.get_watch_playlist, playlistId=pid, limit=50)
        tracks = [t for t in map(track_from, w.get("tracks", [])) if t]
        return {"title": "Mix", "subtitle": "YouTube Music mix", "thumb": tracks[0]["thumb"] if tracks else "", "tracks": tracks}
    p = await yt_get("playlist", youtube.yt.get_playlist, pid, limit=100)
    tracks = [t for t in map(track_from, p.get("tracks", [])) if t]
    return {"title": p.get("title"), "subtitle": (p.get("author") or {}).get("name", "") if isinstance(p.get("author"), dict) else "",
            "thumb": thumb_of(p), "tracks": tracks}


@router.get("/api/artist/{channel_id}")
async def artist(channel_id: str):
    a = await yt_get("artist", youtube.yt.get_artist, channel_id)
    songs = [t for t in map(track_from, (a.get("songs") or {}).get("results", [])) if t]
    albums = [{"type": "album", "id": x.get("browseId"), "title": x.get("title"), "subtitle": x.get("year") or "",
               "thumb": thumb_of(x)}
              for x in (a.get("albums") or {}).get("results", [])]
    return {"title": a.get("name"), "subtitle": "Artist", "thumb": thumb_of(a),
            "tracks": songs, "albums": albums}

_where: dict[str, dict] = {}


@router.get("/api/where/{video_id}")
async def where(video_id: str):
    """A song's artist and album pages, for songs saved before tracks carried them (history, playlists)."""
    if local.is_local(video_id):
        return {"artistId": "", "albumId": ""}
    if video_id not in _where:
        w = await yt_get("song", youtube.yt.get_watch_playlist, video_id, limit=1)
        t = track_from((w.get("tracks") or [{}])[0]) or {}
        if len(_where) >= 2000:               # the oldest lookups go first (dicts keep their order)
            del _where[next(iter(_where))]
        _where[video_id] = {"artistId": t.get("artistId", ""), "albumId": t.get("albumId", "")}
    return _where[video_id]


# ---------- links, explore, moods ----------
YT_ID = re.compile(r"[\w-]{2,80}")


@router.get("/api/resolve", dependencies=[feature("links")])
async def resolve(url: str):
    """A pasted YouTube / YouTube Music link: which album, playlist, artist or song it points to."""
    raw = url.strip()
    try:
        u = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    except ValueError:
        raise HTTPException(400, "That isn't a link")
    host = (u.hostname or "").lower()
    if host not in ("youtu.be", "youtube.com") and not host.endswith(".youtube.com"):
        raise HTTPException(400, "Only YouTube and YouTube Music links work here")
    qs = urllib.parse.parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    vid = (qs.get("v") or [None])[0]
    if host == "youtu.be" and parts:
        vid = parts[0]
    elif len(parts) > 1 and parts[0] in ("shorts", "live", "embed"):
        vid = parts[1]
    lst = (qs.get("list") or [None])[0]
    kind, ident = None, None
    if len(parts) > 1 and parts[0] in ("browse", "channel"):
        b = parts[1]
        kind, ident = ("album", b) if b.startswith("MPRE") else ("artist", b) if b.startswith("UC") else ("playlist", b)
    elif lst and (not vid or parts[:1] == ["playlist"]):
        kind, ident = "playlist", lst
    elif lst and (not lst.startswith("RD") or lst.startswith("RDCLAK")):   # a song played from a playlist or album
        kind, ident = "playlist", lst                          # (RD… on a song link is just its radio: the song wins)
    elif vid:
        kind, ident = "song", vid
    if not kind or not YT_ID.fullmatch(ident or ""):
        raise HTTPException(400, "That link doesn't point to a song, album, playlist or artist")
    if kind == "playlist" and ident.startswith("OLAK5uy_"):   # an album's playlist: open the album itself
        try:
            ident = await asyncio.to_thread(youtube.yt.get_album_browse_id, ident) or ident
        except Exception:
            pass
        if ident.startswith("MPRE"):
            kind = "album"
    if kind != "song":
        return {"type": kind, "id": ident}
    try:
        w = await asyncio.to_thread(youtube.yt.get_watch_playlist, ident, limit=1)
        t = track_from((w.get("tracks") or [{}])[0])
    except Exception:
        t = None
    if not t:
        raise HTTPException(404, "Couldn't find that song")
    return {"type": "song", "track": t}


@router.get("/api/explore", dependencies=[feature("browse")])
async def explore():
    """New releases (albums) and the moods & genres to browse."""
    async def fetch():
        ex, moods = await asyncio.gather(yt_get("explore page", youtube.yt.get_explore),
                                         yt_get("list of moods", youtube.yt.get_mood_categories))
        releases = [album_card(x) for x in ex.get("new_releases") or [] if x.get("browseId")]
        groups = [{"title": k, "items": [{"title": m["title"], "params": m["params"]} for m in v if m.get("params")]}
                  for k, v in moods.items()]
        return {"releases": releases, "moods": [g for g in groups if g["items"]]}
    return await cached("explore", fetch)


@router.get("/api/mood", dependencies=[feature("browse")])
async def mood(params: str):
    if not re.fullmatch(r"[\w=%-]{4,200}", params):
        raise HTTPException(400, "bad mood")

    async def fetch():
        pls = await yt_get("mood", youtube.yt.get_mood_playlists, params)
        def sub(p):
            a = p.get("author")
            return ", ".join(x.get("name", "") for x in a) if isinstance(a, list) else p.get("description") or ""
        return [{"type": "playlist", "id": p["playlistId"], "title": p.get("title"), "subtitle": sub(p),
                 "thumb": thumb_of(p)}
                for p in pls[:60] if p.get("playlistId")]
    return await cached("mood:" + params, fetch)


# ---------- for you: shelves from what the house plays and likes ----------
@router.get("/api/forme", dependencies=[feature("browse")])
async def for_me(request: Request):
    most = [t for _, t in data.most_played(24)]
    likes = [{**{k: t.get(k, "") for k in data.TRACK_KEYS}, "likedBy": t.get("likedBy") or []}
             for t in data.playlists[LIKED_ID]["tracks"]]
    random.shuffle(likes)
    shelves = []
    if most:
        shelves.append({"key": "most", "title": "Most played", "subtitle": f"The house, last {STATS_DAYS} days", "items": most})
    if house.on("stats") or admin.is_admin(request, touch=False):
        day = await asyncio.to_thread(on_this_day)
        if day:
            day["items"] = [t for t in day["items"] if not blocklist.blocked(t)]
            shelves.append(day)
    if likes and (house.on("likes") or admin.is_admin(request, touch=False)):
        shelves.append({"key": "likedmix", "title": "Liked mix", "subtitle": "Everyone's likes, shuffled", "items": likes[:30]})
    seeds = [t["videoId"] for t in most[:5]] or [t["videoId"] for t in likes[:5]]
    seed = random.choice(seeds) if seeds else None
    # Recommended: YouTube Music's radio of a song played lately (not the House mix's seed), less what the
    # house already plays a lot, so there is always a row of songs to discover even when YouTube's own
    # home (not signed in) has only playlists and albums
    recent = [h for h in data.history[:15] if h.get("videoId") and h["videoId"] != seed and not local.is_local(h["videoId"])]
    pick = random.choice(recent) if recent else None
    mix, recs = await asyncio.gather(cached("housemix:" + seed, lambda: radio_for(seed, 40)) if seed else asyncio.sleep(0, []),
                                     cached("recs:" + pick["videoId"], lambda: radio_for(pick["videoId"], 40)) if pick else asyncio.sleep(0, []))
    if mix:
        shelves.append({"key": "housemix", "title": "House mix", "subtitle": "New songs like the ones you play", "items": mix[:30]})
    known = {t["videoId"] for t in most} | {t["videoId"] for t in (mix or [])[:30]}
    recs = [t for t in recs or [] if t["videoId"] not in known]
    if len(recs) >= 5:
        shelves.append({"key": "recs", "title": "Recommended", "subtitle": f'Because you played {pick["title"]}', "items": recs[:30]})
    return shelves


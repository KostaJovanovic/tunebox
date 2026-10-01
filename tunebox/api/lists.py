"""History, Tunebox playlists (one shared set for the whole house), Liked songs and Top 30.

Everyone sees every playlist and may add, remove and reorder its songs. Renaming or deleting one is
for whoever made it (its owner) and the admin; a playlist with no owner is the house's."""
import asyncio
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import admin, audit, blocklist, data
from ..config import HISTORY_MAX, LIKED_ID, STATS_DAYS, TOP_ID, TOP_SIZE
from ..data import clean_track, list_summary, playlists, save_lists, sorted_lists
from ..player import player
from ..settings import save_settings, settings
from .. import house
from ..web import BaseModel, feature, need_feature, who

router = APIRouter()
lists_lock = asyncio.Lock()


@router.get("/api/history")
async def get_history(limit: int = 100):
    return data.history[:max(1, min(limit, HISTORY_MAX))]


@router.delete("/api/history", dependencies=[Depends(admin.need)])
async def clear_history(request: Request):
    data.clear_history()
    audit.log("history", "Cleared the history", request)
    return {"ok": True}


def may_manage(p: dict, request: Request) -> bool:
    """Renaming and deleting: the playlist's owner, or the admin."""
    return bool(p.get("owner") and p["owner"] == who(request)) or admin.is_admin(request)


def top_list() -> dict:
    """Top 30: the house's most played songs of the last STATS_DAYS days, made fresh on every read.
    Each track carries its play count; nobody edits it."""
    now = int(time.time())
    tracks = [{**t, "plays": n} for n, t in data.most_played(TOP_SIZE * 2) if not blocklist.blocked(t)][:TOP_SIZE]
    return {"id": TOP_ID, "name": f"Top {TOP_SIZE}", "tracks": tracks, "created": now, "updated": now, "owner": "",
            "auto": True, "days": STATS_DAYS}


def get_list(list_id: str, request: Request) -> dict:
    """The playlist, if its feature is on (Liked songs belongs to likes, the rest to playlists)."""
    need_feature(request, "likes" if list_id == LIKED_ID else "playlists")
    if list_id == TOP_ID:
        raise HTTPException(400, f"Top {TOP_SIZE} makes itself from what plays here")
    if list_id not in playlists:
        raise HTTPException(404, "No such playlist")
    return playlists[list_id]


class ListBody(BaseModel):
    name: str | None = None
    tracks: list[dict] | None = None
    fromQueue: bool = False


class ListTrackBody(BaseModel):
    track: dict


class LikeBody(BaseModel):
    track: dict
    liked: bool


class ListEditBody(BaseModel):
    op: str                                   # "move" or "remove"
    videoId: str
    at: int | None = None                     # where the client saw it (tells duplicates apart)
    to: int | None = None                     # move: the new position


@router.get("/api/lists")
async def all_lists(request: Request):
    is_admin = admin.is_admin(request, touch=False)
    ls = [p for p in sorted_lists() if is_admin or house.on("likes" if p["id"] == LIKED_ID else "playlists")]
    top = top_list()
    if top["tracks"] and (is_admin or house.on("playlists")):
        ls.insert(1 if ls and ls[0]["id"] == LIKED_ID else 0, top)   # next to Liked songs
    return [list_summary(p) for p in ls]


@router.post("/api/lists", dependencies=[feature("playlists")])
async def create_list(body: ListBody, request: Request):
    name = (body.name or "").strip()[:80] or "New playlist"
    src = player.queue[max(player.index, 0):] if body.fromQueue else (body.tracks or [])
    async with lists_lock:
        pid = secrets.token_hex(4)
        now = int(time.time())
        playlists[pid] = {"id": pid, "name": name, "tracks": [t for t in map(clean_track, src) if t],
                          "created": now, "updated": now, "owner": who(request)}
        save_lists()
    return playlists[pid]


@router.get("/api/lists/{list_id}")
async def one_list(list_id: str, request: Request):
    if list_id == TOP_ID:
        need_feature(request, "playlists")
        return top_list()
    return get_list(list_id, request)


@router.patch("/api/lists/{list_id}")
async def edit_list(list_id: str, body: ListBody, request: Request):
    async with lists_lock:
        p = get_list(list_id, request)
        name = (body.name or "").strip()[:80]
        if name and name != p["name"] and list_id != LIKED_ID:
            if not may_manage(p, request):
                raise HTTPException(403, "Only its owner or the admin can rename it")
            p["name"] = name
        if body.tracks is not None:
            liked_by = {t["videoId"]: t["likedBy"] for t in p["tracks"] if t.get("likedBy")}   # who liked what stays
            p["tracks"] = [{**t, "likedBy": liked_by[t["videoId"]]} if t["videoId"] in liked_by else t
                           for t in map(clean_track, body.tracks) if t]
        p["updated"] = int(time.time())
        save_lists()
    return p


@router.patch("/api/lists/{list_id}/tracks")
async def edit_list_tracks(list_id: str, body: ListEditBody, request: Request):
    """Moves or removes one song by videoId, so edits from two devices don't undo each other."""
    async with lists_lock:
        p = get_list(list_id, request)
        ts = p["tracks"]
        i = body.at
        if i is None or not 0 <= i < len(ts) or ts[i]["videoId"] != body.videoId:
            i = next((k for k, t in enumerate(ts) if t["videoId"] == body.videoId), None)
        if i is None:
            raise HTTPException(404, "That song is no longer in the playlist")
        if body.op == "remove":
            ts.pop(i)
        elif body.op == "move" and body.to is not None:
            ts.insert(max(0, min(len(ts) - 1, body.to)), ts.pop(i))
        else:
            raise HTTPException(400, "unknown op")
        p["updated"] = int(time.time())
        save_lists()
    return p


@router.post("/api/lists/{list_id}/tracks")
async def add_to_list(list_id: str, body: ListTrackBody, request: Request):
    t = clean_track(body.track)
    if not t:
        raise HTTPException(400, "not a track")
    async with lists_lock:
        p = get_list(list_id, request)
        dup = any(x["videoId"] == t["videoId"] for x in p["tracks"])
        if not dup:
            p["tracks"].insert(0 if list_id == LIKED_ID else len(p["tracks"]), t)   # newest like first
            p["updated"] = int(time.time())
            save_lists()
    return {"ok": True, "duplicate": dup, "count": len(p["tracks"])}


@router.post("/api/like", dependencies=[feature("likes")])
async def like(body: LikeBody, request: Request):
    """Adds the song to the top of Liked songs, or takes it out. The list is shared; likedBy
    remembers who liked each song (liking an already liked song adds your name)."""
    t = clean_track(body.track)
    if not t:
        raise HTTPException(400, "not a track")
    by = who(request)
    async with lists_lock:
        p = playlists[LIKED_ID]
        have = next((x for x in p["tracks"] if x["videoId"] == t["videoId"]), None)
        if body.liked and have is None:
            p["tracks"].insert(0, {**t, "likedBy": [by] if by else []})
        elif body.liked and by and by not in have.setdefault("likedBy", []):
            have["likedBy"].append(by)
        elif not body.liked and have is not None:
            p["tracks"] = [x for x in p["tracks"] if x["videoId"] != t["videoId"]]
        else:
            return {"liked": body.liked, "count": len(p["tracks"])}
        p["updated"] = int(time.time())
        save_lists()
    return {"liked": body.liked, "count": len(p["tracks"])}


@router.delete("/api/lists/{list_id}")
async def delete_list(list_id: str, request: Request):
    if list_id == LIKED_ID:
        raise HTTPException(400, "Liked songs can't be deleted")
    async with lists_lock:
        if not may_manage(get_list(list_id, request), request):
            raise HTTPException(403, "Only its owner or the admin can delete it")
        del playlists[list_id]
        save_lists()
        if settings["alarm"].get("list") == list_id:
            settings["alarm"]["list"] = None
            save_settings()
    return {"ok": True}


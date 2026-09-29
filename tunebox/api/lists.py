"""History, Tunebox playlists (one shared set for the whole house) and Liked songs."""
import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, Request

from .. import auth, data
from ..config import HISTORY_MAX, LIKED_ID
from ..data import clean_track, list_summary, playlists, save_lists, sorted_lists
from ..player import player
from ..settings import save_settings, settings
from ..web import BaseModel, who

router = APIRouter()
lists_lock = asyncio.Lock()


@router.get("/api/history")
async def get_history(limit: int = 100):
    return data.history[:max(1, min(limit, HISTORY_MAX))]


class AdminBody(BaseModel):
    admin: str | None = None


@router.delete("/api/history")
async def clear_history(body: AdminBody | None = None):
    await auth.need_admin(body and body.admin)
    data.clear_history()
    return {"ok": True}


def get_list(list_id: str) -> dict:
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
async def all_lists():
    return [list_summary(p) for p in sorted_lists()]


@router.post("/api/lists")
async def create_list(body: ListBody):
    name = (body.name or "").strip()[:80] or "New playlist"
    src = player.queue[max(player.index, 0):] if body.fromQueue else (body.tracks or [])
    async with lists_lock:
        pid = secrets.token_hex(4)
        now = int(time.time())
        playlists[pid] = {"id": pid, "name": name, "tracks": [t for t in map(clean_track, src) if t],
                          "created": now, "updated": now}
        save_lists()
    return playlists[pid]


@router.get("/api/lists/{list_id}")
async def one_list(list_id: str):
    return get_list(list_id)


@router.patch("/api/lists/{list_id}")
async def edit_list(list_id: str, body: ListBody):
    async with lists_lock:
        p = get_list(list_id)
        if body.name is not None and body.name.strip() and list_id != LIKED_ID:
            p["name"] = body.name.strip()[:80]
        if body.tracks is not None:
            p["tracks"] = [t for t in map(clean_track, body.tracks) if t]
        p["updated"] = int(time.time())
        save_lists()
    return p


@router.patch("/api/lists/{list_id}/tracks")
async def edit_list_tracks(list_id: str, body: ListEditBody):
    """Moves or removes one song by videoId, so edits from two devices don't undo each other."""
    async with lists_lock:
        p = get_list(list_id)
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
async def add_to_list(list_id: str, body: ListTrackBody):
    t = clean_track(body.track)
    if not t:
        raise HTTPException(400, "not a track")
    async with lists_lock:
        p = get_list(list_id)
        dup = any(x["videoId"] == t["videoId"] for x in p["tracks"])
        if not dup:
            p["tracks"].insert(0 if list_id == LIKED_ID else len(p["tracks"]), t)   # newest like first
            p["updated"] = int(time.time())
            save_lists()
    return {"ok": True, "duplicate": dup, "count": len(p["tracks"])}


@router.post("/api/like")
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
async def delete_list(list_id: str):
    if list_id == LIKED_ID:
        raise HTTPException(400, "Liked songs can't be deleted")
    async with lists_lock:
        get_list(list_id)
        del playlists[list_id]
        save_lists()
        if settings["alarm"].get("list") == list_id:
            settings["alarm"]["list"] = None
            save_settings()
    return {"ok": True}


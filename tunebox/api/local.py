"""Local songs: uploading, listing, changing and removing them, their covers, and the admin's limits
on the room they take (local.py does the work).

An upload is the file itself as the request body (application/octet-stream, its name in ?name=), one
request per file: nothing large is held in memory, and no multipart parser is needed."""
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import admin, audit, data, house, local
from ..config import HISTORY_FILE
from ..files import write_json
from ..player import player
from ..web import BaseModel, feature, need_feature, need_who, who
from .lists import lists_lock

router = APIRouter()
LOCAL = [feature("local")]
ADMIN = [Depends(admin.need)]
DRAIN_MAX = 64 * local.MB


async def refuse(request: Request, exc: HTTPException):
    """Refuses an upload whose body hasn't been read. The rest of it is read and dropped first (up to
    DRAIN_MAX), so the answer reaches the sender: closing the connection on a browser that is still
    sending shows there as a network error, not as this message."""
    n = 0
    async for chunk in request.stream():
        n += len(chunk)
        if n > DRAIN_MAX:
            break
    raise exc


def may_edit(request: Request, s: dict, touch: bool = True) -> bool:
    """Whoever uploaded it, and the admin. A song uploaded with names switched off is the house's."""
    return admin.is_admin(request, touch=touch) or (bool(s.get("by")) and who(request) == s["by"])


def view(s: dict, request: Request) -> dict:
    return {**local.track(s), "by": s.get("by", ""), "at": s["at"], "size": s["size"], "ext": s["ext"], "was": s.get("was", s["ext"]),
            "mine": may_edit(request, s, touch=False)}


def get_song(sid: str) -> dict:
    if sid not in local.songs:
        raise HTTPException(404, "No such local song")
    return local.songs[sid]


def everywhere(vid: str, fn) -> int:
    """Runs fn(list, index) on every copy of a song: up next, earlier queues, playlists and likes,
    history. fn changes or deletes it; how many copies there were."""
    n = 0
    spots = [player.queue, data.history] + [s["queue"] for s in player.undo] + [l["tracks"] for l in data.playlists.values()]
    for tracks in spots:
        for i in range(len(tracks) - 1, -1, -1):
            if tracks[i].get("videoId") == vid and not (tracks is player.queue and i == player.index and fn is drop):
                fn(tracks, i)
                n += 1
    return n


def drop(tracks: list, i: int):
    if tracks is player.queue and i < player.index:
        player.index -= 1
    del tracks[i]


def saved_everywhere():
    data.save_lists()
    write_json(HISTORY_FILE, data.history)
    player.save_session()


@router.get("/api/local", dependencies=LOCAL)
async def all_local(request: Request):
    """Newest first, with how much more fits."""
    newest = sorted(reversed(list(local.songs.values())), key=lambda s: -s["at"])   # added in the same second: the later one first
    return {"songs": [view(s, request) for s in newest],
            "maxMB": house.house["local"]["maxMB"], "room": local.room(), "used": local.used()}


@router.post("/api/local/upload")
async def upload(request: Request, name: str = ""):
    try:
        need_feature(request, "local")
        by = need_who(request)
    except HTTPException as exc:
        await refuse(request, exc)
    max_mb = house.house["local"]["maxMB"]
    limit, room = max_mb * local.MB, local.room()
    too_big, full = HTTPException(413, f"Too big: a file can be {max_mb} MB at most"), HTTPException(413, "There is no room left for local songs")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > limit or declared > room:
        await refuse(request, too_big if declared > limit else full)
    local.INCOMING.mkdir(parents=True, exist_ok=True)
    part = local.INCOMING / f"{secrets.token_hex(8)}.part"
    size, sha = 0, hashlib.sha256()
    try:
        with part.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit or size > room:   # it said it was smaller, or didn't say
                    await refuse(request, too_big if size > limit else full)
                sha.update(chunk)
                f.write(chunk)
        if not size:
            raise HTTPException(400, "That file is empty")
        digest = sha.hexdigest()
        if any(s.get("sha") == digest for s in local.songs.values()):
            raise HTTPException(409, "Already here")
        try:
            s = await local.add_file(part, name, digest, by)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        part.unlink(missing_ok=True)          # a refused or broken upload leaves nothing behind
    return view(s, request)


@router.get("/api/local/{sid}/cover")
async def cover(sid: str):
    """Open even with local songs switched off: songs already in playlists and the history keep their covers."""
    c = local.cover_of(sid)
    if not c:
        raise HTTPException(404, "No cover")
    return FileResponse(c[0], media_type=c[1], headers={"Cache-Control": "public, max-age=31536000, immutable"})   # ?v= changes with the cover


class EditBody(BaseModel):
    title: str | None = None
    artist: str | None = None
    album: str | None = None


def owned(sid: str, request: Request) -> dict:
    s = get_song(sid)
    if not may_edit(request, s):
        raise HTTPException(403, "Only whoever uploaded this song, or the admin, can change it")
    return s


def refresh(s: dict):
    """The song changed: every copy of it follows."""
    t = local.track(s)

    def put(tracks, i):
        tracks[i].update(t)
    everywhere(t["videoId"], put)
    if player.seed and player.seed.get("videoId") == t["videoId"]:
        player.seed.update({k: t[k] for k in ("title", "artist", "thumb")})
    if t["videoId"] in data.stats:
        data.stats[t["videoId"]]["track"] = t
    saved_everywhere()


@router.patch("/api/local/{sid}", dependencies=LOCAL)
async def edit(sid: str, body: EditBody, request: Request):
    async with lists_lock:
        s = owned(sid, request)
        for k in ("title", "artist", "album"):
            v = getattr(body, k)
            if v is not None:
                s[k] = " ".join(v.split())[:300]
        if not s["title"]:
            raise HTTPException(400, "A song needs a title")
        local.save()
        refresh(s)
    return view(s, request)


@router.post("/api/local/{sid}/cover")
async def set_cover(sid: str, request: Request):
    """The picture itself as the body (image/jpeg, image/png or image/webp)."""
    try:
        need_feature(request, "local")
        owned(sid, request)
    except HTTPException as exc:
        await refuse(request, exc)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > local.COVER_MAX:
            await refuse(request, HTTPException(413, "That picture is too big (5 MB at most)"))
    async with lists_lock:
        s = owned(sid, request)
        if not local.put_cover(s, body):
            raise HTTPException(400, "That isn't a picture (JPEG, PNG or WebP)")
        local.save()
        refresh(s)
    return view(s, request)


@router.delete("/api/local/{sid}", dependencies=LOCAL)
async def delete(sid: str, request: Request):
    """The file goes, and the song leaves up next, the playlists, the likes and the history. The play log
    keeps what was heard."""
    async with lists_lock:
        s = owned(sid, request)
        vid = local.PREFIX + sid
        if player.current and player.current["videoId"] == vid:
            if player.index + 1 < len(player.queue):
                await player.play_index(step=1)       # mpv lets go of the file
            else:
                await player.stop()
        everywhere(vid, drop)
        data.stats.pop(vid, None)
        await player.sync_armed()
        local.remove(sid)
        saved_everywhere()
    if admin.is_admin(request, touch=False) and not (s.get("by") and who(request) == s["by"]):
        audit.log("local.delete", f'Removed the local song "{s["title"]}"', request)
    return {"ok": True}


# ---------- the admin: room and limits ----------
class LimitsBody(BaseModel):
    capGB: float | None = None                # how much local songs may take; -1: no cap
    reserveGB: float | None = None            # free space to always leave on the disk
    maxMB: int | None = None                  # the biggest file


async def space() -> dict:
    return {**local.disk(), **house.house["local"], "room": local.room(), "encoders": await local.mpv_caps()}


@router.get("/api/admin/local/disk", dependencies=ADMIN)
async def disk():
    return await space()


@router.patch("/api/admin/local/limits", dependencies=ADMIN)
async def limits(body: LimitsBody, request: Request):
    lim = house.house["local"]
    if body.capGB is not None:
        lim["capGB"] = None if body.capGB < 0 else round(min(body.capGB, 100000), 2)
    if body.reserveGB is not None:
        lim["reserveGB"] = round(max(0, min(body.reserveGB, 100000)), 2)
    if body.maxMB is not None:
        lim["maxMB"] = max(1, min(body.maxMB, 4096))
    house.save_house()
    cap = "no cap" if lim["capGB"] is None else f'{lim["capGB"]:g} GB'
    audit.log("local.limits", f'Local songs: {cap}, {lim["reserveGB"]:g} GB kept free, files up to {lim["maxMB"]} MB', request)
    return await space()

"""Playing and the queue: what's on (/api/state), adding songs, the transport buttons, queue edits and undo."""
import asyncio
import random

from fastapi import APIRouter, HTTPException, Request

from .. import admin, blocklist, house
from ..data import clean_track, people
from ..player import player
from ..settings import save_settings_soon, settings
from ..web import BaseModel, need_feature, need_who, who

router = APIRouter()


@router.get("/api/state")
async def state(request: Request):
    # looking only: this is polled every second and must not keep an admin session alive
    return {**player.state(), "admin": admin.is_admin(request, touch=False), "houseRev": house.rev}


class PlayBody(BaseModel):
    tracks: list[dict]
    start: int = 0
    mode: str = "replace"                     # add | next | now | replace (see Player.add / Player.replace)
    label: str | None = None                  # what was added, for the undo list ("Album name")


class QueueBody(BaseModel):                   # older pages; new ones use /api/play with a mode
    track: dict
    next: bool = False


class ControlBody(BaseModel):
    action: str
    value: float | None = None
    videoId: str | None = None                # jump/remove/move: the track the client saw at `value`
    to: int | None = None                     # move: its new queue index
    id: str | None = None                     # restore: the snapshot


def queue_at(i: int, vid: str | None) -> int:
    """The queue index a client meant; 409 when the queue moved under it."""
    if not 0 <= i < len(player.queue) or (vid is not None and player.queue[i]["videoId"] != vid):
        raise HTTPException(409, "The queue changed, try again")
    return i


def nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def may_add(by: str, n: int, replacing: bool = False):
    """The admin can stop a person adding songs, or limit how many of theirs wait at once."""
    p = people.get(by) or {}
    if p.get("noAdd"):
        raise HTTPException(403, "You can't add songs right now")
    cap = p.get("cap")
    if cap:
        start = player.index + 1
        waiting = 0 if replacing else sum(1 for t in player.queue[start:player.user_end()] if t.get("by") == by)
        if waiting + n - replacing > cap:     # replacing: the first of them plays now
            raise HTTPException(403, f"You can have {cap} song{'s' if cap != 1 else ''} waiting" +
                                (f", and {waiting} of yours {'is' if waiting == 1 else 'are'} already" if waiting else ""))


@router.post("/api/play")
async def play(body: PlayBody, request: Request):
    by = need_who(request)
    tracks = [t for t in map(clean_track, body.tracks) if t]
    if not tracks:
        raise HTTPException(400, "no tracks")
    first = tracks[max(0, min(body.start, len(tracks) - 1))]
    allowed = [t for t in tracks if not blocklist.blocked(t)]
    if not allowed:
        raise HTTPException(403, "That song is blocked here" if len(tracks) == 1 else "Those songs are blocked here")
    start = allowed.index(first) if first in allowed else 0      # a blocked song in a list is left out
    skipped, tracks = len(tracks) - len(allowed), allowed
    may_add(by, len(tracks), body.mode == "replace")
    label = (body.label or "").strip()[:60]
    if body.mode in ("add", "next", "now"):
        pos = await player.add(tracks, by, body.mode, f'Added "{label}"' if label else "")
        msg = ("Playing now" if pos == 0 else "Plays next" if pos == 1 or body.mode == "next" else f"Added · {nth(pos)} in queue")
        return {"ok": True, "position": pos, "message": msg + left_out(skipped)}
    if body.mode != "replace":
        raise HTTPException(400, "unknown mode")
    asyncio.get_running_loop().create_task(player.replace(tracks, start, by, f'Played "{label}"' if label else ""))
    return {"ok": True, "message": (f'Playing "{label}"' if label else "Playing") + left_out(skipped)}


def left_out(n: int) -> str:
    return f" · {n} blocked song{'s' if n != 1 else ''} left out" if n else ""


@router.post("/api/queue")
async def enqueue(body: QueueBody, request: Request):
    by = need_who(request)
    track = clean_track(body.track)
    if not track:
        raise HTTPException(400, "not a track")
    if blocklist.blocked(track):
        raise HTTPException(403, "That song is blocked here")
    may_add(by, 1)
    pos = await player.add([track], by, "next" if body.next else "add")
    return {"ok": True, "position": pos}


@router.get("/api/queue/history")
async def queue_history():
    """Earlier queues (undo snapshots), newest first."""
    return [{"id": s["id"], "label": s["label"], "by": s["by"], "at": s["at"], "count": len(s["queue"]),
             "current": s["queue"][0]["title"] if s["queue"] else "", "thumb": s["queue"][0]["thumb"] if s["queue"] else ""}
            for s in reversed(player.undo)]


@router.post("/api/control")
async def control(body: ControlBody, request: Request):
    a, v, by = body.action, body.value, who(request)
    p = player
    msg = ""
    if a == "toggle":
        if p.mpv.props.get("idle-active") and p.current:
            asyncio.get_running_loop().create_task(p.play_index(p.index, p.resume_at))
        else:
            asyncio.get_running_loop().create_task(p.fade_toggle())
    elif a == "next":
        asyncio.get_running_loop().create_task(p.play_index(step=1))
    elif a == "prev":
        if (p.mpv.props.get("time-pos") or 0) > 5 or p.index == 0:
            await p.mpv.send("seek", 0, "absolute")
        else:
            asyncio.get_running_loop().create_task(p.play_index(step=-1))
    elif a == "seek" and v is not None:
        await p.mpv.send("seek", v, "absolute")
    elif a == "volume" and v is not None:
        settings["volume"] = round(max(0, min(100, v)))
        if p.ramp:                            # touching the volume ends an alarm ramp
            p.ramp, p.fade_db = None, 0.0
        await p.apply_volume()
        save_settings_soon()
    elif a == "jump" and v is not None:
        i = queue_at(int(v), body.videoId)
        asyncio.get_running_loop().create_task(p.play_index(i, vid=body.videoId))
    elif a == "remove" and v is not None:
        i = queue_at(int(v), body.videoId)
        if p.index < i < len(p.queue):
            p.snapshot(f'Removed "{p.queue[i]["title"]}"', by)
            p.queue.pop(i)
            msg = "Removed"
    elif a in ("move", "promote") and v is not None:
        # move: to a new place (dropped among the added songs it counts as added, among the radio as radio);
        # promote: a song to the front of the added songs ("play next", from the queue itself)
        i = queue_at(int(v), body.videoId)
        if i <= p.index:
            raise HTTPException(400, "Only songs that are up next can be moved")
        t = p.queue[i]
        p.snapshot(f'Moved "{t["title"]}"', by)
        p.queue.pop(i)
        to = p.index + 1 if a == "promote" else max(p.index + 1, min(int(body.to if body.to is not None else i), len(p.queue)))
        if to <= p.user_end():
            if t.get("src") != "user":
                t.update(src="user", by=by)
        else:
            t["src"] = "auto"
        p.queue.insert(to, t)
        msg = "Plays next" if a == "promote" else ""
    elif a == "shuffle":                      # the songs people added; the radio stays after them
        end = p.user_end()
        rest = p.queue[p.index + 1:end]
        if len(rest) > 1:
            p.snapshot("Shuffled up next", by)
            random.shuffle(rest)
            p.queue[p.index + 1:end] = rest
            msg = "Shuffled"
    elif a == "clear":                        # the songs people added; the radio keeps going
        end = p.user_end()
        if end > p.index + 1:
            p.snapshot("Cleared up next", by)
            del p.queue[p.index + 1:end]
            msg = "Cleared"
    elif a == "clear_auto":
        end = p.user_end()
        if end < len(p.queue):
            p.snapshot("Cleared the radio", by)
            del p.queue[end:]
            p.seed, p.seed_gen = None, p.seed_gen + 1
            msg = "Radio cleared"
    elif a == "refresh":
        need_feature(request, "radio")
        seed = p.seed or p.current
        if seed:
            p.snapshot("New radio songs", by)
            p.reseed(seed, fill=False)
            await p._reseed(p.seed_gen, fresh=True)
            msg = "New radio songs"
    elif a == "stop":
        if p.current:
            p.snapshot("Stopped", by)
        await p.stop()
    elif a == "undo":
        if not p.undo:
            raise HTTPException(400, "Nothing to undo")
        snap = p.undo.pop()
        await p.restore(snap)
        msg = f"Undone: {snap['label']}"
    elif a == "restore":
        snap = next((s for s in p.undo if s["id"] == body.id), None)
        if not snap:
            raise HTTPException(404, "That queue is gone")
        p.snapshot("Before restoring an earlier queue", by)
        await p.restore(snap)
        msg = "Restored"
    else:
        raise HTTPException(400, "unknown action")
    await p.sync_armed()
    return {"ok": True, "message": msg}

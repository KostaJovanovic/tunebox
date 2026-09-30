"""The admin's routes: unlocking and the password (admin.py), the audit log, and everything about
people: their details and pass phrases, what they played, liked and made, merging and removing them."""
import time
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import admin, audit, auth, data, house, plays
from ..config import HISTORY_FILE, LIKED_ID
from ..data import list_summary, people, playlists, save_lists, save_people
from ..files import write_json
from ..player import player
from ..settings import save_settings, settings
from ..web import BaseModel
from .lists import lists_lock
from .people import PersonBody, new_person, people_lock, person_fields, set_phrase

router = APIRouter()
ADMIN = [Depends(admin.need)]


# ---------- unlocking, the password, the audit log ----------
class LoginBody(BaseModel):
    password: str | None = None
    create: bool = False                      # no password set yet: this one becomes it


class PasswordBody(BaseModel):
    old: str | None = None
    new: str


@router.get("/api/admin")
async def admin_state(request: Request):
    return {"set": auth.admin_set(), "admin": admin.is_admin(request, touch=False), "lockedFor": admin.locked_for(),
            "signups": house.house["signups"]}


@router.post("/api/admin/login")
async def login(body: LoginBody, request: Request, response: Response):
    await admin.login(request, response, body.password, body.create)
    return {"ok": True}


@router.post("/api/admin/logout")
async def logout(request: Request, response: Response):
    if admin.is_admin(request, touch=False):
        audit.log("logout", "Admin locked", request)
    admin.logout(request, response)
    return {"ok": True}


@router.post("/api/admin/password", dependencies=ADMIN)
async def password(body: PasswordBody, request: Request, response: Response):
    await admin.change_password(request, response, body.old, body.new)
    return {"ok": True}


@router.post("/api/admin/reset")
async def reset(request: Request):
    admin.reset(request)
    return {"ok": True}


@router.get("/api/admin/audit", dependencies=ADMIN)
async def audit_log(limit: int = 300):
    return audit.entries[-max(1, min(limit, 300)):][::-1]


class SignupsBody(BaseModel):
    open: bool


@router.patch("/api/admin/signups", dependencies=ADMIN)
async def signups(body: SignupsBody, request: Request):
    house.house["signups"] = "open" if body.open else "closed"
    house.save_house()
    audit.log("signups", "Anyone can add a name" if body.open else "Only the admin adds names", request)
    return {"signups": house.house["signups"]}


# ---------- people ----------
class AdminPersonBody(PersonBody):
    noAdd: bool | None = None                 # can't add songs
    cap: int | None = None                    # at most this many songs waiting; 0: no limit


class MergeBody(BaseModel):
    source: str                               # this person goes away...
    into: str                                 # ...and everything of theirs becomes this person's


class UnlikeBody(BaseModel):
    videoId: str | None = None
    all: bool = False


class PlaysBody(BaseModel):
    who: str | None = None
    plays: list[dict] | None = None           # [{"t": started, "v": videoId}, ...]
    all: bool = False                         # every play of `who`


def name_of(pid: str) -> str:
    return people[pid]["name"] if pid in people else "someone removed"


def get_person(pid: str) -> dict:
    if pid not in people:
        raise HTTPException(404, "No such person")
    return people[pid]


def listening() -> dict[str, dict]:
    """What each person played, from one pass over the play log."""
    out: dict[str, dict] = {}
    for p in plays.read(0):
        if p["by"] and plays.counted(p):
            s = out.setdefault(p["by"], {"plays": 0, "secs": 0, "last": 0, "songs": Counter(), "track": {}})
            s["plays"] += 1
            s["secs"] += p["s"]
            s["last"] = max(s["last"], p["t"])
            s["songs"][p["v"]] += 1
            s["track"][p["v"]] = p
    return out


def admin_view(p: dict, heard: dict | None) -> dict:
    h = heard or {"plays": 0, "secs": 0, "last": 0, "songs": Counter(), "track": {}}
    liked = sum(1 for t in playlists[LIKED_ID]["tracks"] if p["id"] in (t.get("likedBy") or []))
    return {**{k: v for k, v in p.items() if k not in ("phrase", "kv")}, "locked": bool(p.get("phrase")),
            "plays": h["plays"], "minutes": round(h["secs"] / 60), "last": h["last"],
            "top": [{"title": h["track"][v]["ti"], "artist": h["track"][v]["ar"], "plays": n} for v, n in h["songs"].most_common(3)],
            "lists": sum(1 for l in playlists.values() if l.get("owner") == p["id"]), "likes": liked}


def admin_fields(p: dict, body: AdminPersonBody):
    person_fields(p, body)
    set_phrase(p, body.phrase)
    if body.noAdd is not None:
        p["noAdd"] = body.noAdd
        if not p["noAdd"]:
            del p["noAdd"]
    if body.cap is not None:
        p["cap"] = max(0, min(body.cap, 999))
        if not p["cap"]:
            del p["cap"]


@router.get("/api/admin/people", dependencies=ADMIN)
async def all_people():
    heard = listening()
    return sorted((admin_view(p, heard.get(p["id"])) for p in people.values()), key=lambda p: p["name"].lower())


@router.post("/api/admin/people", dependencies=ADMIN)
async def add_person(body: AdminPersonBody, request: Request):
    async with people_lock:
        p = new_person(body)
        admin_fields(p, AdminPersonBody(noAdd=body.noAdd, cap=body.cap))
        save_people()
    audit.log("person.add", f'Added {p["name"]}', request)
    return admin_view(p, None)


@router.post("/api/admin/people/merge", dependencies=ADMIN)
async def merge(body: MergeBody, request: Request):
    a, b = body.source, body.into
    if a == b:
        raise HTTPException(400, "Pick two different people")
    async with people_lock, lists_lock:
        pa, pb = get_person(a), get_person(b)
        n = plays.rewrite(lambda p: {**p, "by": b} if p["by"] == a else p)
        rename(a, b)
        for t in playlists[LIKED_ID]["tracks"]:
            if a in (t.get("likedBy") or []):
                t["likedBy"] = [x for x in t["likedBy"] if x != a] + ([] if b in t["likedBy"] else [b])
        for l in playlists.values():
            if l.get("owner") == a:
                l["owner"] = b
        pb["seminars"] = pb.get("seminars", []) + [s for s in pa.get("seminars", []) if s not in pb.get("seminars", [])]
        del people[a]
        save_lists()
        save_people()
    audit.log("person.merge", f'Merged {pa["name"]} into {pb["name"]} ({n} plays)', request)
    return {"ok": True, "plays": n}


@router.patch("/api/admin/people/{pid}", dependencies=ADMIN)
async def edit_person(pid: str, body: AdminPersonBody, request: Request):
    """Anyone, a name with a pass phrase too. The admin's device gets no key for that name."""
    async with people_lock:
        p = get_person(pid)
        admin_fields(p, body)
        save_people()
    what = ("pass phrase removed" if body.phrase == "" else "pass phrase set" if body.phrase
            else "blocked from adding songs" if body.noAdd else "changed")
    audit.log("person.edit", f'{p["name"]}: {what}', request)
    return admin_view(p, listening().get(pid))


@router.post("/api/admin/people/{pid}/signout", dependencies=ADMIN)
async def sign_out(pid: str, request: Request):
    """Every device that typed this name's pass phrase has to type it again."""
    async with people_lock:
        p = get_person(pid)
        if not p.get("phrase"):
            raise HTTPException(400, "That name has no pass phrase, so no device is signed in to it")
        p["kv"] = p.get("kv", 0) + 1
        save_people()
    audit.log("person.signout", f'Signed every device out of {p["name"]}', request)
    return {"ok": True}


def rename(pid: str, to: str):
    """Songs up next, earlier queues and the history that say `pid` added them say `to` instead."""
    for t in player.queue:
        if t.get("by") == pid:
            t["by"] = to
    for s in player.undo:
        if s.get("by") == pid:
            s["by"] = to
        for t in s["queue"]:
            if t.get("by") == pid:
                t["by"] = to
    if any(h.get("by") == pid for h in data.history):
        for h in data.history:
            if h.get("by") == pid:
                h["by"] = to
        write_json(HISTORY_FILE, data.history)
    player.save_session()


def drop_list(list_id: str):
    del playlists[list_id]
    if settings["alarm"].get("list") == list_id:
        settings["alarm"]["list"] = None
        save_settings()


@router.delete("/api/admin/people/{pid}", dependencies=ADMIN)
async def remove_person(pid: str, request: Request, mode: str = "keep"):
    """keep: their songs, plays and likes stay, with no name on them, and their playlists become the
    house's. purge: their plays, likes and playlists go too."""
    if mode not in ("keep", "purge"):
        raise HTTPException(400, "unknown mode")
    async with people_lock, lists_lock:
        p = get_person(pid)
        n = 0
        if mode == "purge":
            n = plays.rewrite(lambda q: None if q["by"] == pid else q)
            liked = playlists[LIKED_ID]
            for t in liked["tracks"]:
                if pid in (t.get("likedBy") or []):
                    t["likedBy"] = [x for x in t["likedBy"] if x != pid] or None
            liked["tracks"] = [t for t in liked["tracks"] if t.get("likedBy", []) is not None]
            for l in [l for l in playlists.values() if l.get("owner") == pid]:
                drop_list(l["id"])
            rename(pid, "")
        else:
            for l in playlists.values():
                if l.get("owner") == pid:
                    l["owner"] = ""
        del people[pid]
        save_lists()
        save_people()
    audit.log("person.delete", f'Removed {p["name"]}' + (f" with {n} plays, their likes and playlists" if mode == "purge" else ""), request)
    return {"ok": True}


@router.get("/api/admin/people/{pid}/detail", dependencies=ADMIN)
async def detail(pid: str):
    get_person(pid)
    return {"lists": [list_summary(l) for l in data.sorted_lists() if l.get("owner") == pid],
            "likes": [{k: t.get(k, "") for k in ("videoId", "title", "artist", "thumb")}
                      for t in playlists[LIKED_ID]["tracks"] if pid in (t.get("likedBy") or [])]}


@router.post("/api/admin/people/{pid}/unlike", dependencies=ADMIN)
async def unlike(pid: str, body: UnlikeBody, request: Request):
    """Takes their name off one liked song, or all of them; a song nobody else liked leaves Liked songs."""
    async with lists_lock:
        p, liked, n = get_person(pid), playlists[LIKED_ID], 0
        keep = []
        for t in liked["tracks"]:
            if pid in (t.get("likedBy") or []) and (body.all or t["videoId"] == body.videoId):
                n += 1
                t["likedBy"] = [x for x in t["likedBy"] if x != pid]
                if not t["likedBy"]:
                    continue
            keep.append(t)
        if n:
            liked["tracks"], liked["updated"] = keep, int(time.time())
            save_lists()
    if n:
        audit.log("likes.delete", f'Removed {n} of {p["name"]}\'s likes', request)
    return {"removed": n}


# ---------- the play log ----------
@router.get("/api/admin/plays", dependencies=ADMIN)
async def get_plays(who: str = "", before: float = 0, limit: int = 100):
    """Newest first; who: a person's id, or "" for everything that played."""
    ps = [p for p in plays.read(0, before or None) if not who or p["by"] == who]
    return ps[::-1][:max(1, min(limit, 500))]


@router.delete("/api/admin/plays", dependencies=ADMIN)
async def delete_plays(body: PlaysBody, request: Request):
    if body.all:
        if not body.who:
            raise HTTPException(400, "Whose plays?")
        n = plays.rewrite(lambda p: None if p["by"] == body.who else p)
        audit.log("plays.delete", f"Removed all {n} plays of {name_of(body.who)}", request)
    else:
        gone = {(int(x.get("t", 0)), str(x.get("v", ""))) for x in body.plays or []}
        n = plays.rewrite(lambda p: None if (p["t"], p["v"]) in gone else p)
        if n:
            audit.log("plays.delete", f"Removed {n} play{'s' if n != 1 else ''} from the log", request)
    return {"removed": n}

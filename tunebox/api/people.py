"""People: who's listening, picked per device (cookie tb_who), so the queue can show who added what;
their groups; pass phrases for names (optional, see auth.py). The admin's side of it is in api/admin.py."""
import asyncio
import re
import secrets

from fastapi import APIRouter, HTTPException, Request, Response

from .. import admin, auth, data, house
from ..data import people, save_people
from ..web import BaseModel, need_feature

router = APIRouter()
people_lock = asyncio.Lock()
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


class PersonBody(BaseModel):
    name: str | None = None
    color: str | None = None
    emoji: str | None = None
    seminars: list[str] | None = None         # groups, by id or name; an unknown name adds that group (if the house lets people)
    phrase: str | None = None                 # a new pass phrase; "" takes it off


def person_fields(p: dict, body: PersonBody, may_create: bool = False) -> None:
    """may_create: an unknown group name makes that group (the admin always may; others by the house's rule)."""
    if body.name is not None:
        name = " ".join(body.name.split())[:24]
        if not name:
            raise HTTPException(400, "Type a name")
        if any(q["name"].lower() == name.lower() and q["id"] != p.get("id") for q in people.values()):
            raise HTTPException(409, "That name is taken")
        p["name"] = name
    if body.color is not None:
        if not COLOR_RE.fullmatch(body.color):
            raise HTTPException(400, "bad colour")
        p["color"] = body.color.upper()
    if body.emoji is not None:
        e = body.emoji.strip()[:8]
        if any(ch.isascii() and ch not in "#*0123456789" for ch in e):   # emoji only (keycaps start with #, * or a digit)
            raise HTTPException(400, "Pick an emoji")
        p["emoji"] = e
    if body.seminars is not None:
        p["seminars"] = pick_seminars(body.seminars, may_create)


def pick_seminars(names: list[str], may_create: bool) -> list[str]:
    """The groups a person is in: known ones by id or name, a new one by its name. The house says
    whether everyone needs one, and what it calls them."""
    g, out = house.house["groups"], []
    for n in names[:12]:
        n = " ".join(str(n).split())[:24]
        if not n:
            continue
        sid = data.find_seminar(n)
        if sid is None:
            if not may_create:
                raise HTTPException(400, f'Pick a {g["one"].lower()} from the list')
            sid = data.add_seminar(n)["id"]
        if sid not in out:
            out.append(sid)
    if not out and g["required"] and house.on("groups"):
        raise HTTPException(400, f'Pick your {g["one"].lower()}')
    return out


def may_create(request: Request) -> bool:
    return house.house["groups"]["create"] == "open" or admin.is_admin(request, touch=False)


@router.get("/api/people")
async def all_people(request: Request):
    return sorted((auth.public(p, request) for p in people.values()), key=lambda p: p["name"].lower())


@router.get("/api/seminars")
async def all_seminars():
    return sorted(data.seminars.values(), key=lambda s: s["name"].lower())


def set_phrase(p: dict, phrase: str | None):
    """None: unchanged; "": none any more; else the new one (every other device must type it again)."""
    if phrase is not None:
        p["phrase"] = auth.hash_phrase(auth.clean_phrase(phrase)) if phrase else None
        if not p["phrase"]:
            del p["phrase"]


def new_person(body: PersonBody, may_create: bool = False) -> dict:
    """Makes the person and adds them; the caller holds people_lock and saves."""
    p = {"id": secrets.token_hex(4), "name": "", "color": "#1F5FBF", "emoji": "", "seminars": []}
    start = [s for s in house.house["newPerson"]["groups"] if s in data.seminars]   # the house's groups for someone who picks none
    person_fields(p, PersonBody(name=body.name or "", color=body.color, emoji=body.emoji,
                                seminars=body.seminars or start), may_create)
    set_phrase(p, body.phrase or None)
    people[p["id"]] = p
    return p


@router.post("/api/people")
async def add_person(body: PersonBody, request: Request, response: Response):
    need_feature(request, "people")
    if house.house["signups"] != "open" and not admin.is_admin(request):
        raise HTTPException(403, "New names are added by the admin here")
    async with people_lock:
        p = new_person(body, may_create(request))
        save_people()
    auth.give_key(response, p["id"])
    return {**auth.public(p, request), "mine": True}


@router.patch("/api/people/{pid}")
async def edit_person(pid: str, body: PersonBody, request: Request, response: Response):
    async with people_lock:
        if pid not in people:
            raise HTTPException(404, "No such person")
        if not auth.holds_key(request, pid):
            raise HTTPException(403, "Only they can change it: that name has a pass phrase")
        person_fields(people[pid], body, may_create(request))
        set_phrase(people[pid], body.phrase)
        save_people()
    auth.give_key(response, pid)
    return {**auth.public(people[pid], request), "mine": True}


class PhraseBody(BaseModel):
    phrase: str | None = None


@router.post("/api/people/{pid}/unlock")
async def unlock(pid: str, body: PhraseBody, response: Response):
    """This device knows the name's pass phrase: it may use the name from now on."""
    if pid not in people:
        raise HTTPException(404, "No such person")
    if not await auth.matches(body.phrase, people[pid].get("phrase")):
        raise HTTPException(403, "Wrong pass phrase")
    auth.give_key(response, pid)
    return {"ok": True}



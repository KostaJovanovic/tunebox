"""People: who's listening, picked per device (cookie tb_who), so the queue can show who added what."""
import asyncio
import re
import secrets

from fastapi import APIRouter, HTTPException

from ..data import people, save_people
from ..web import BaseModel

router = APIRouter()
people_lock = asyncio.Lock()
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


class PersonBody(BaseModel):
    name: str | None = None
    color: str | None = None
    emoji: str | None = None


def person_fields(p: dict, body: PersonBody) -> None:
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


@router.get("/api/people")
async def all_people():
    return sorted(people.values(), key=lambda p: p["name"].lower())


@router.post("/api/people")
async def add_person(body: PersonBody):
    async with people_lock:
        p = {"id": secrets.token_hex(4), "name": "", "color": "#1F5FBF", "emoji": ""}
        person_fields(p, PersonBody(name=body.name or "", color=body.color, emoji=body.emoji))
        people[p["id"]] = p
        save_people()
    return p


@router.patch("/api/people/{pid}")
async def edit_person(pid: str, body: PersonBody):
    async with people_lock:
        if pid not in people:
            raise HTTPException(404, "No such person")
        person_fields(people[pid], body)
        save_people()
    return people[pid]


@router.delete("/api/people/{pid}")
async def remove_person(pid: str):
    """Their songs stay where they are; they just show no name any more."""
    async with people_lock:
        people.pop(pid, None)
        save_people()
    return {"ok": True}


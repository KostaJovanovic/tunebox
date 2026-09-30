"""The house's setup (house.py): what every page reads, and the admin's routes to change it: name,
accent and time zone, the feature switches and their presets, groups, the wall screen, the blocklist."""
import json
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import admin, audit, blocklist, data, house
from ..data import clean_track, people, save_people
from ..player import player
from ..web import BaseModel
from .people import people_lock

router = APIRouter()
ADMIN = [Depends(admin.need)]
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


@router.get("/api/house")
async def get_house():
    return house.public()


@router.get("/api/admin/house", dependencies=ADMIN)
async def get_setup():
    """The same, with what the admin's panel offers: every feature, the presets, the accents."""
    return {**house.public(), "features": list(house.FEATURES), "presets": house.PRESETS, "accents": list(house.ACCENTS)}


def saved(request: Request, ev: str, msg: str) -> dict:
    house.save_house()
    audit.log(ev, msg, request)
    return house.public()


# ---------- name, accent, time zone, groups' rules, wall ----------
class HouseBody(BaseModel):
    name: str | None = None
    accent: str | None = None
    tz: str | None = None                     # "": the server's own time
    signups: str | None = None
    groups: dict | None = None                # one, many, required, create
    newPerson: dict | None = None             # groups: [ids]
    wall: dict | None = None                  # lyrics, queue, who, clock, controls


def word(v, fallback: str) -> str:
    return " ".join(str(v or "").split())[:24] or fallback


@router.patch("/api/admin/house", dependencies=ADMIN)
async def set_house(body: HouseBody, request: Request):
    h, what = house.house, []
    if body.name is not None:
        h["name"] = word(body.name, "Tunebox")
        what.append(f'name "{h["name"]}"')
    if body.accent is not None:
        if body.accent not in house.ACCENTS:
            raise HTTPException(400, "unknown accent")
        h["accent"] = body.accent
        what.append("accent")
    if body.tz is not None:
        if body.tz:
            try:
                ZoneInfo(body.tz)
            except Exception:
                raise HTTPException(400, "unknown time zone")
        h["tz"] = body.tz
        what.append("time zone " + (body.tz or "the server's"))
    if body.signups is not None:
        if body.signups not in ("open", "closed"):
            raise HTTPException(400, "signups: open or closed")
        h["signups"] = body.signups
        what.append("anyone can add a name" if body.signups == "open" else "only the admin adds names")
    if body.groups is not None:
        g = h["groups"]
        if "one" in body.groups:
            g["one"] = word(body.groups["one"], g["one"])
        if "many" in body.groups:
            g["many"] = word(body.groups["many"], g["many"])
        if "required" in body.groups:
            g["required"] = bool(body.groups["required"])
        if body.groups.get("create") in ("open", "admin"):
            g["create"] = body.groups["create"]
        what.append(f'groups are "{g["many"]}"')
    if body.newPerson is not None:
        h["newPerson"]["groups"] = [s for s in body.newPerson.get("groups") or [] if s in data.seminars][:12]
        what.append("a new person's groups")
    if body.wall is not None:
        h["wall"].update({k: bool(v) for k, v in body.wall.items() if k in h["wall"]})
        what.append("the wall screen")
    return saved(request, "house", "House: " + ", ".join(what or ["nothing"]))


# ---------- features ----------
class FeaturesBody(BaseModel):
    features: dict[str, bool]


class PresetBody(BaseModel):
    name: str


class SetupBody(BaseModel):
    setup: dict


@router.patch("/api/admin/features", dependencies=ADMIN)
async def set_features(body: FeaturesBody, request: Request):
    changed = {k: bool(v) for k, v in body.features.items() if k in house.FEATURES and house.on(k) != bool(v)}
    house.house["features"].update(changed)
    msg = ", ".join(f"{house.label(k)} {'on' if v else 'off'}" for k, v in changed.items()) or "nothing"
    return saved(request, "features", "Switched " + msg)


@router.post("/api/admin/features/preset", dependencies=ADMIN)
async def preset(body: PresetBody, request: Request):
    off = house.PRESETS.get(body.name)
    if off is None:
        raise HTTPException(404, "No such preset")
    house.house["features"].update({k: k not in off for k in house.FEATURES})
    return saved(request, "features", f"Preset: {body.name}")


@router.get("/api/admin/features/export", dependencies=ADMIN)
async def export_setup():
    """The house's setup as a file, to load into another Tunebox."""
    h = house.house
    setup = {"tunebox_setup": 1, "name": h["name"], "accent": h["accent"], "features": h["features"],
             "groups": h["groups"], "wall": h["wall"], "signups": h["signups"]}
    return Response(json.dumps(setup, indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="tunebox-setup.json"'})


@router.post("/api/admin/features/import", dependencies=ADMIN)
async def import_setup(body: SetupBody, request: Request):
    s = body.setup
    if s.get("tunebox_setup") != 1:
        raise HTTPException(400, "That isn't a Tunebox setup file")
    new = house.merged({k: s[k] for k in ("name", "accent", "features", "groups", "wall", "signups") if k in s})
    new["features"] = {k: bool(new["features"].get(k, True)) for k in house.FEATURES}
    if new["accent"] not in house.ACCENTS or new["signups"] not in ("open", "closed"):
        raise HTTPException(400, "That setup file has a value this Tunebox doesn't know")
    for k in ("name", "accent", "features", "groups", "wall", "signups"):
        house.house[k] = new[k]
    return saved(request, "features", "Loaded a setup file")


# ---------- groups ----------
class GroupBody(BaseModel):
    name: str | None = None
    color: str | None = None


def group_fields(g: dict, body: GroupBody):
    if body.name is not None:
        name = " ".join(body.name.split())[:24]
        if not name:
            raise HTTPException(400, "Type a name")
        if any(x["name"].lower() == name.lower() and x["id"] != g.get("id") for x in data.seminars.values()):
            raise HTTPException(409, "That name is taken")
        g["name"] = name
    if body.color is not None:
        if not COLOR_RE.fullmatch(body.color):
            raise HTTPException(400, "bad colour")
        g["color"] = body.color.upper()


@router.post("/api/admin/groups", dependencies=ADMIN)
async def add_group(body: GroupBody, request: Request):
    async with people_lock:
        probe: dict = {}
        group_fields(probe, GroupBody(name=body.name or "", color=body.color))   # refuses a bad or taken name
        g = data.add_seminar(probe["name"])
        g.update(probe)
        data.save_seminars()
    audit.log("group", f'Added the group {g["name"]}', request)
    return g


@router.patch("/api/admin/groups/{gid}", dependencies=ADMIN)
async def edit_group(gid: str, body: GroupBody, request: Request):
    async with people_lock:
        if gid not in data.seminars:
            raise HTTPException(404, "No such group")
        group_fields(data.seminars[gid], body)
        data.save_seminars()
    audit.log("group", f'Changed the group {data.seminars[gid]["name"]}', request)
    return data.seminars[gid]


@router.delete("/api/admin/groups/{gid}", dependencies=ADMIN)
async def delete_group(gid: str, request: Request):
    """Its people stay, without it. What they played while in it keeps the old group, which Stats no longer shows."""
    async with people_lock:
        g = data.seminars.pop(gid, None)
        if not g:
            raise HTTPException(404, "No such group")
        for p in people.values():
            if gid in (p.get("seminars") or []):
                p["seminars"] = [s for s in p["seminars"] if s != gid]
        nw = house.house["newPerson"]
        if gid in nw["groups"]:
            nw["groups"] = [s for s in nw["groups"] if s != gid]
            house.save_house()
        data.save_seminars()
        save_people()
    audit.log("group", f'Removed the group {g["name"]}', request)
    return {"ok": True}


# ---------- the blocklist ----------
class BlockBody(BaseModel):
    kind: str                                 # "song" or "artist"
    track: dict | None = None                 # song: the song; artist: a song of theirs (its first artist is blocked)
    name: str | None = None                   # artist: the name, when there is no song to take it from


@router.get("/api/admin/blocks", dependencies=ADMIN)
async def get_blocks():
    b = blocklist.blocks
    return {"songs": [{"id": k, **v} for k, v in sorted(b["songs"].items(), key=lambda kv: -kv[1].get("at", 0))],
            "artists": [{"key": k, **v} for k, v in sorted(b["artists"].items(), key=lambda kv: -kv[1].get("at", 0))]}


@router.post("/api/admin/blocks", dependencies=ADMIN)
async def add_block(body: BlockBody, request: Request):
    t = clean_track(body.track) if body.track else None
    if body.kind == "song":
        if not t:
            raise HTTPException(400, "not a track")
        blocklist.add_song(t)
        what = f'the song "{t["title"]}"'
    elif body.kind == "artist":
        name = " ".join((body.name or (t and t["artist"].split(",")[0]) or "").split())[:100]
        if not name:
            raise HTTPException(400, "Which artist?")
        blocklist.add_artist(name, t["artistId"] if t and not body.name else "")
        what = f"the artist {name}"
    else:
        raise HTTPException(400, "kind: song or artist")
    n = await player.drop_blocked(f"Blocked {what}")
    audit.log("block", f"Blocked {what}", request)
    return {"ok": True, "removed": n, "message": f"Blocked {what}" + (f" · {n} taken out of up next" if n else "")}


@router.delete("/api/admin/blocks/{kind}/{key:path}", dependencies=ADMIN)
async def remove_block(kind: str, key: str, request: Request):
    was = blocklist.blocks.get(kind, {}).get(key)
    if not blocklist.remove(kind, key):
        raise HTTPException(404, "That isn't blocked")
    audit.log("block", f'Unblocked {was.get("title") or was.get("name") or key}', request)
    return {"ok": True}

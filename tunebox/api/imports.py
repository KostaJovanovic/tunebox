"""Importing playlists from a file (tunebox/importer.py does the work). Anyone who may make playlists
may import; saving goes through the playlists' own routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .. import importer
from ..web import BaseModel, feature, who

router = APIRouter(dependencies=[feature("playlists")])


class ImportBody(BaseModel):
    text: str = Field(max_length=2_000_000)
    name: str = ""


def _job(jid: str) -> dict:
    if jid not in importer.jobs:
        raise HTTPException(404, "That import is gone (the server restarted, or it was a day old)")
    return importer.jobs[jid]


@router.post("/api/import")
async def start(body: ImportBody, request: Request):
    owner = who(request)
    if any(j["owner"] == owner and j["status"] == "running" for j in importer.jobs.values()):
        raise HTTPException(409, "You have an import running already: wait for it, or cancel it")
    rows = importer.parse(body.text)
    if not rows:
        raise HTTPException(400, "Found no songs in that file")
    name = body.name.strip()[:80] or (rows[0]["playlist"] if len({r["playlist"] for r in rows}) == 1 else "") or "Imported playlist"
    return importer.summary(importer.start(rows, name, owner))


@router.get("/api/import")
async def mine(request: Request):
    """This person's imports, running or waiting to be saved, newest first."""
    importer.tidy()
    owner = who(request)
    return [importer.summary(j) for j in sorted(importer.jobs.values(), key=lambda j: -j["created"]) if j["owner"] == owner]


@router.get("/api/import/{jid}")
async def one(jid: str):
    j = _job(jid)
    return importer.summary(j) | {"rows": j["rows"]}


@router.delete("/api/import/{jid}")
async def drop(jid: str):
    _job(jid)
    importer.forget(jid)
    return {"ok": True}

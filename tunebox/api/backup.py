"""Backup and restore: everything the house made (people, groups, pass phrases, playlists and likes,
history, play counts, the play log, settings, the house setup, the blocklist, the list of local songs) in one
JSON file. The YouTube sign-in (browser.json) and the audit log are never in it. The local songs' audio is
only in the admin's full backup, a zip with that JSON file and the local folder; putting the audio
back is unzipping the local folder into Tunebox's data folder. A restore first saves what it replaces in backups/,
so it can be undone. Every night the server also writes a backup there itself (nightly()), keeping the last 14.

Anyone may download a backup, but only the admin's has the secrets (keys.json and the pass phrase
hashes). Restoring is the admin's, and it never changes the admin password."""
import asyncio
import datetime
import json
import sys
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .. import admin, audit, auth, blocklist, data, house, local, plays, wall
from ..config import (BLOCK_FILE, DATA, HISTORY_FILE, HOUSE_FILE, KEYS_FILE, LISTS_FILE, LOCAL_DIR, LOCAL_FILE, PEOPLE_FILE,
                      PLAYS_DIR, SEMINARS_FILE, SETTINGS_FILE, STATS_FILE, WALL_FILE)
from ..files import read_json, write_json
from ..player import player
from ..settings import load_settings, settings
from ..web import BaseModel

router = APIRouter()
BACKUPS = DATA / "backups"
FILES = {"settings": SETTINGS_FILE, "history": HISTORY_FILE, "playlists": LISTS_FILE, "people": PEOPLE_FILE,
         "seminars": SEMINARS_FILE, "stats": STATS_FILE, "keys": KEYS_FILE, "house": HOUSE_FILE,
         "blocklist": BLOCK_FILE, "local": LOCAL_FILE, "wall": WALL_FILE}


def snapshot(secrets: bool = True) -> dict:
    """What a backup holds, as it is on disk now (unsaved plays and counts are written first).
    Without secrets: no keys.json and no pass phrase hashes, and the backup says so ("stripped")."""
    plays.flush()
    data.save_stats(force=True)
    out = {"tunebox": 1, "made": int(time.time()), "files": {k: read_json(p, None) for k, p in FILES.items()}, "plays": {}}
    if PLAYS_DIR.exists():
        out["plays"] = {f.name: f.read_text(encoding="utf-8") for f in sorted(PLAYS_DIR.glob("*.jsonl"))}
    if not secrets:
        out["stripped"] = True
        del out["files"]["keys"]
        for p in (out["files"]["people"] or {}).values():
            p.pop("phrase", None)
            p.pop("kv", None)
    return out


NIGHTLY_KEEP = 14


async def nightly():
    """A backup of the day, once a day after 04:00 by the house's clock (when the house is likely asleep):
    backups/nightly-YYYY-MM-DD.json, with the secrets, so it restores fully. One write a day spares the SD
    card; the oldest beyond 14 are deleted. Started by app.py's lifespan; nothing may end this loop."""
    while True:
        try:
            now = datetime.datetime.now(house.tz())
            f = BACKUPS / f"nightly-{now.date().isoformat()}.json"
            if now.hour >= 4 and not f.exists():
                BACKUPS.mkdir(parents=True, exist_ok=True)
                write_json(f, snapshot())
                for old in sorted(BACKUPS.glob("nightly-*.json"))[:-NIGHTLY_KEEP]:
                    old.unlink(missing_ok=True)
        except Exception as exc:
            print(f"tunebox: nightly backup failed: {exc}", file=sys.stderr)
        await asyncio.sleep(600)


@router.get("/api/backup")
async def backup(request: Request):
    day = datetime.date.today().isoformat()
    return Response(json.dumps(snapshot(admin.is_admin(request)), ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="tunebox-backup-{day}.json"'})


class Pipe:
    """What zipfile writes to, handed on piece by piece: the zip is never whole in memory or on disk."""

    def __init__(self):
        self.buf, self.pos = bytearray(), 0

    def write(self, b):
        self.buf += b
        self.pos += len(b)
        return len(b)

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def take(self) -> bytes:
        out, self.buf = bytes(self.buf), bytearray()
        return out


def full_zip(backup: dict):
    """The backup and every local file, stored as they are (audio doesn't compress)."""
    pipe = Pipe()
    with zipfile.ZipFile(pipe, "w", zipfile.ZIP_STORED) as z:
        z.writestr("tunebox-backup.json", json.dumps(backup, ensure_ascii=False))
        yield pipe.take()
        for f in sorted(LOCAL_DIR.rglob("*")) if LOCAL_DIR.exists() else []:
            rel = f.relative_to(LOCAL_DIR)
            if not f.is_file() or rel.parts[0].startswith("."):
                continue                      # uploads still on their way in
            with z.open(zipfile.ZipInfo.from_file(f, f"local/{rel.as_posix()}"), "w", force_zip64=True) as dest, f.open("rb") as src:
                while chunk := src.read(1 << 18):
                    dest.write(chunk)
                    yield pipe.take()
    yield pipe.take()


@router.get("/api/backup/full", dependencies=[Depends(admin.need)])
async def full_backup(request: Request):
    day = datetime.date.today().isoformat()
    audit.log("backup", "Downloaded a full backup, with the local songs", request)
    return StreamingResponse(full_zip(snapshot()), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="tunebox-full-{day}.zip"'})


class RestoreBody(BaseModel):
    backup: dict


def replace_in_place(target, new):
    """The live containers are imported elsewhere: change them, never rebind them."""
    if isinstance(target, list):
        target[:] = new
    else:
        target.clear()
        target.update(new)


@router.post("/api/restore", dependencies=[Depends(admin.need)])
async def restore(body: RestoreBody, request: Request):
    b = body.backup
    files, logs = b.get("files"), b.get("plays") or {}
    if b.get("tunebox") != 1 or not isinstance(files, dict) or not isinstance(logs, dict):
        raise HTTPException(400, "That isn't a Tunebox backup")
    if any(not n.endswith(".jsonl") or "/" in n or "\\" in n or n.startswith(".") for n in logs):
        raise HTTPException(400, "That backup has a bad play log file name")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    before = BACKUPS / f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}.json"
    write_json(before, snapshot())            # what's here now, in case the restore was a mistake
    if "keys" not in files and isinstance(files.get("people"), dict):
        for pid, p in files["people"].items():    # a backup without secrets: names keep the pass phrases they have now
            now = data.people.get(pid) or {}
            p.update({k: now[k] for k in ("phrase", "kv") if k in now})
    if isinstance(files.get("keys"), dict):
        files["keys"]["admin"] = auth.keys.get("admin")   # the admin password stays what it is
    for k, path in FILES.items():
        v = files.get(k)
        if k == "keys" and v is None:
            continue                          # never without the secret: every device key would die
        if v is None:
            path.unlink(missing_ok=True)
        else:
            write_json(path, v)
    for f in PLAYS_DIR.glob("*.jsonl") if PLAYS_DIR.exists() else []:
        f.unlink()
    PLAYS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in logs.items():
        (PLAYS_DIR / name).write_text(str(text), encoding="utf-8")
    plays.reset()
    # the live state follows the files
    replace_in_place(data.history, read_json(HISTORY_FILE, []))
    replace_in_place(data.playlists, read_json(LISTS_FILE, {}))
    data.ensure_liked()
    replace_in_place(data.people, read_json(PEOPLE_FILE, {}))
    replace_in_place(data.seminars, data.load_seminars())
    replace_in_place(data.stats, read_json(STATS_FILE, {}))
    replace_in_place(auth.keys, read_json(KEYS_FILE, {}))
    auth.ensure_secret()
    replace_in_place(settings, load_settings())
    house.load()
    house.save_house()                        # bumps its revision: every page reads the setup again
    blocklist.load()
    local.load()
    wall.load()
    data.save_lists()                         # bumps the revisions: every page reloads names and likes
    data.save_people()
    await player.apply_volume()
    await player.mpv.apply_eq()
    audit.log("restore", f"Restored a backup from {time.strftime('%Y-%m-%d', time.localtime(b.get('made') or 0))}", request)
    return {"ok": True, "before": before.name}

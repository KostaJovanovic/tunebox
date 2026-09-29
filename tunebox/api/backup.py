"""Backup and restore: everything the house made (people, seminars, pass phrases, playlists and likes,
history, play counts, the play log, settings) in one JSON file. The YouTube sign-in (browser.json)
is never in it. A restore first saves what it replaces in backups/, so it can be undone."""
import datetime
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import auth, data, plays
from ..config import (DATA, HISTORY_FILE, KEYS_FILE, LISTS_FILE, PEOPLE_FILE, PLAYS_DIR, SEMINARS, SEMINARS_FILE,
                      SETTINGS_FILE, STATS_FILE)
from ..files import read_json, write_json
from ..player import player
from ..settings import load_settings, settings
from ..web import BaseModel

router = APIRouter()
BACKUPS = DATA / "backups"
FILES = {"settings": SETTINGS_FILE, "history": HISTORY_FILE, "playlists": LISTS_FILE, "people": PEOPLE_FILE,
         "seminars": SEMINARS_FILE, "stats": STATS_FILE, "keys": KEYS_FILE}


def snapshot() -> dict:
    """What a backup holds, as it is on disk now (unsaved plays and counts are written first)."""
    plays.flush()
    data.save_stats(force=True)
    out = {"tunebox": 1, "made": int(time.time()), "files": {k: read_json(p, None) for k, p in FILES.items()}, "plays": {}}
    if PLAYS_DIR.exists():
        out["plays"] = {f.name: f.read_text(encoding="utf-8") for f in sorted(PLAYS_DIR.glob("*.jsonl"))}
    return out


@router.get("/api/backup")
async def backup():
    day = datetime.date.today().isoformat()
    return Response(json.dumps(snapshot(), ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="tunebox-backup-{day}.json"'})


class RestoreBody(BaseModel):
    backup: dict


def replace_in_place(target, new):
    """The live containers are imported elsewhere: change them, never rebind them."""
    if isinstance(target, list):
        target[:] = new
    else:
        target.clear()
        target.update(new)


@router.post("/api/restore")
async def restore(body: RestoreBody):
    b = body.backup
    files, logs = b.get("files"), b.get("plays") or {}
    if b.get("tunebox") != 1 or not isinstance(files, dict) or not isinstance(logs, dict):
        raise HTTPException(400, "That isn't a Tunebox backup")
    if any(not n.endswith(".jsonl") or "/" in n or "\\" in n or n.startswith(".") for n in logs):
        raise HTTPException(400, "That backup has a bad play log file name")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    before = BACKUPS / f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}.json"
    write_json(before, snapshot())            # what's here now, in case the restore was a mistake
    for k, path in FILES.items():
        v = files.get(k)
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
    replace_in_place(data.seminars, {**SEMINARS, **read_json(SEMINARS_FILE, {})})
    replace_in_place(data.stats, read_json(STATS_FILE, {}))
    replace_in_place(auth.keys, read_json(KEYS_FILE, {}))
    auth.ensure_secret()
    replace_in_place(settings, load_settings())
    data.save_lists()                         # bumps the revisions: every page reloads names and likes
    data.save_people()
    await player.apply_volume()
    await player.mpv.apply_eq()
    return {"ok": True, "before": before.name}

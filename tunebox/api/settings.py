"""Settings: volume is in queue.py; here the EQ, playback options, sleep timer, alarm and the
YouTube account (the admin's to change), and where the server is on the network."""
import asyncio
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from ytmusicapi import YTMusic, setup as yt_setup

from .. import admin, audit, data, house, network, youtube
from ..config import AUTH_FILE, DATA, EQ_FREQS, EQ_PRESETS, QUALITY, TEST_RAMP
from ..audio import eq_bands
from ..mpv import PlayerDown
from ..player import player
from ..settings import save_settings, settings
from ..web import BaseModel, feature

router = APIRouter()


class EqBody(BaseModel):
    preset: str
    custom: list[float] | None = None


class AccountBody(BaseModel):
    headers: str


@router.get("/api/network")
async def get_network(request: Request):
    """The server's address as the device asking can reach it, and the Wi-Fi to join: the admin's name
    for it, else the one the server is on."""
    named = house.house["network"]
    net = await asyncio.to_thread(network.info, audit.asker(request)[0], not named)
    return {"ip": net["ip"], "host": net["host"], "wifi": named or net["wifi"] or None}


def account_status() -> dict:
    return {"signedIn": AUTH_FILE.exists()}


@router.get("/api/settings")
async def get_settings():
    return {"volume": settings["volume"], "eq": settings["eq"], "bands": eq_bands(),
            "freqs": EQ_FREQS, "presets": EQ_PRESETS, "account": account_status(),
            "normalize": settings["normalize"], "autoplay": settings["autoplay"], "turns": settings["turns"],
            "quality": settings["quality"], "qualities": list(QUALITY), "alarm": {**settings["alarm"], "tz": house.tz_name()},
            "lists": [data.list_summary(p) for p in data.sorted_lists()]}


class OptionsBody(BaseModel):
    normalize: bool | None = None
    autoplay: bool | None = None
    turns: bool | None = None
    quality: str | None = None


@router.post("/api/options")
async def set_options(body: OptionsBody):
    if body.quality is not None and body.quality not in QUALITY:
        raise HTTPException(400, "unknown quality")
    if body.autoplay is not None:
        settings["autoplay"] = body.autoplay
        if body.autoplay:
            asyncio.get_running_loop().create_task(player.refill())
    if body.quality is not None and body.quality != settings["quality"]:
        settings["quality"] = body.quality
        await asyncio.to_thread(youtube.set_quality, body.quality)
        player.resolver.cache.clear()         # the next tracks resolve at the new quality
    if body.turns is not None:
        settings["turns"] = body.turns
    if body.normalize is not None:
        settings["normalize"] = body.normalize
        await player.mpv.apply_eq()
    save_settings()
    return await get_settings()


class SleepBody(BaseModel):
    minutes: float | None = None
    track: bool = False


@router.post("/api/sleep", dependencies=[feature("sleep")])
async def set_sleep(body: SleepBody):
    await player.set_sleep(body.minutes, body.track)
    return player.state()["sleep"] or {}


class AlarmBody(BaseModel):
    enabled: bool
    time: str
    days: list[int]
    playlist: str | None = Field(None, alias="list")   # "list" in the JSON; as a field name it hides list[] (Python 3.14)
    level: int = 45
    ramp: float = 5
    tz: str | None = None                     # older pages send their own; the alarm goes by the house's time zone
    test: bool = False


@router.post("/api/alarm", dependencies=[feature("alarm")])
async def set_alarm(body: AlarmBody):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.time):
        raise HTTPException(400, "time must be HH:MM")
    a = settings["alarm"]
    a.update(enabled=body.enabled, time=body.time, days=sorted({d for d in body.days if 0 <= d <= 6}),
             list=body.playlist if body.playlist in data.playlists else None, level=max(1, min(100, body.level)),
             ramp=max(0, min(30, body.ramp)))
    save_settings()
    player.clock.set()
    if body.test:
        await player.fire_alarm(ramp_s=TEST_RAMP)   # the full ramp starts 50 dB down: minutes of near-silence
    return await get_settings()


@router.post("/api/eq", dependencies=[feature("eq")])
async def set_eq(body: EqBody):
    if body.preset != "custom" and body.preset not in EQ_PRESETS:
        raise HTTPException(400, "unknown preset")
    if body.custom is not None:
        if len(body.custom) != len(EQ_FREQS):
            raise HTTPException(400, "need 10 bands")
        settings["eq"]["custom"] = [round(max(-12, min(12, g)), 1) for g in body.custom]
    settings["eq"]["preset"] = body.preset
    save_settings()
    try:
        await player.mpv.apply_eq()
    except PlayerDown:
        raise
    except Exception as exc:
        raise HTTPException(500, f"mpv rejected the filter: {exc}")
    return await get_settings()


@router.post("/api/account", dependencies=[Depends(admin.need)])
async def set_account(body: AccountBody, request: Request):
    """Accepts request headers copied from music.youtube.com, or just the Cookie value."""
    raw = body.headers.strip().replace("\r", "")
    if not raw:
        raise HTTPException(400, "empty")
    lines = raw.split("\n")
    if not any(l.lower().startswith("cookie:") for l in lines):
        if len(lines) == 1 and "=" in raw:            # bare cookie string
            lines = [f"cookie: {raw}"]
        else:
            raise HTTPException(400, "No Cookie header found")
    if not any(l.lower().startswith("x-goog-authuser:") for l in lines):
        lines.append("x-goog-authuser: 0")
    cookie = next(l for l in lines if l.lower().startswith("cookie:"))
    if "SAPISID=" not in cookie:
        raise HTTPException(400, "That cookie has no SAPISID: copy it from music.youtube.com while signed in")
    if not any(l.lower().startswith("authorization:") for l in lines):
        lines.append("authorization: SAPISIDHASH 0_0")   # recomputed from the cookie on every request
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix="browser.", suffix=".new")   # unique, 0600 from the start
    os.close(fd)
    try:
        await asyncio.to_thread(yt_setup, tmp, "\n".join(lines))   # rewrites the file in place: stays 0600
        test = YTMusic(tmp)
        await asyncio.to_thread(test.get_library_playlists, 1)
    except Exception as exc:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(400, f"YouTube rejected these headers: {str(exc)[:160]}")
    os.replace(tmp, AUTH_FILE)
    youtube.yt = test
    audit.log("account", "Signed in to YouTube Music", request)
    return account_status()


@router.delete("/api/account", dependencies=[Depends(admin.need)])
async def clear_account(request: Request):
    AUTH_FILE.unlink(missing_ok=True)
    youtube.yt = YTMusic()
    audit.log("account", "Signed out of YouTube Music", request)
    return account_status()

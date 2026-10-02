"""yt-dlp's version and its update. YouTube changes often, and an old yt-dlp is the usual reason songs
stop loading: when they keep failing (youtube.trouble), /api/state tells the admin, who can update it.

  warning()   cheap, for every poll: the failures in a row, or None while songs load
  info()      the version running, the one installed, the newest on PyPI (asked at most every 6 hours)
  update()    pip install -U yt-dlp, only that package (a server's Python may be shared with other apps)

The running server keeps the yt-dlp it started with: an update takes effect after a restart."""
import asyncio
import importlib.metadata
import json
import sys
import time
import urllib.request

import yt_dlp.version

from . import youtube

LOADED = yt_dlp.version.__version__            # what this process plays with until it restarts
FAILS = 3                                     # songs failing in a row before the admin is told
PYPI = "https://pypi.org/pypi/yt-dlp/json"
LATEST_TTL = 6 * 3600

_latest = {"v": "", "at": 0.0}
_lock = asyncio.Lock()
last = {"ok": None, "msg": "", "at": 0}       # the last update's outcome


def vkey(v: str) -> tuple:
    """2026.08.19 and 2026.8.19 are the same version; .dev and the like sort after the date."""
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def installed() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return LOADED


def restart_needed() -> bool:
    """A newer yt-dlp is on disk than the one this process loaded (updated here, or by hand)."""
    return vkey(installed()) != vkey(LOADED)


def warning() -> dict | None:
    """For /api/state (the admin's only): no disk and no network unless songs are failing."""
    t = getattr(youtube, "trouble", None) or {}
    if t.get("fails", 0) < FAILS:
        return None
    return {"fails": t["fails"], "last": (t.get("last") or "")[:200], "busy": _lock.locked(), "restart": restart_needed()}


def _fetch_latest() -> str:
    req = urllib.request.Request(PYPI, headers={"User-Agent": "tunebox"})
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.load(r)["info"]["version"]


async def latest() -> str:
    """The newest yt-dlp on PyPI, or "" when it can't be asked (no internet is no error)."""
    if time.time() - _latest["at"] > LATEST_TTL:
        _latest["at"] = time.time()
        try:
            _latest["v"] = await asyncio.to_thread(_fetch_latest)
        except Exception:
            pass
    return _latest["v"]


async def info() -> dict:
    new = await latest()
    have = installed()
    return {"running": LOADED, "installed": have, "latest": new,
            "outdated": bool(new) and vkey(new) > vkey(have), "restart": restart_needed(),
            "busy": _lock.locked(), "warning": warning(), "last": last}


async def update() -> dict:
    """pip install -U yt-dlp with this server's own Python. Never -r: only yt-dlp moves."""
    if _lock.locked():
        return {**last, "busy": True}
    async with _lock:
        before = installed()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-U", "--disable-pip-version-check", "yt-dlp",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            text = out.decode(errors="replace").strip()
            ok = proc.returncode == 0
        except asyncio.TimeoutError:
            proc.kill()
            ok, text = False, "pip took more than 5 minutes"
        except Exception as exc:
            ok, text = False, str(exc)
        _latest["at"] = 0                     # ask PyPI afresh next time
        after = installed()
        if not ok:
            tail = text.splitlines()[-1] if text else "pip failed"
            msg = f"The update failed: {tail}"
        elif vkey(after) == vkey(before):
            msg = f"yt-dlp {after} is already the newest."
        else:
            msg = f"yt-dlp updated from {before} to {after}. Restart Tunebox to use it."
        last.update(ok=ok, msg=msg[:300], at=int(time.time()))
        return {**last, "before": before, "after": after, "restart": restart_needed()}

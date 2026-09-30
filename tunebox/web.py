"""What every request goes through: the same-site guard, readable errors, and who is asking."""
import ipaddress
import urllib.parse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel as PydanticModel, ConfigDict

from . import admin, auth, data, house
from .config import CGNAT, LOCAL_NAMES
from .mpv import PlayerDown


class BaseModel(PydanticModel):
    """Request bodies: Python's JSON reader takes NaN and Infinity, which min/max can't clamp."""
    model_config = ConfigDict(allow_inf_nan=False)


def host_ok(host: str | None) -> bool:
    """Our own names and private addresses only: a foreign name resolving to us is DNS rebinding."""
    h = (host or "").strip().lower()
    if h.startswith("["):                     # [v6]:port
        h = h[1:h.find("]")] if "]" in h else ""
    elif h.count(":") == 1:                   # name:port or v4:port
        h = h.split(":")[0]
    h = h.rstrip(".")
    if h in LOCAL_NAMES or h.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or (ip.version == 4 and ip in CGNAT)


async def same_site_only(request: Request, call_next):
    """Refuses foreign Host headers, writes from foreign pages (Origin), and non-JSON bodies
    (a foreign page can send text/plain or form bodies without a CORS preflight). Local songs and
    their covers arrive as the file itself: those types need a preflight too, which nothing here answers."""
    if not host_ok(request.headers.get("host")):
        return JSONResponse({"detail": "Unknown host"}, 403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None:
            try:
                oh = urllib.parse.urlsplit(origin).hostname if origin != "null" else None
            except ValueError:
                oh = None
            if not oh or not host_ok(oh):
                return JSONResponse({"detail": "Cross-site request refused"}, 403)
        has_body = request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers
        kind = request.headers.get("content-type", "").lower()
        file_ok = "/api/local/" in request.url.path and (kind == "application/octet-stream" or kind.startswith("image/"))
        if has_body and not kind.startswith("application/json") and not file_ok:
            return JSONResponse({"detail": "Send JSON"}, 415)
    return await call_next(request)


async def bad_body(_request, exc: RequestValidationError):
    # FastAPI's own 422 echoes the input back, and a NaN in it can't be written as JSON (a 500 instead)
    first = (exc.errors() or [{}])[0]
    where = ".".join(str(x) for x in first.get("loc", ())[1:]) or "request"
    return JSONResponse({"detail": f"{where}: {first.get('msg', 'invalid')}"}, 422)


async def player_down(_request, _exc):
    return JSONResponse({"detail": "Player is restarting"}, 503)


def install(app: FastAPI):
    app.middleware("http")(same_site_only)
    app.add_exception_handler(RequestValidationError, bad_body)
    app.add_exception_handler(PlayerDown, player_down)


def need_feature(request: Request, *names: str):
    """403 unless one of these features is on, or the admin is asking (a switched-off feature is the
    admin's alone)."""
    if not any(house.on(n) for n in names) and not admin.is_admin(request):
        raise HTTPException(403, f"The admin switched off {house.label(names[0])}")


def feature(*names: str):
    """For routes that belong to a feature the admin can switch off."""
    def check(request: Request):
        need_feature(request, *names)
    return Depends(check)


def who(request: Request) -> str:
    """The person this device picked (cookie tb_who), or "" for nobody, a removed name, or a protected
    name this device hasn't unlocked. With names switched off, everyone but the admin is nobody."""
    if not house.on("people") and not admin.is_admin(request, touch=False):
        return ""
    pid = request.cookies.get("tb_who") or ""
    return pid if pid in data.people and auth.holds_key(request, pid) else ""   # a protected name needs its key


def need_who(request: Request) -> str:
    """Adding songs needs a name; the UI answers this 401 by showing its picker. With names switched
    off nobody has one: songs are added by "" and simply queue in order."""
    pid = who(request)
    if not pid and house.on("people"):
        raise HTTPException(401, "pick")
    return pid

"""The admin: one password for the house (auth.py keeps its hash), and the sessions of the devices
that typed it. A session is a cookie (tb_admin) and lasts until ADMIN_IDLE seconds pass without
admin work. Sessions and the lockout live in memory only: a restart locks every device again.

A program on the server itself needs no password: every start writes a fresh token to cli.token,
and a request that carries it (X-Tunebox-Local) is the admin. Reading that file proves access to
the server's files, which the address a request comes from cannot (behind a reverse proxy every
request comes from this machine)."""
import asyncio
import hashlib
import hmac
import math
import os
import secrets
import sys
import time

from fastapi import HTTPException, Request, Response

from . import audit, auth
from .config import ADMIN_IDLE, LOCK_AFTER, LOCK_FOR, TOKEN_FILE

sessions: dict[str, float] = {}               # sha256 of the cookie -> when it last did admin work
fails = 0                                     # wrong passwords in a row
locked_until = 0.0
login_lock = asyncio.Lock()                   # one guess at a time, so the lockout can't be raced
local_token = secrets.token_hex(24)


def write_token():
    try:
        TOKEN_FILE.unlink(missing_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(local_token)
    except OSError as exc:
        print(f"tunebox: cannot write {TOKEN_FILE.name}: {exc}", file=sys.stderr)


write_token()


def _key(cookie: str | None) -> str:
    return hashlib.sha256((cookie or "").encode()).hexdigest()


def is_local(request: Request) -> bool:
    return hmac.compare_digest(request.headers.get("x-tunebox-local", ""), local_token)


def is_admin(request: Request, touch: bool = True) -> bool:
    """touch=False only looks (the state every page polls must not keep a session alive)."""
    if is_local(request):
        return True
    key = _key(request.cookies.get("tb_admin"))
    seen = sessions.get(key)
    if seen is None:
        return False
    now = time.monotonic()
    if now - seen > ADMIN_IDLE:
        del sessions[key]
        return False
    if touch:
        sessions[key] = now
    return True


def need(request: Request):
    """For routes only the admin may use. The page answers this 403 by asking for the password."""
    if not is_admin(request):
        raise HTTPException(403, "admin")


def locked_for() -> int:
    """Seconds until the password may be tried again (0: now)."""
    return max(0, math.ceil(locked_until - time.monotonic()))


def open_session(response: Response):
    cookie = secrets.token_urlsafe(32)
    sessions[_key(cookie)] = time.monotonic()
    response.set_cookie("tb_admin", cookie, path="/", httponly=True, samesite="strict")


def drop_all():
    sessions.clear()


def logout(request: Request, response: Response):
    sessions.pop(_key(request.cookies.get("tb_admin")), None)
    response.delete_cookie("tb_admin", path="/")


async def check(password: str | None, request: Request):
    """The password, or 403. LOCK_AFTER wrong ones in a row lock it for everyone for LOCK_FOR seconds."""
    global fails, locked_until
    async with login_lock:
        if locked_for():
            await asyncio.sleep(1)
            raise HTTPException(403, f"Too many wrong passwords. Try again in {math.ceil(locked_for() / 60)} min")
        if await auth.matches(password, auth.keys["admin"]):
            fails = 0
            return
        fails += 1
        audit.log("fail", f"Wrong admin password ({fails} in a row)", request)
        if fails >= LOCK_AFTER:
            fails, locked_until = 0, time.monotonic() + LOCK_FOR
            audit.log("lockout", f"Admin locked for {LOCK_FOR // 60} min", request)
        raise HTTPException(403, "Wrong admin password")


async def login(request: Request, response: Response, password: str | None, create: bool):
    if not auth.admin_set():
        if not create:
            raise HTTPException(409, "No admin password is set yet")
        auth.set_admin(auth.clean_phrase(password or ""))
        audit.log("password", "The admin password was set for the first time", request)
    else:
        await check(password, request)
    open_session(response)
    audit.log("unlock", "Admin unlocked", request)


async def change_password(request: Request, response: Response, old: str | None, new: str):
    new = auth.clean_phrase(new)
    await check(old, request)
    auth.set_admin(new)
    drop_all()                                # every other admin device has to type the new one
    open_session(response)
    audit.log("password", "The admin password was changed", request)


def reset(request: Request):
    """From the server itself only (run.py --reset-admin): the password is gone, the next person to
    open the admin panel sets a new one."""
    global fails, locked_until
    if not is_local(request):
        raise HTTPException(403, "Only from the server itself")
    auth.set_admin(None)
    drop_all()
    fails, locked_until = 0, 0.0
    audit.log("password", "The admin password was reset from the server", request)

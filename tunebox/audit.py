"""The audit log: every admin unlock, every wrong password and every change the admin made, newest
last, in audit.json. It is not part of a backup, so a restore can't erase it."""
import asyncio
import ipaddress
import sys
import time

from fastapi import Request

from .config import AUDIT_FILE, AUDIT_KEEP
from .files import read_json, write_json

entries: list[dict] = read_json(AUDIT_FILE, [])
_save_later: asyncio.TimerHandle | None = None


def asker(request: Request | None) -> tuple[str, str]:
    """The address and browser behind a request. Behind a reverse proxy every request comes from this
    machine, so the address the proxy passed on is used."""
    if request is None:
        return "", ""
    ip = request.client.host if request.client else ""
    try:
        if ipaddress.ip_address(ip).is_loopback:
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or ip
    except ValueError:
        pass
    return ip, request.headers.get("user-agent", "")[:120]


def log(ev: str, msg: str, request: Request | None = None):
    global _save_later
    ip, ua = asker(request)
    entries.append({"t": int(time.time()), "ev": ev, "msg": msg[:200], "ip": ip, "ua": ua})
    del entries[:-AUDIT_KEEP]
    try:                                      # one write a moment after the last entry (spares an SD card)
        if _save_later:
            _save_later.cancel()
        _save_later = asyncio.get_running_loop().call_later(5, flush)
    except RuntimeError:                      # no event loop (a script): write now
        flush()


def flush():
    global _save_later
    if _save_later:
        _save_later.cancel()
        _save_later = None
    try:
        write_json(AUDIT_FILE, entries)
    except OSError as exc:
        print(f"tunebox: cannot save the audit log: {exc}", file=sys.stderr)

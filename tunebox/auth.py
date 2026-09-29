"""Pass phrases. A person may have one: picking that name on a device then asks for it once, and the
device keeps a signed cookie (tb_key_<id>) instead. The house may have an admin phrase: it guards
removing people and clearing the history, and resets a person's forgotten phrase.

Only salted scrypt hashes are kept (in keys.json, with the secret that signs the cookies)."""
import asyncio
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

from . import data
from .config import KEYS_FILE
from .files import read_json, write_json

KEY_AGE = 10 * 365 * 86400                    # a device stays signed in until the phrase changes

keys: dict = read_json(KEYS_FILE, {})         # {"secret": hex, "admin": {"salt", "hash"} | None}
if not keys.get("secret"):
    keys["secret"] = secrets.token_hex(32)
    write_json(KEYS_FILE, keys)


def hash_phrase(phrase: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    h = hashlib.scrypt(phrase.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    return {"salt": salt, "hash": h.hex()}


def clean_phrase(phrase: str) -> str:
    phrase = " ".join(phrase.split())
    if len(phrase) < 4:
        raise HTTPException(400, "A pass phrase needs at least 4 characters")
    return phrase[:200]


async def matches(phrase: str | None, stored: dict | None) -> bool:
    """scrypt runs in a thread; a wrong guess costs a second, so guessing is slow."""
    if not stored:
        return True
    if phrase:
        h = await asyncio.to_thread(hash_phrase, " ".join(phrase.split())[:200], stored["salt"])
        if hmac.compare_digest(h["hash"], stored["hash"]):
            return True
    await asyncio.sleep(1)
    return False


# ---------- a person's phrase ----------
def device_key(pid: str) -> str:
    """What a device that knows pid's phrase holds; a new phrase (new salt) signs every device out."""
    salt = data.people[pid]["phrase"]["salt"]
    return hmac.new(bytes.fromhex(keys["secret"]), f"{pid}:{salt}".encode(), hashlib.sha256).hexdigest()


def holds_key(request: Request, pid: str) -> bool:
    p = data.people.get(pid)
    if not p or not p.get("phrase"):
        return True
    return hmac.compare_digest(request.cookies.get(f"tb_key_{pid}", ""), device_key(pid))


def give_key(response: Response, pid: str):
    if data.people[pid].get("phrase"):
        response.set_cookie(f"tb_key_{pid}", device_key(pid), max_age=KEY_AGE, path="/", httponly=True, samesite="lax")


def public(p: dict, request: Request) -> dict:
    """A person as clients see them: never the hash; locked, and whether this device holds the key."""
    out = {k: v for k, v in p.items() if k != "phrase"}
    out["locked"] = bool(p.get("phrase"))
    if out["locked"]:
        out["mine"] = holds_key(request, p["id"])
    return out


# ---------- the admin phrase ----------
def admin_set() -> bool:
    return bool(keys.get("admin"))


async def need_admin(phrase: str | None):
    """No admin phrase set: anyone may. Otherwise 403 "admin" asks the page for it."""
    if not admin_set():
        return
    if not phrase:
        raise HTTPException(403, "admin")
    if not await matches(phrase, keys["admin"]):
        raise HTTPException(403, "Wrong admin pass phrase")


def set_admin(phrase: str | None):
    keys["admin"] = hash_phrase(clean_phrase(phrase)) if phrase else None
    write_json(KEYS_FILE, keys)

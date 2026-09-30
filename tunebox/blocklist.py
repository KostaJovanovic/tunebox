"""Songs and artists the admin blocked, kept in blocklist.json. A blocked song can't be added, the
radio leaves it out, and it is taken out of what's up next."""
import time

from .config import BLOCK_FILE
from .files import read_json, write_json

_saved = read_json(BLOCK_FILE, {})
# {"songs": {videoId: {title, artist, at}}, "artists": {name in lower case: {name, id, at}}}; changed in place
blocks: dict = {"songs": dict(_saved.get("songs") or {}), "artists": dict(_saved.get("artists") or {})}


def load():
    """The file was replaced (a restore): read it afresh, in place."""
    saved = read_json(BLOCK_FILE, {})
    for kind in ("songs", "artists"):
        blocks[kind].clear()
        blocks[kind].update(saved.get(kind) or {})


def save():
    write_json(BLOCK_FILE, blocks)


def artists_of(track: dict) -> list[str]:
    return [a.strip().lower() for a in str(track.get("artist") or "").split(",") if a.strip()]


def blocked(track: dict) -> bool:
    if track.get("videoId") in blocks["songs"]:
        return True
    if not blocks["artists"]:
        return False
    ids = {a.get("id") for a in blocks["artists"].values() if a.get("id")}
    return (track.get("artistId") or None) in ids or any(a in blocks["artists"] for a in artists_of(track))


def add_song(track: dict):
    blocks["songs"][track["videoId"]] = {"title": track.get("title", ""), "artist": track.get("artist", ""), "at": int(time.time())}
    save()


def add_artist(name: str, artist_id: str = ""):
    blocks["artists"][name.strip().lower()] = {"name": name.strip(), "id": artist_id, "at": int(time.time())}
    save()


def remove(kind: str, key: str) -> bool:
    if blocks.get(kind, {}).pop(key, None) is None:
        return False
    save()
    return True

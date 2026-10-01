"""Songs and artists the admin blocked, kept in blocklist.json. A blocked song can't be added, the
radio leaves it out, and it is taken out of what's up next.

Softer, and anyone's to set: songs "not for the radio" (`radio`). The radio never picks them, but
people may still add them."""
import time

from .config import BLOCK_FILE
from .files import read_json, write_json

_saved = read_json(BLOCK_FILE, {})
# {"songs": {videoId: {title, artist, at}}, "artists": {name in lower case: {name, id, at}},
#  "radio": {videoId: {title, artist, at, by}}}; changed in place
KINDS = ("songs", "artists", "radio")
blocks: dict = {k: dict(_saved.get(k) or {}) for k in KINDS}


def load():
    """The file was replaced (a restore): read it afresh, in place."""
    saved = read_json(BLOCK_FILE, {})
    for kind in KINDS:
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


def for_radio(track: dict) -> bool:
    """May the radio pick this song: not blocked, and nobody said "not for the radio"."""
    return track.get("videoId") not in blocks["radio"] and not blocked(track)


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

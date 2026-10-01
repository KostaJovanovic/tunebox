"""Songs added from the wall screen, kept in wall.json: they belong to nobody (no name's stats, no turn of
anyone's), but the house counts them. `adds` is a list of the times songs were added there, changed in
place. Stats reads it for a period; a backup carries it."""
import time

from .config import WALL_FILE
from .files import read_json, write_json

adds: list[int] = list(read_json(WALL_FILE, {}).get("adds") or [])


def load():
    """The file was replaced (a restore): read it afresh, in place."""
    adds[:] = list(read_json(WALL_FILE, {}).get("adds") or [])


def added(n: int):
    """n songs were just added on the wall. One small write per add (adds are taps, not a stream)."""
    adds.extend([int(time.time())] * n)
    write_json(WALL_FILE, {"adds": adds})


def count(since: float = 0, until: float | None = None) -> int:
    until = until or time.time() + 1
    return sum(1 for t in adds if since <= t < until)

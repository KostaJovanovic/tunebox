"""What the admin set for the whole house, kept in house.json.

`house` is changed in place, never replaced. `rev` is replaced on every change, so read it as house.rev."""
import time

from .config import HOUSE_FILE
from .files import read_json, write_json

DEFAULTS = {"signups": "open"}                # "open": anyone adds their name; "closed": only the admin does

_saved = read_json(HOUSE_FILE, {})
house: dict = {**DEFAULTS, **(_saved if isinstance(_saved, dict) else {})}
rev = time.time_ns() // 1_000_000             # bumped on every change, so pages fetch it again


def save_house():
    global rev
    rev += 1
    write_json(HOUSE_FILE, house)

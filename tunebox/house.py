"""What the admin set for the whole house, kept in house.json: its name and accent, the time zone,
which features are on, what groups are called and how they work, what the wall screen shows,
the Wi-Fi's name for Settings, whether anyone may add a name, and how much room local songs may take.

A feature that is off is hidden from everyone and its routes answer only the admin (web.feature).
Nothing is deleted: switching it back on brings everything back.

`house` is changed in place, never replaced. `rev` is replaced on every change, so read it as house.rev."""
import copy
import time
from zoneinfo import ZoneInfo

from .config import HOUSE_FILE
from .files import read_json, write_json
from .settings import settings

# every feature the admin can switch off, and how a refusal names it ("The admin switched off ...")
FEATURES = {
    "lyrics": "lyrics", "wall": "the wall screen", "stats": "stats", "recap": "the recap", "alarm": "the alarm",
    "sleep": "the sleep timer", "playlists": "playlists", "likes": "likes", "groups": "groups", "people": "names",
    "radio": "the radio", "browse": "Home and Explore", "eq": "the equaliser", "links": "pasting links",
    "local": "local songs", "look": "choosing a theme and accent", "namelist": "the names in Settings",
}
# one-click setups: what each one switches off (everything else is on); the admin adjusts from there
PRESETS = {
    "home": [],
    "office": ["recap", "alarm", "sleep", "eq"],
    "party": ["people", "groups", "stats", "recap", "alarm", "sleep", "local"],
    "solo": ["people", "groups", "recap", "wall"],
}
ACCENTS = ("", "red", "orange", "yellow", "green", "blue", "magenta")   # "": every device keeps its own (web/shared/look.js)
DEFAULTS = {
    "signups": "open",                        # "open": anyone adds their name; "closed": only the admin does
    "name": "Tunebox",
    "accent": "",
    "tz": "",                                 # "": the alarm's old time zone, or the server's own time
    "network": "",                            # the Wi-Fi to join, shown in Settings; "": the server's own, when it is on Wi-Fi
    "features": {k: True for k in FEATURES},
    # what groups are called here, whether everyone must be in one, and who may make a new one ("open" or "admin")
    "groups": {"one": "Seminar", "many": "Seminars", "required": True, "create": "open"},
    "newPerson": {"groups": []},              # the groups a new person starts in when they pick none
    "wall": {"lyrics": True, "queue": False, "who": False, "clock": True, "controls": True},
    # local songs: the most they may take in all (None: no cap), the free space always left on the disk, the biggest file
    "local": {"capGB": None, "reserveGB": 2, "maxMB": 200},
}


def merged(saved) -> dict:
    """The defaults with what was saved on top; keys this version doesn't know are dropped."""
    out = copy.deepcopy(DEFAULTS)
    for k, v in (saved if isinstance(saved, dict) else {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if kk in out[k]})
        elif k in out and not isinstance(out[k], dict):
            out[k] = v
    return out


house: dict = merged(read_json(HOUSE_FILE, {}))
rev = time.time_ns() // 1_000_000             # bumped on every change, so pages fetch it again


def load():
    """The file was replaced (a restore): read it afresh, in place."""
    new = merged(read_json(HOUSE_FILE, {}))
    house.clear()
    house.update(new)


def save_house():
    global rev
    rev += 1
    write_json(HOUSE_FILE, house)


def on(name: str) -> bool:
    return bool(house["features"].get(name, True))


def label(name: str) -> str:
    """How a refusal names a feature; groups go by the house's own word for them."""
    return house["groups"]["many"].lower() if name == "groups" else FEATURES[name]


def tz():
    """The house's time zone (the alarm, the hours in Stats), or None for the server's own time."""
    for name in (house["tz"], settings["alarm"].get("tz")):
        if name:
            try:
                return ZoneInfo(name)
            except Exception:
                pass
    return None


def tz_name() -> str:
    z = tz()
    return z.key if z else ""


def public() -> dict:
    """What every page needs to know."""
    return {"name": house["name"], "accent": house["accent"], "tz": tz_name(), "signups": house["signups"], "network": house["network"],
            "off": [k for k in FEATURES if not on(k)], "groups": house["groups"], "newPerson": house["newPerson"],
            "wall": house["wall"], "local": {"maxMB": house["local"]["maxMB"]}, "rev": rev}

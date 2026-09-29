"""The house settings (volume, EQ, playback options, alarm), kept in settings.json."""
import asyncio
import math
import sys

from .config import SETTINGS_FILE, VOL_RANGE_DB
from .files import read_json, write_json


def load_settings() -> dict:
    s = {"volume": 70, "volume_scale": "db", "eq": {"preset": "flat", "custom": [0] * 10},
         "normalize": False, "autoplay": True, "quality": "best", "turns": True,
         "alarm": {"enabled": False, "time": "07:00", "days": [0, 1, 2, 3, 4], "list": None,
                   "level": 45, "ramp": 5, "tz": "Europe/Belgrade", "last": ""}}
    saved = read_json(SETTINGS_FILE, {})
    try:
        if "volume_scale" not in saved and saved.get("volume"):   # old files hold mpv's own volume
            saved["volume"] = round(max(0, min(100, 100 + 60 * math.log10(saved["volume"] / 100) * 100 / VOL_RANGE_DB)))
        saved["volume_scale"] = "db"
        s["alarm"].update(saved.pop("alarm", {}))
        s.update(saved)
    except (AttributeError, TypeError, ValueError):
        pass
    return s


_save_later: asyncio.TimerHandle | None = None


def save_settings() -> None:
    global _save_later
    if _save_later:
        _save_later.cancel()
        _save_later = None
    try:
        write_json(SETTINGS_FILE, settings)
    except OSError as exc:                    # the live settings still apply; only persistence failed
        print(f"tunebox: cannot save settings: {exc}", file=sys.stderr)


def save_settings_soon(delay: float = 3.0) -> None:
    """One write a moment after the last change, not one per step of a volume drag (spares an SD card)."""
    global _save_later
    if _save_later:
        _save_later.cancel()
    _save_later = asyncio.get_running_loop().call_later(delay, save_settings)


def flush_settings() -> None:
    """Shutdown: write a pending save now."""
    if _save_later:
        save_settings()


settings = load_settings()                    # changed in place, never replaced: import it freely

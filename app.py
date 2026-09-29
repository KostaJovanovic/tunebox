"""Tunebox: a lean YouTube Music player for the server's own speakers.

ytmusicapi provides search, browsing and YouTube Music's own radio ("up next")
recommendations; yt-dlp resolves each track to a direct audio stream (no ads);
mpv plays it through ALSA and is driven over its JSON IPC socket.
"""
import asyncio
import datetime
import ipaddress
import json
import math
import os
import random
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel as PydanticModel, ConfigDict
from ytmusicapi import YTMusic, setup as yt_setup
from ytmusicapi.exceptions import YTMusicUserError


class BaseModel(PydanticModel):
    """Request bodies: Python's JSON reader takes NaN and Infinity, which min/max can't clamp."""
    model_config = ConfigDict(allow_inf_nan=False)

HERE = Path(__file__).parent
RUN_DIR = Path(os.environ.get("TUNEBOX_RUN", "/run/tunebox"))
MPV_SOCK = RUN_DIR / "mpv.sock"
DATA = Path(os.environ.get("TUNEBOX_DATA") or HERE)   # where the files below live (the dev emulator moves them)
AUTH_FILE = DATA / "browser.json"          # optional: personal YT Music headers
SETTINGS_FILE = DATA / "settings.json"     # volume + equaliser, survives restarts
SESSION_FILE = DATA / "session.json"       # queue + position, restored paused after a restart
HISTORY_FILE = DATA / "history.json"       # recently played, newest first (shared by everyone)
LISTS_FILE = DATA / "playlists.json"       # Tunebox playlists (shared, editable by anyone)
PEOPLE_FILE = DATA / "people.json"         # who's listening: names picked per device (cookie tb_who)
STATS_FILE = DATA / "stats.json"           # when each song played, last STATS_DAYS days (for "Most played")
LIKED_ID = "liked"                          # the built-in "Liked songs" playlist: pinned first, can't be renamed or deleted
URL_TTL = 4 * 3600                          # stream URLs expire after ~6 h; re-resolve well before that
SESSION_EVERY = 60                          # save queue + position at most this often (seconds), spares the SD card
PLAYED_KEEP = 50                            # played tracks kept in the queue before the current one
FAIL_LIMIT = 3                              # stop after this many streams in a row failed
FAIL_TTL = 60                               # don't retry resolving a failed videoId in the background for this long
RADIO_REFILL_AT = 3                         # refill when this few tracks remain
UNDO_KEEP = 15                              # queue snapshots kept for undo (saved with the session)
UNDO_TRACKS = 200                           # songs kept per snapshot (the current one and what's up next)
PRELOAD_AT = 20                             # hand the next track to mpv this many seconds before the end
HISTORY_MAX = 300
STATS_DAYS = 30
VOL_RANGE_DB = 50                           # the volume slider spans -50 dB .. 0 dB (0 = mute)
SLEEP_FADE = 30                             # sleep timer fades out over the last 30 s
TRACK_FADE = 8                              # "end of track" sleep fades over the last 8 s
TEST_RAMP = 10                              # an alarm test ramps up over 10 s, not the alarm's minutes
QUALITY = {                                 # yt-dlp format per audio quality setting
    "best": "bestaudio[acodec=opus]/bestaudio",
    "balanced": "250/bestaudio[abr<=100]/bestaudio",
    "low": "249/bestaudio[abr<=64]/worstaudio",
}
NORMALIZE_FILTER = "dynaudnorm=f=500:g=31:p=0.9:m=8"
LOCAL_NAMES = {"ele.local", "ele", "ele.home", "localhost", "print-scan-server"}
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale addresses

yt = YTMusic(str(AUTH_FILE)) if AUTH_FILE.exists() else YTMusic()

EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_PRESETS = {
    "flat":       [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "bass":       [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "treble":     [0, 0, 0, 0, 0, 1, 2, 4, 5, 6],
    "vocal":      [-2, -2, -1, 1, 3, 4, 3, 1, 0, -1],
    "rock":       [4, 3, 2, 0, -1, -1, 1, 3, 4, 4],
    "pop":        [-1, 1, 3, 4, 3, 0, -1, -1, 0, 1],
    "electronic": [5, 4, 1, 0, -2, 1, 0, 1, 4, 5],
    "jazz":       [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "classical":  [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
    "loudness":   [6, 4, 0, 0, -2, 0, -1, -2, 3, 4],
    "night":      [-3, -2, -1, 0, 1, 2, 2, 1, -1, -2],
}


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


def write_json(path: Path, data) -> None:
    """Atomic and durable: a unique temp file next to the target, fsynced, then renamed over it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default):
    """A missing file gives the default; a corrupt one is moved aside (so nothing overwrites it) and reported."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except ValueError:                        # bad JSON or bad UTF-8
        bad = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(bad)
        except OSError:
            pass
        print(f"tunebox: {path.name} was corrupt, moved to {bad.name}", file=sys.stderr)
    except OSError as exc:
        print(f"tunebox: cannot read {path.name}: {exc}", file=sys.stderr)
    return default


def save_settings() -> None:
    try:
        write_json(SETTINGS_FILE, settings)
    except OSError as exc:                    # the live settings still apply; only persistence failed
        print(f"tunebox: cannot save settings: {exc}", file=sys.stderr)


def level_to_mpv(level: float, extra_db: float = 0.0) -> float:
    """Slider level (0-100) to mpv volume. The slider is linear in dB; mpv cubes its
    volume (gain = (v/100)^3), so v = 100 * gain^(1/3) = 100 * 10^(dB/60)."""
    if level <= 0:
        return 0
    db = (level - 100) * VOL_RANGE_DB / 100 + extra_db
    return round(100 * 10 ** (db / 60), 2)


def eq_bands() -> list[float]:
    eq = settings["eq"]
    return eq["custom"] if eq["preset"] == "custom" else EQ_PRESETS.get(eq["preset"], EQ_PRESETS["flat"])


def pre_cut(bands) -> str:
    """Linear gain for the pre-cut that keeps EQ boosts from clipping."""
    return f"{10 ** (-max(0, max(bands)) / 20):.5f}"


def eq_filter(bands=None) -> str:
    """mpv audio filter string: a fixed chain of named filters (pre-cut, one equalizer per band,
    optional loudness normaliser). Its gains can then be changed live with af-command, without
    rebuilding the chain, which would briefly interrupt playback."""
    bands = list(bands if bands is not None else eq_bands())
    parts = [f"volume@pre=volume={pre_cut(bands)}"]
    parts += [f"equalizer@b{i}=f={f}:t=o:w=1:g={g}" for i, (f, g) in enumerate(zip(EQ_FREQS, bands))]
    if settings.get("normalize"):
        parts.append(NORMALIZE_FILTER)
    return "@tbeq:lavfi=[" + ",".join(parts) + "]"


settings = load_settings()
history: list[dict] = read_json(HISTORY_FILE, [])
playlists: dict[str, dict] = read_json(LISTS_FILE, {})
if LIKED_ID not in playlists:
    playlists[LIKED_ID] = {"id": LIKED_ID, "name": "Liked songs", "tracks": [], "created": int(time.time()), "updated": int(time.time())}
lists_rev = time.time_ns() // 1_000_000        # bumped on every playlist change, so clients refresh their liked hearts
people: dict[str, dict] = read_json(PEOPLE_FILE, {})
people_rev = time.time_ns() // 1_000_000       # bumped when names change, so clients refresh their chips
stats: dict[str, dict] = read_json(STATS_FILE, {})   # {videoId: {"track": {...}, "plays": [ts, ...]}}
stats_dirty = False
ydl = yt_dlp.YoutubeDL({
    "format": QUALITY.get(settings["quality"], QUALITY["best"]),
    "quiet": True, "no_warnings": True, "noplaylist": True,
    # Official Node 22 build (Debian's Node 20 is too old for yt-dlp's challenge solver)
    "js_runtimes": {"node": {"path": str(HERE.parent / "node" / "bin" / "node")}},
})
ydl_lock = threading.Lock()


def track_from(item: dict) -> dict | None:
    """Normalises any ytmusicapi song-like dict into the fields the UI needs."""
    vid = item.get("videoId")
    if not vid:
        return None
    artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
    thumbs = item.get("thumbnails") or item.get("thumbnail") or []
    album = item.get("album")
    return {
        "videoId": vid,
        "title": item.get("title", ""),
        "artist": artists,
        "album": album.get("name") if isinstance(album, dict) else (album or ""),
        "duration": item.get("duration") or item.get("length") or "",
        "thumb": thumbs[-1]["url"] if thumbs else "",
    }


def count_play(track: dict, when: float | None = None):
    """Remembers when a song played; saved with the session every minute (spares the SD card)."""
    global stats_dirty
    s = stats.setdefault(track["videoId"], {"plays": []})
    s["track"] = {k: str(track.get(k) or "") for k in ("videoId", "title", "artist", "album", "duration", "thumb")}
    s["plays"].append(int(when or time.time()))
    stats_dirty = True


def save_stats(force: bool = False):
    global stats_dirty
    if not (stats_dirty or force):
        return
    cutoff = time.time() - STATS_DAYS * 86400
    for vid in list(stats):
        stats[vid]["plays"] = [t for t in stats[vid]["plays"] if t > cutoff][-500:]
        if not stats[vid]["plays"]:
            del stats[vid]
    try:
        write_json(STATS_FILE, stats)
        stats_dirty = False
    except OSError:
        pass


if not STATS_FILE.exists():                   # first start: begin with what the history already knows
    for h in reversed(history):
        if h.get("videoId") and time.time() - h.get("playedAt", 0) < STATS_DAYS * 86400:
            count_play(h, h["playedAt"])


class Resolver:
    """Resolves videoIds to stream URLs in the background and caches them."""

    def __init__(self):
        self.cache: dict[str, tuple[float, str]] = {}
        self.pending: dict[str, asyncio.Future] = {}
        self.failed: dict[str, float] = {}   # videoId -> when it last failed to resolve

    def _extract(self, vid: str) -> str:
        with ydl_lock:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={vid}", download=False)
        return info["url"]

    async def get(self, vid: str, retry: bool = True) -> str:
        """retry=False (background work) gives up at once on a videoId that failed in the last FAIL_TTL s."""
        hit = self.cache.get(vid)
        if hit and time.time() - hit[0] < URL_TTL:
            return hit[1]
        if not retry and time.time() - self.failed.get(vid, 0) < FAIL_TTL:
            raise RuntimeError("failed recently")
        if vid not in self.pending:
            loop = asyncio.get_running_loop()
            self.pending[vid] = loop.run_in_executor(None, self._extract, vid)
        try:
            url = await self.pending[vid]
        except Exception:
            self.failed[vid] = time.time()
            raise
        finally:
            self.pending.pop(vid, None)
        self.failed.pop(vid, None)
        self.cache[vid] = (time.time(), url)
        return url

    def prefetch(self, vid: str) -> None:
        asyncio.get_running_loop().create_task(self._quiet(vid))

    async def _quiet(self, vid: str) -> None:
        try:
            await self.get(vid, retry=False)
        except Exception:
            pass


class PlayerDown(ConnectionError):
    """mpv is not answering (crashed, restarting, or stuck): the API reports 503."""


class Mpv:
    """Minimal async client for mpv's JSON IPC."""

    def __init__(self):
        self.proc = None
        self.writer = None
        self.req = 0
        self.waiting: dict[int, asyncio.Future] = {}
        self.props = {}
        self.on_end = None
        self.on_start = None
        self.on_loaded = None                 # a started entry opened its stream and plays
        self.started = None                   # playlist entry id of the last start-file
        self.on_exit = None                   # called when the IPC connection to mpv is lost
        self.eq_chain = None                  # (normalize, gains) written into the af string
        self.eq_live = None                   # gains currently applied (af string + af-command)

    async def start(self):
        if self.proc and self.proc.returncode is None:   # a restart: make sure the old mpv is gone
            self.proc.kill()
            await self.proc.wait()
        self.props = {"pause": False, "time-pos": 0, "duration": 0, "volume": 70, "idle-active": True}
        self.eq_chain = self.eq_live = self.started = None
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        MPV_SOCK.unlink(missing_ok=True)
        self.proc = await asyncio.create_subprocess_exec(
            "mpv", "--idle=yes", "--no-video", "--no-terminal", "--no-config",
            f"--input-ipc-server={MPV_SOCK}", "--ao=alsa", f"--volume={level_to_mpv(settings['volume'])}",
            "--cache=yes", "--demuxer-max-bytes=16MiB", "--audio-buffer=0.5",
            "--prefetch-playlist=yes", "--gapless-audio=weak")
        for _ in range(50):
            if MPV_SOCK.exists():
                break
            await asyncio.sleep(0.1)
        reader, self.writer = await asyncio.open_unix_connection(str(MPV_SOCK), limit=1 << 20)
        asyncio.get_running_loop().create_task(self._read(reader))
        for i, prop in enumerate(self.props, 1):
            await self.send("observe_property", i, prop)
        await self.apply_eq()

    async def quit(self):
        """Server shutdown: stop mpv (no restart), killing it if it will not go."""
        self.on_exit = None
        p = self.proc
        if not p or p.returncode is not None:
            return
        p.terminate()
        try:
            await asyncio.wait_for(p.wait(), 3)
        except asyncio.TimeoutError:
            p.kill()
            await p.wait()

    async def apply_eq(self, rebuild: bool = False):
        """Applies the current EQ. Gain changes go to the running filters with af-command (no gap);
        the chain itself is only rebuilt when its shape changes, or when nothing is audible."""
        bands, norm = list(eq_bands()), bool(settings.get("normalize"))
        quiet = self.props.get("idle-active") or self.props.get("pause")
        if rebuild or quiet or not self.eq_chain or self.eq_chain[0] != norm:
            res = await self.send("set_property", "af", eq_filter(bands))
            if res.get("error") != "success":
                raise RuntimeError(res.get("error"))
            self.eq_chain, self.eq_live = (norm, bands), bands
            return
        await self._eq_commands(bands, self.eq_live)

    async def _eq_commands(self, bands, prev=None):
        for i, g in enumerate(bands):
            if prev is None or prev[i] != g:
                await self.send("af-command", "tbeq", "g", str(g), f"equalizer@b{i}")
        if prev is None or pre_cut(prev) != pre_cut(bands):
            await self.send("af-command", "tbeq", "volume", pre_cut(bands), "volume@pre")
        self.eq_live = bands

    async def _eq_reapply(self):
        """mpv rebuilds the chain from its string when audio restarts; put the live gains back."""
        if self.eq_chain and self.eq_live != self.eq_chain[1]:
            try:
                await self._eq_commands(self.eq_live)
            except Exception:
                pass

    async def eq_sync(self):
        """While paused or idle, write the live gains into the af string (nobody hears the rebuild)."""
        if (self.eq_chain and self.eq_live != self.eq_chain[1]
                and (self.props.get("pause") or self.props.get("idle-active"))):
            await self.apply_eq(rebuild=True)

    async def _read(self, reader):
        try:
            while line := await reader.readline():
                try:
                    self._dispatch(json.loads(line))
                except Exception:
                    pass                      # one bad message must not end the connection
        except Exception:
            pass                              # connection reset
        self.writer = None
        for fut in self.waiting.values():
            if not fut.done():
                fut.set_exception(PlayerDown("mpv is gone"))
        self.waiting.clear()
        if self.on_exit:
            asyncio.get_running_loop().create_task(self.on_exit())

    def _dispatch(self, msg: dict):
        if "request_id" in msg and msg["request_id"] in self.waiting:
            fut = self.waiting.pop(msg["request_id"])
            if not fut.done():                # its sender may have timed out already
                fut.set_result(msg)
        elif msg.get("event") == "property-change":
            self.props[msg["name"]] = msg.get("data")
        elif msg.get("event") == "end-file" and msg.get("reason") in ("eof", "error"):
            if self.on_end:
                asyncio.get_running_loop().create_task(self.on_end(msg.get("reason"), msg.get("playlist_entry_id")))
        elif msg.get("event") == "start-file":
            self.started = msg.get("playlist_entry_id")
            if self.eq_chain and self.eq_live != self.eq_chain[1]:
                # audio restarts for the new file anyway: bake the live gains into the chain now
                asyncio.get_running_loop().create_task(self.apply_eq(rebuild=True))
            if self.on_start:
                asyncio.get_running_loop().create_task(self.on_start(msg.get("playlist_entry_id")))
        elif msg.get("event") == "file-loaded":   # carries no entry id: it belongs to the last start-file
            if self.on_loaded:
                asyncio.get_running_loop().create_task(self.on_loaded(self.started))
        elif msg.get("event") == "audio-reconfig":
            asyncio.get_running_loop().create_task(self._eq_reapply())

    async def send(self, *cmd):
        if not self.writer:
            raise PlayerDown("mpv is not running")
        self.req += 1
        rid = self.req
        fut = asyncio.get_running_loop().create_future()
        self.waiting[rid] = fut
        try:
            self.writer.write((json.dumps({"command": list(cmd), "request_id": rid}) + "\n").encode())
            await self.writer.drain()
            return await asyncio.wait_for(fut, 5)
        except (ConnectionError, asyncio.TimeoutError) as exc:
            raise PlayerDown(str(exc) or "mpv did not answer") from exc
        finally:
            self.waiting.pop(rid, None)


class Player:
    def __init__(self):
        self.mpv = Mpv()
        self.resolver = Resolver()
        self.queue: list[dict] = []
        self.index = -1
        self.loading = False
        self.error = ""
        self.play_lock = asyncio.Lock()
        self.resume_at = 0.0                  # position to resume from after a restart
        self.cur_entry = None                 # mpv playlist entry id of the current track
        self.armed = None                     # {"index", "videoId", "entry"} of the preloaded next track
        self.fade_db = 0.0                    # extra attenuation for sleep fade-out / alarm ramp
        self.sleep = None                     # {"until": ts} or {"mode": "track", "entry": id}
        self.ramp = None                      # (start_ts, seconds) of an alarm volume ramp
        self.restarting = False               # mpv is being restarted after a crash
        self.gen = 0                          # bumped by every play request; only the newest loads
        self.fails = 0                        # streams that failed in a row
        self.seed = None                      # the last song someone added: the radio (auto songs) follows it
        self.seed_gen = 0                     # bumped on every re-seed; a radio that arrives late is dropped
        self.undo: list[dict] = []            # queue snapshots, oldest first

    async def apply_volume(self):
        await self.mpv.send("set_property", "volume", level_to_mpv(settings["volume"], self.fade_db))

    def add_history(self, track: dict | None):
        if not track or (history and history[0]["videoId"] == track["videoId"]):
            return
        count_play(track)
        history.insert(0, {**track, "playedAt": int(time.time())})
        del history[HISTORY_MAX:]
        try:
            write_json(HISTORY_FILE, history)
        except OSError:
            pass

    def session_data(self) -> dict:
        return {"queue": self.queue, "index": self.index,
                "position": self.mpv.props.get("time-pos") or self.resume_at or 0,
                "seed": self.seed, "undo": self.undo}

    def save_session(self):
        try:
            write_json(SESSION_FILE, self.session_data())
        except OSError:
            pass

    async def _session_loop(self):
        """Saves the queue and position at most every SESSION_EVERY seconds, and only when they
        changed, so a crash or power cut loses at most that much (and the SD card is spared)."""
        last = None
        while True:
            await asyncio.sleep(SESSION_EVERY)
            save_stats()
            try:
                self.trim_played()
                data = self.session_data()
                data["position"] = round(data["position"])
                snap = json.dumps(data)       # a snapshot: the queue list itself is mutated in place
                if snap != last:
                    self.save_session()
                    last = snap
            except Exception:
                pass

    def trim_played(self):
        """Drops the oldest played tracks so at most PLAYED_KEEP stay before the current one."""
        drop = self.index - PLAYED_KEEP
        if drop <= 0:
            return
        del self.queue[:drop]
        self.index -= drop
        if self.armed:
            self.armed["index"] -= drop

    def load_session(self):
        data = read_json(SESSION_FILE, None)
        try:
            self.queue, self.index = list(data["queue"]), int(data["index"])
            self.resume_at = float(data.get("position") or 0)
            self.seed, self.undo = data.get("seed"), list(data.get("undo") or [])
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

    @property
    def current(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    async def start(self):
        self.mpv.on_end = self._ended
        self.mpv.on_start = self._started
        self.mpv.on_loaded = self._loaded
        self.mpv.on_exit = self._mpv_lost
        await self.mpv.start()
        loop = asyncio.get_running_loop()
        loop.create_task(self._preload_loop())
        loop.create_task(self._volume_loop())
        loop.create_task(self._alarm_loop())
        self.load_session()
        loop.create_task(self._session_loop())

    async def _mpv_lost(self):
        """mpv died or its socket broke: start a new one and keep the queue, paused where it was
        (play resumes from resume_at, as after a server restart)."""
        if self.restarting:
            return                            # a failed restart attempt drops its connection too
        self.restarting = True
        p = self.mpv.props
        if self.current and not p.get("idle-active") and p.get("time-pos"):
            self.resume_at = p["time-pos"]
        self.armed, self.cur_entry = None, None
        self.save_session()
        delay = 1
        while True:
            await asyncio.sleep(delay)
            try:
                await self.mpv.start()
                break
            except Exception:
                delay = min(delay * 2, 30)
        self.restarting = False
        self.error = "Player restarted, press play to continue"
        try:
            await self.apply_volume()
        except Exception:
            pass

    async def _ended(self, reason, entry=None):
        if entry is not None and entry != self.cur_entry:
            return                            # an old or dropped playlist entry
        if reason == "eof" and self.armed:
            return                            # mpv moves on to the preloaded track by itself
        if reason == "eof" and self.sleep and self.sleep.get("mode") == "track":
            await self.end_sleep()            # sleep "at end of track": stop here, ready for the next one
            if self.index + 1 < len(self.queue):
                self.index += 1
            return
        if reason == "error":
            self.fails += 1
            if self.current:
                self.resolver.cache.pop(self.current["videoId"], None)
            if self.fails >= FAIL_LIMIT:      # YouTube is refusing us: stop instead of burning the queue
                self.cur_entry = None
                await self.disarm()
                try:
                    await self.mpv.send("stop")
                except Exception:
                    pass
                self.error = "Streams are failing, try again later"
                return
            self.error = "Stream failed, skipping"
        if self.index + 1 < len(self.queue):
            await self.play_index(step=1)

    async def _started(self, entry):
        """mpv started a playlist entry: if it is the preloaded one, advance the queue."""
        armed = self.armed
        if not armed or entry != armed["entry"]:
            return
        self.armed, self.cur_entry = None, entry
        if 0 <= armed["index"] < len(self.queue) and self.queue[armed["index"]]["videoId"] == armed["videoId"]:
            self.index = armed["index"]
        self.error, self.resume_at = "", 0
        try:
            await self.mpv.send("playlist-clear")      # drop the finished entry, keep the current one
        except Exception:
            pass
        for nxt in self.queue[self.index + 1:self.index + 3]:
            self.resolver.prefetch(nxt["videoId"])
        await self.refill()

    async def _loaded(self, entry):
        """The current entry opened its stream and plays: only now does it count as played."""
        if entry is None or entry != self.cur_entry:
            return
        self.fails = 0
        self.add_history(self.current)

    async def disarm(self):
        """Forgets the preloaded next track after the queue changed."""
        if self.armed:
            self.armed = None
            try:
                await self.mpv.send("playlist-clear")
            except Exception:
                pass

    async def _preload_loop(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.mpv.eq_sync()
            except Exception:
                pass
            try:
                await self._arm_next()
            except Exception:
                pass

    async def _arm_next(self):
        p = self.mpv.props
        dur, pos = p.get("duration") or 0, p.get("time-pos") or 0
        i, entry0 = self.index + 1, self.cur_entry
        if self.armed or self.loading or p.get("idle-active") or not dur or dur - pos > PRELOAD_AT or i >= len(self.queue):
            return
        if self.sleep and self.sleep.get("mode") == "track":
            return                            # the sleep timer stops at the end of this track
        track = self.queue[i]
        url = await self.resolver.get(track["videoId"], retry=False)
        if (self.armed or self.loading or self.cur_entry != entry0 or self.index + 1 != i or i >= len(self.queue)
                or self.queue[i]["videoId"] != track["videoId"]):
            return                            # queue or track changed while resolving
        res = await self.mpv.send("loadfile", url, "append")
        entry = (res.get("data") or {}).get("playlist_entry_id")
        if entry is not None:
            self.armed = {"index": i, "videoId": track["videoId"], "entry": entry}

    async def play_index(self, i: int = 0, start: float = 0, step: int = 0, vid: str | None = None):
        """Plays queue[i], or the track `step` places from the current one (worked out when the request
        runs, so quick skips add up). Resolving happens outside the lock; only the newest request loads."""
        async with self.play_lock:
            if step:
                i = self.index + step
            if not 0 <= i < len(self.queue) or (vid and self.queue[i]["videoId"] != vid):
                return
            self.gen += 1
            gen, track = self.gen, self.queue[i]
            self.index, self.resume_at = i, 0
            self.armed, self.cur_entry = None, None   # the old entry ending must not move the queue on
            self.loading, self.error = True, ""
        try:
            url = await self.resolver.get(track["videoId"])
            async with self.play_lock:
                if gen != self.gen:
                    return                    # a newer request took over while this one resolved
                if start > 1:
                    res = await self.mpv.send("loadfile", url, "replace", -1, f"start={start:.1f}")
                else:
                    res = await self.mpv.send("loadfile", url, "replace")
                self.cur_entry = (res.get("data") or {}).get("playlist_entry_id")
                await self.mpv.send("set_property", "pause", False)
        except Exception as exc:
            if gen == self.gen:
                self.error = f"Could not load: {exc}"[:200]
        finally:
            if gen == self.gen:
                self.loading = False
        if gen != self.gen:
            return
        for nxt in self.queue[self.index + 1:self.index + 3]:
            self.resolver.prefetch(nxt["videoId"])
        await self.refill()

    async def stop(self):
        self.gen += 1                         # cancels a play request still resolving
        self.armed, self.cur_entry, self.loading = None, None, False
        await self.mpv.send("stop")
        self.queue, self.index = [], -1

    # ---------- the two-part queue: now playing → songs people added (src "user") → radio (src "auto") ----------
    def user_end(self) -> int:
        """Index just past the songs people added, i.e. where the radio starts."""
        i = self.index + 1
        while i < len(self.queue) and self.queue[i].get("src") == "user":
            i += 1
        return i

    def turn_slot(self, by: str) -> int:
        """Where a song added by `by` goes. Taking turns: someone with k songs up next goes before the
        first song that is some person's (k+1)th, so everyone's songs alternate. Otherwise: at the end."""
        start, end = self.index + 1, self.user_end()
        if not settings["turns"]:
            return end
        k = sum(1 for t in self.queue[start:end] if t.get("by") == by)
        rounds: dict[str, int] = {}
        for j in range(start, end):
            b = self.queue[j].get("by", "")
            rounds[b] = rounds.get(b, 0) + 1
            if rounds[b] > k + 1:
                return j
        return end

    def finished(self) -> bool:
        """Nothing plays and nothing would: a song added now should start right away."""
        if self.current is None:
            return True
        return (bool(self.mpv.props.get("idle-active")) and not self.loading and not self.resume_at
                and self.index + 1 >= len(self.queue))

    async def sync_armed(self):
        """Drops the preloaded next track if the queue changed so that it isn't next any more."""
        a = self.armed
        if a and (a["index"] != self.index + 1 or a["index"] >= len(self.queue)
                  or self.queue[a["index"]]["videoId"] != a["videoId"]):
            await self.disarm()

    async def add(self, tracks: list[dict], by: str, mode: str = "add", label: str = "") -> int:
        """add: each song at its turn at the end of the added songs; next: in front of them, in order;
        now: in front, and the first one plays at once. The radio then follows the last song added.
        Returns the first song's place in the queue (1 = next, 0 = playing now)."""
        items = [{**t, "by": by, "src": "user"} for t in tracks]
        if not items:
            return 0
        self.snapshot(label or (f'Added "{items[0]["title"]}"' if len(items) == 1 else f"Added {len(items)} songs"), by)
        start_now = mode == "now" or self.finished()
        if self.current is None:
            self.queue, self.index = [], -1
        if mode in ("next", "now") or start_now:
            at = self.index + 1
            self.queue[at:at] = items
            pos = 0 if start_now else 1
        else:
            pos = 0
            for it in items:
                j = self.turn_slot(by)
                self.queue.insert(j, it)
                pos = pos or j - self.index
        await self.sync_armed()
        if start_now:
            self.fails = 0
            asyncio.get_running_loop().create_task(self.play_index(self.index + 1))
        self.reseed(items[-1])
        for t in items[:2]:
            self.resolver.prefetch(t["videoId"])
        return pos

    async def replace(self, tracks: list[dict], start: int = 0, by: str = "", label: str = ""):
        """Plays a list now; it becomes the songs up next (the radio follows its last song). What played
        before stays behind the current song, so Previous still goes back to it."""
        items = [{**t, "by": by, "src": "user"} for t in tracks if t]
        if not items:
            return
        self.snapshot(label or f'Played "{items[0]["title"]}"', by)
        keep = self.queue[:self.index + 1] if self.current else []
        await self.disarm()
        self.queue, self.fails = keep + items, 0   # a fresh run of FAIL_LIMIT tries
        self.reseed(items[-1])
        await self.play_index(len(keep) + max(0, min(start, len(items) - 1)))

    async def play_tracks(self, tracks: list[dict], start: int = 0, radio: bool = False):
        """The alarm's way in: replace the queue with a list."""
        await self.replace(tracks, start, label="Alarm")

    def reseed(self, track: dict, fill: bool = True):
        """The radio now follows `track`: its radio replaces the auto songs (in the background)."""
        self.seed = {k: str(track.get(k) or "") for k in ("videoId", "title", "artist", "thumb")}
        self.seed_gen += 1
        if fill and settings["autoplay"]:
            asyncio.get_running_loop().create_task(self._reseed(self.seed_gen))

    async def radio_for(self, vid: str, limit: int = 30) -> list[dict]:
        try:
            radio = await asyncio.to_thread(yt.get_watch_playlist, vid, radio=True, limit=limit)
        except Exception:
            return []
        return [t for t in map(track_from, radio.get("tracks", [])) if t and t["videoId"] != vid]

    async def _reseed(self, gen: int, fresh: bool = False):
        """Replaces the auto songs with the seed's radio. fresh: avoid the songs it replaces (Refresh)."""
        items = await self.radio_for(self.seed["videoId"], 50 if fresh else 30)
        if gen != self.seed_gen or not items:
            return                            # another song was added meanwhile: its radio wins
        end = self.user_end()
        known = {t["videoId"] for t in self.queue[:end]}
        if fresh:
            known |= {t["videoId"] for t in self.queue[end:]}
            random.shuffle(items)
        new = []
        for t in items:
            if t["videoId"] not in known:
                new.append({**t, "by": "", "src": "auto"})
                known.add(t["videoId"])
        if new:
            self.queue[end:] = new[:30]
            await self.sync_armed()

    async def refill(self, force: bool = False):
        """Keeps the music going: when little is left, more radio of the seed (the last song someone
        added), or of the current song when the seed has nothing new."""
        if not (settings["autoplay"] or force) or not self.current or len(self.queue) - self.index > RADIO_REFILL_AT:
            return
        gen = self.seed_gen
        for seed in (self.seed, self.current):
            if not seed:
                continue
            items = await self.radio_for(seed["videoId"])
            if gen != self.seed_gen or not self.current:
                return                        # the queue changed meanwhile: that radio is stale
            known = {t["videoId"] for t in self.queue}
            new = [{**t, "by": "", "src": "auto"} for t in items if t["videoId"] not in known]
            if new:
                self.queue.extend(new)
                return

    # ---------- undo: a snapshot before every queue change ----------
    def snapshot(self, label: str, by: str = ""):
        cur = max(self.index, 0)
        self.undo.append({"id": secrets.token_hex(3), "label": label[:90], "by": by, "at": int(time.time()),
                          "queue": [dict(t) for t in self.queue[cur:cur + UNDO_TRACKS]] if self.current else [],
                          "position": round(self.mpv.props.get("time-pos") or self.resume_at or 0, 1),
                          "seed": self.seed})
        del self.undo[:-UNDO_KEEP]

    async def restore(self, snap: dict):
        """Puts a snapshot back. The same song still playing: only what's up next changes.
        Otherwise the snapshot's song resumes where it was (what played since stays behind it)."""
        q = [dict(t) for t in snap["queue"]]
        self.seed, self.seed_gen = snap.get("seed"), self.seed_gen + 1
        cur = self.current
        if q and cur and cur["videoId"] == q[0]["videoId"]:
            self.queue[self.index + 1:] = q[1:]
            await self.sync_armed()
        elif not q:
            await self.stop()
        else:
            keep = self.queue[:self.index + 1] if cur else []
            await self.disarm()
            self.queue = keep + q
            asyncio.get_running_loop().create_task(self.play_index(len(keep), start=snap.get("position") or 0))

    # ---------- sleep timer and alarm ----------
    async def set_sleep(self, minutes: float | None = None, track: bool = False):
        if track:
            await self.disarm()               # no gapless hand-over: playback stops after this track
            self.sleep = {"mode": "track"}
        elif minutes and minutes > 0:
            minutes = min(minutes, 24 * 60)
            self.sleep = {"until": time.time() + minutes * 60, "minutes": minutes}
        else:
            await self.end_sleep()

    async def end_sleep(self):
        self.sleep = None
        if self.fade_db and not self.ramp:
            self.fade_db = 0.0
            await self.apply_volume()

    def sleep_left(self) -> float | None:
        s, p = self.sleep, self.mpv.props
        if not s:
            return None
        if s.get("mode") == "track":
            return max(0.0, (p.get("duration") or 0) - (p.get("time-pos") or 0))
        return max(0.0, s["until"] - time.time())

    async def _volume_loop(self):
        """Drives the sleep fade-out and the alarm ramp-up (4 steps a second)."""
        while True:
            await asyncio.sleep(0.25)
            try:
                await self._volume_tick()
            except Exception:
                pass

    async def _volume_tick(self):
        target = 0.0
        if self.ramp:
            start, secs = self.ramp
            frac = (time.time() - start) / secs
            if frac >= 1:
                self.ramp = None
            else:
                target = -VOL_RANGE_DB * (1 - frac)
        if self.sleep:
            left, fade = self.sleep_left(), TRACK_FADE if self.sleep.get("mode") == "track" else SLEEP_FADE
            paused = self.mpv.props.get("pause") or self.mpv.props.get("idle-active")
            if self.sleep.get("mode") != "track" and left <= 0:
                await self.mpv.send("set_property", "pause", True)
                self.sleep, self.ramp = None, None
                target = 0.0
            elif left < fade and not (paused and self.sleep.get("mode") == "track"):
                target = min(target, -VOL_RANGE_DB * (1 - left / fade))
        if abs(target - self.fade_db) > 0.05:
            self.fade_db = target
            await self.apply_volume()

    async def _alarm_loop(self):
        while True:
            await asyncio.sleep(15)
            try:                              # nothing may end this loop, or the alarm never rings again
                a = settings["alarm"]
                try:
                    now = datetime.datetime.now(ZoneInfo(a.get("tz") or "UTC"))
                except Exception:
                    now = datetime.datetime.now()
                stamp = now.strftime("%Y-%m-%d") + " " + a["time"]
                if a["enabled"] and now.weekday() in a["days"] and now.strftime("%H:%M") == a["time"] and a.get("last") != stamp:
                    a["last"] = stamp
                    save_settings()
                    await self.fire_alarm()
            except Exception as exc:
                self.error = f"Alarm failed: {exc}"[:200]

    async def fire_alarm(self, ramp_s: float | None = None):
        a = settings["alarm"]
        self.sleep = None
        settings["volume"] = a.get("level") or settings["volume"]
        save_settings()
        self.ramp = (time.time(), ramp_s or max(0.2, float(a.get("ramp") or 0)) * 60)
        self.fade_db = -VOL_RANGE_DB
        await self.apply_volume()
        tracks = (playlists.get(a.get("list") or "") or {}).get("tracks")
        if tracks:
            await self.play_tracks(tracks, 0, radio=True)
        elif self.current and self.mpv.props.get("idle-active"):
            await self.play_index(self.index, self.resume_at)
        elif self.current:
            await self.mpv.send("set_property", "pause", False)
        elif history:
            await self.play_tracks([dict(history[0])], 0, radio=True)

    def state(self):
        p = self.mpv.props
        left = self.sleep_left()
        return {
            "current": self.current, "index": self.index,
            "queue": self.queue[max(self.index, 0):max(self.index, 0) + 60],
            "offset": max(self.index, 0),
            "paused": bool(p.get("pause")), "position": p.get("time-pos") or 0,
            "duration": p.get("duration") or 0, "volume": settings["volume"],
            "loading": self.loading, "error": self.error,
            "idle": bool(p.get("idle-active")),
            "sleep": None if left is None else {"mode": self.sleep.get("mode", "timer"), "left": round(left),
                                                 "minutes": self.sleep.get("minutes")},
            "alarm": bool(settings["alarm"]["enabled"]), "ramping": bool(self.ramp), "listsRev": lists_rev,
            "peopleRev": people_rev, "userCount": self.user_end() - max(self.index, 0) - 1 if self.current else 0,
            "seed": self.seed, "turns": settings["turns"],
            "undo": {"n": len(self.undo), "label": self.undo[-1]["label"]} if self.undo else None,
            **({"paused": True, "position": self.resume_at} if p.get("idle-active") and not self.loading else {}),
        }


player = Player()


@asynccontextmanager
async def lifespan(_app):
    await player.start()
    yield
    player.save_session()
    save_stats()
    await player.mpv.quit()


app = FastAPI(title="Tunebox", lifespan=lifespan)


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


@app.middleware("http")
async def same_site_only(request: Request, call_next):
    """Refuses foreign Host headers, writes from foreign pages (Origin), and non-JSON bodies
    (a foreign page can send text/plain or form bodies without a CORS preflight)."""
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
        if has_body and not request.headers.get("content-type", "").lower().startswith("application/json"):
            return JSONResponse({"detail": "Send JSON"}, 415)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def bad_body(_request, exc: RequestValidationError):
    # FastAPI's own 422 echoes the input back, and a NaN in it can't be written as JSON (a 500 instead)
    first = (exc.errors() or [{}])[0]
    where = ".".join(str(x) for x in first.get("loc", ())[1:]) or "request"
    return JSONResponse({"detail": f"{where}: {first.get('msg', 'invalid')}"}, 422)


@app.exception_handler(PlayerDown)
async def player_down(_request, _exc):
    return JSONResponse({"detail": "Player is restarting"}, 503)


@app.get("/")
def index(request: Request):
    classic = request.cookies.get("tb_ui") == "classic"
    return FileResponse(HERE / ("classic.html" if classic else "index.html"),
                        headers={"Cache-Control": "no-cache", "Vary": "Cookie"})


@app.get("/bauhaus")
def bauhaus():
    return FileResponse(HERE / "index.html")


@app.get("/classic")
def classic():
    return FileResponse(HERE / "classic.html")


@app.get("/wall")
def wall():
    """The wall screen: a tablet or TV showing what plays."""
    return FileResponse(HERE / "wall.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
async def state():
    return player.state()


async def yt_get(what: str, fn, *args, **kw):
    """A YouTube Music lookup; a bad or gone ID (or YouTube failing) becomes a readable 404/502, not a 500."""
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except (YTMusicUserError, KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise HTTPException(404, f"Couldn't find that {what} on YouTube Music")
    except Exception as e:
        if "404" in str(e) or "400" in str(e):
            raise HTTPException(404, f"Couldn't find that {what} on YouTube Music")
        raise HTTPException(502, f"YouTube Music didn't answer: {str(e)[:120]}")


@app.get("/api/search")
async def search(q: str, kind: str = "songs"):
    if not q.strip():
        return []
    filt = kind if kind in ("songs", "albums", "artists", "playlists") else "songs"
    res = await yt_get("search", yt.search, q, filter=filt, limit=30)
    out = []
    for r in res:
        thumbs = r.get("thumbnails") or []
        if filt == "songs":
            t = track_from(r)
            if t:
                out.append({"type": "song", **t})
        elif filt == "albums":
            out.append({"type": "album", "id": r.get("browseId"), "title": r.get("title"),
                        "subtitle": ", ".join(a["name"] for a in r.get("artists") or []) + (f" · {r['year']}" if r.get("year") else ""),
                        "thumb": thumbs[-1]["url"] if thumbs else ""})
        elif filt == "artists":
            out.append({"type": "artist", "id": r.get("browseId"), "title": r.get("artist"),
                        "subtitle": "Artist", "thumb": thumbs[-1]["url"] if thumbs else ""})
        else:
            out.append({"type": "playlist", "id": r.get("browseId"), "title": r.get("title"),
                        "subtitle": r.get("author") or "Playlist", "thumb": thumbs[-1]["url"] if thumbs else ""})
    return [o for o in out if o.get("videoId") or o.get("id")]


@app.get("/api/home")
async def home():
    shelves = await asyncio.to_thread(yt.get_home, limit=6)
    out = []
    for shelf in shelves:
        items = []
        for c in shelf.get("contents", []):
            thumbs = c.get("thumbnails") or []
            thumb = thumbs[-1]["url"] if thumbs else ""
            if c.get("videoId"):
                t = track_from(c)
                items.append({"type": "song", **t})
            elif c.get("playlistId") or (c.get("browseId") or "").startswith(("VL", "RD", "PL")):
                items.append({"type": "playlist", "id": c.get("playlistId") or c.get("browseId"),
                              "title": c.get("title"), "subtitle": c.get("description") or "", "thumb": thumb})
            elif (c.get("browseId") or "").startswith("MPRE"):
                items.append({"type": "album", "id": c["browseId"], "title": c.get("title"),
                              "subtitle": c.get("year") or "", "thumb": thumb})
        if items:
            out.append({"title": shelf.get("title"), "items": items[:12]})
    return out


@app.get("/api/album/{browse_id}")
async def album(browse_id: str):
    a = await yt_get("album", yt.get_album, browse_id)
    thumbs = a.get("thumbnails") or []
    tracks = [t for t in (track_from({**x, "album": a.get("title"), "thumbnails": x.get("thumbnails") or thumbs})
                          for x in a.get("tracks", [])) if t]
    return {"title": a.get("title"), "subtitle": ", ".join(x["name"] for x in a.get("artists") or []),
            "thumb": thumbs[-1]["url"] if thumbs else "", "tracks": tracks}


@app.get("/api/playlist/{playlist_id}")
async def playlist(playlist_id: str):
    pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
    if pid.startswith("RD") and not pid.startswith("RDCLAK"):      # a radio mix; RDCLAK are curated playlists
        w = await yt_get("mix", yt.get_watch_playlist, playlistId=pid, limit=50)
        tracks = [t for t in map(track_from, w.get("tracks", [])) if t]
        return {"title": "Mix", "subtitle": "YouTube Music mix", "thumb": tracks[0]["thumb"] if tracks else "", "tracks": tracks}
    p = await yt_get("playlist", yt.get_playlist, pid, limit=100)
    thumbs = p.get("thumbnails") or []
    tracks = [t for t in map(track_from, p.get("tracks", [])) if t]
    return {"title": p.get("title"), "subtitle": (p.get("author") or {}).get("name", "") if isinstance(p.get("author"), dict) else "",
            "thumb": thumbs[-1]["url"] if thumbs else "", "tracks": tracks}


@app.get("/api/artist/{channel_id}")
async def artist(channel_id: str):
    a = await yt_get("artist", yt.get_artist, channel_id)
    thumbs = a.get("thumbnails") or []
    songs = [t for t in map(track_from, (a.get("songs") or {}).get("results", [])) if t]
    albums = [{"type": "album", "id": x.get("browseId"), "title": x.get("title"), "subtitle": x.get("year") or "",
               "thumb": (x.get("thumbnails") or [{}])[-1].get("url", "")}
              for x in (a.get("albums") or {}).get("results", [])]
    return {"title": a.get("name"), "subtitle": "Artist", "thumb": thumbs[-1]["url"] if thumbs else "",
            "tracks": songs, "albums": albums}


# ---------- links, explore, moods ----------
YT_ID = re.compile(r"[\w-]{2,80}")
browse_cache: dict[str, tuple[float, object]] = {}


async def cached(key: str, fn, ttl: float = 3600):
    """YouTube Music's explore pages change slowly: fetch them at most once an hour."""
    hit = browse_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = await fn()
    browse_cache[key] = (time.time(), data)
    return data


@app.get("/api/resolve")
async def resolve(url: str):
    """A pasted YouTube / YouTube Music link: which album, playlist, artist or song it points to."""
    raw = url.strip()
    try:
        u = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    except ValueError:
        raise HTTPException(400, "That isn't a link")
    host = (u.hostname or "").lower()
    if host != "youtu.be" and not host.endswith("youtube.com"):
        raise HTTPException(400, "Only YouTube and YouTube Music links work here")
    qs = urllib.parse.parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    vid = (qs.get("v") or [None])[0]
    if host == "youtu.be" and parts:
        vid = parts[0]
    elif len(parts) > 1 and parts[0] in ("shorts", "live", "embed"):
        vid = parts[1]
    lst = (qs.get("list") or [None])[0]
    kind, ident = None, None
    if len(parts) > 1 and parts[0] in ("browse", "channel"):
        b = parts[1]
        kind, ident = ("album", b) if b.startswith("MPRE") else ("artist", b) if b.startswith("UC") else ("playlist", b)
    elif lst and (not vid or parts[:1] == ["playlist"]):
        kind, ident = "playlist", lst
    elif lst and (not lst.startswith("RD") or lst.startswith("RDCLAK")):   # a song played from a playlist or album
        kind, ident = "playlist", lst                          # (RD… on a song link is just its radio: the song wins)
    elif vid:
        kind, ident = "song", vid
    if not kind or not YT_ID.fullmatch(ident or ""):
        raise HTTPException(400, "That link doesn't point to a song, album, playlist or artist")
    if kind == "playlist" and ident.startswith("OLAK5uy_"):   # an album's playlist: open the album itself
        try:
            ident = await asyncio.to_thread(yt.get_album_browse_id, ident) or ident
        except Exception:
            pass
        if ident.startswith("MPRE"):
            kind = "album"
    if kind != "song":
        return {"type": kind, "id": ident}
    try:
        w = await asyncio.to_thread(yt.get_watch_playlist, ident, limit=1)
        t = track_from((w.get("tracks") or [{}])[0])
    except Exception:
        t = None
    if not t:
        raise HTTPException(404, "Couldn't find that song")
    return {"type": "song", "track": t}


def album_card(x: dict) -> dict:
    return {"type": "album", "id": x.get("browseId"), "title": x.get("title"),
            "subtitle": ", ".join(a["name"] for a in x.get("artists") or [] if a.get("name")),
            "thumb": (x.get("thumbnails") or [{}])[-1].get("url", "")}


@app.get("/api/explore")
async def explore():
    """New releases (albums) and the moods & genres to browse."""
    async def fetch():
        ex, moods = await asyncio.gather(asyncio.to_thread(yt.get_explore), asyncio.to_thread(yt.get_mood_categories))
        releases = [album_card(x) for x in ex.get("new_releases") or [] if x.get("browseId")]
        groups = [{"title": k, "items": [{"title": m["title"], "params": m["params"]} for m in v if m.get("params")]}
                  for k, v in moods.items()]
        return {"releases": releases, "moods": [g for g in groups if g["items"]]}
    return await cached("explore", fetch)


@app.get("/api/mood")
async def mood(params: str):
    if not re.fullmatch(r"[\w=%-]{4,200}", params):
        raise HTTPException(400, "bad mood")

    async def fetch():
        pls = await asyncio.to_thread(yt.get_mood_playlists, params)
        def sub(p):
            a = p.get("author")
            return ", ".join(x.get("name", "") for x in a) if isinstance(a, list) else p.get("description") or ""
        return [{"type": "playlist", "id": p["playlistId"], "title": p.get("title"), "subtitle": sub(p),
                 "thumb": (p.get("thumbnails") or [{}])[-1].get("url", "")}
                for p in pls[:60] if p.get("playlistId")]
    return await cached("mood:" + params, fetch)


# ---------- for you: shelves from what the house plays and likes ----------
@app.get("/api/forme")
async def for_me():
    now = time.time()
    counts = []
    for vid, s in stats.items():
        recent = [t for t in s["plays"] if now - t < STATS_DAYS * 86400]
        if recent:
            counts.append((len(recent), max(recent), s["track"]))
    counts.sort(key=lambda c: (-c[0], -c[1]))
    most = [c[2] for c in counts[:24]]
    likes = [{k: t.get(k, "") for k in TRACK_KEYS} for t in playlists[LIKED_ID]["tracks"]]
    random.shuffle(likes)
    shelves = []
    if most:
        shelves.append({"key": "most", "title": "Most played", "subtitle": f"The house, last {STATS_DAYS} days", "items": most})
    if likes:
        shelves.append({"key": "likedmix", "title": "Liked mix", "subtitle": "Everyone's likes, shuffled", "items": likes[:30]})
    seeds = [c[2]["videoId"] for c in counts[:5]] or [t["videoId"] for t in likes[:5]]
    if seeds:
        seed = random.choice(seeds)
        mix = await cached("housemix:" + seed, lambda: player.radio_for(seed, 40))
        if mix:
            shelves.append({"key": "housemix", "title": "House mix", "subtitle": "New songs like the ones you play", "items": mix[:30]})
    return shelves


class PlayBody(BaseModel):
    tracks: list[dict]
    start: int = 0
    mode: str = "replace"                     # add | next | now | replace (see Player.add / Player.replace)
    label: str | None = None                  # what was added, for the undo list ("Album name")
    radio: bool = True                        # older pages: ignored (the radio always follows)
    similar: bool = False
    shuffle: bool = False


class QueueBody(BaseModel):                   # older pages; new ones use /api/play with a mode
    track: dict
    next: bool = False


class ControlBody(BaseModel):
    action: str
    value: float | None = None
    videoId: str | None = None                # jump/remove/move: the track the client saw at `value`
    to: int | None = None                     # move: its new queue index
    id: str | None = None                     # restore: the snapshot


def queue_at(i: int, vid: str | None) -> int:
    """The queue index a client meant; 409 when the queue moved under it."""
    if not 0 <= i < len(player.queue) or (vid is not None and player.queue[i]["videoId"] != vid):
        raise HTTPException(409, "The queue changed, try again")
    return i


def nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


@app.post("/api/play")
async def play(body: PlayBody, request: Request):
    by = need_who(request)
    tracks = [t for t in map(clean_track, body.tracks) if t]
    if not tracks:
        raise HTTPException(400, "no tracks")
    label = (body.label or "").strip()[:60]
    if body.mode in ("add", "next", "now"):
        pos = await player.add(tracks, by, body.mode, f'Added "{label}"' if label else "")
        msg = ("Playing now" if pos == 0 else "Plays next" if pos == 1 or body.mode == "next" else f"Added · {nth(pos)} in queue")
        return {"ok": True, "position": pos, "message": msg}
    if body.mode != "replace":
        raise HTTPException(400, "unknown mode")
    asyncio.get_running_loop().create_task(player.replace(tracks, body.start, by, f'Played "{label}"' if label else ""))
    return {"ok": True, "message": f'Playing "{label}"' if label else "Playing"}


@app.post("/api/queue")
async def enqueue(body: QueueBody, request: Request):
    by = need_who(request)
    track = clean_track(body.track)
    if not track:
        raise HTTPException(400, "not a track")
    pos = await player.add([track], by, "next" if body.next else "add")
    return {"ok": True, "position": pos}


@app.get("/api/queue/history")
async def queue_history():
    """Earlier queues (undo snapshots), newest first."""
    return [{"id": s["id"], "label": s["label"], "by": s["by"], "at": s["at"], "count": len(s["queue"]),
             "current": s["queue"][0]["title"] if s["queue"] else "", "thumb": s["queue"][0]["thumb"] if s["queue"] else ""}
            for s in reversed(player.undo)]


@app.post("/api/control")
async def control(body: ControlBody, request: Request):
    a, v, by = body.action, body.value, who(request)
    p = player
    msg = ""
    if a == "toggle":
        if p.mpv.props.get("idle-active") and p.current:
            asyncio.get_running_loop().create_task(p.play_index(p.index, p.resume_at))
        else:
            await p.mpv.send("cycle", "pause")
    elif a == "next":
        asyncio.get_running_loop().create_task(p.play_index(step=1))
    elif a == "prev":
        if (p.mpv.props.get("time-pos") or 0) > 5 or p.index == 0:
            await p.mpv.send("seek", 0, "absolute")
        else:
            asyncio.get_running_loop().create_task(p.play_index(step=-1))
    elif a == "seek" and v is not None:
        await p.mpv.send("seek", v, "absolute")
    elif a == "volume" and v is not None:
        settings["volume"] = round(max(0, min(100, v)))
        if p.ramp:                            # touching the volume ends an alarm ramp
            p.ramp, p.fade_db = None, 0.0
        await p.apply_volume()
        save_settings()
    elif a == "jump" and v is not None:
        i = queue_at(int(v), body.videoId)
        asyncio.get_running_loop().create_task(p.play_index(i, vid=body.videoId))
    elif a == "remove" and v is not None:
        i = queue_at(int(v), body.videoId)
        if p.index < i < len(p.queue):
            p.snapshot(f'Removed "{p.queue[i]["title"]}"', by)
            p.queue.pop(i)
            msg = "Removed"
    elif a in ("move", "promote") and v is not None:
        # move: to a new place (dropped among the added songs it counts as added, among the radio as radio);
        # promote: a song to the front of the added songs ("play next", from the queue itself)
        i = queue_at(int(v), body.videoId)
        if i <= p.index:
            raise HTTPException(400, "Only songs that are up next can be moved")
        t = p.queue[i]
        p.snapshot(f'Moved "{t["title"]}"', by)
        p.queue.pop(i)
        to = p.index + 1 if a == "promote" else max(p.index + 1, min(int(body.to if body.to is not None else i), len(p.queue)))
        if to <= p.user_end():
            if t.get("src") != "user":
                t.update(src="user", by=by)
        else:
            t["src"] = "auto"
        p.queue.insert(to, t)
        msg = "Plays next" if a == "promote" else ""
    elif a == "shuffle":                      # the songs people added; the radio stays after them
        end = p.user_end()
        rest = p.queue[p.index + 1:end]
        if len(rest) > 1:
            p.snapshot("Shuffled up next", by)
            random.shuffle(rest)
            p.queue[p.index + 1:end] = rest
            msg = "Shuffled"
    elif a == "clear":                        # the songs people added; the radio keeps going
        end = p.user_end()
        if end > p.index + 1:
            p.snapshot("Cleared up next", by)
            del p.queue[p.index + 1:end]
            msg = "Cleared"
    elif a == "clear_auto":
        end = p.user_end()
        if end < len(p.queue):
            p.snapshot("Cleared the radio", by)
            del p.queue[end:]
            p.seed, p.seed_gen = None, p.seed_gen + 1
            msg = "Radio cleared"
    elif a == "refresh":
        seed = p.seed or p.current
        if seed:
            p.snapshot("New radio songs", by)
            p.seed, p.seed_gen = {k: seed.get(k, "") for k in ("videoId", "title", "artist", "thumb")}, p.seed_gen + 1
            await p._reseed(p.seed_gen, fresh=True)
            msg = "New radio songs"
    elif a == "stop":
        if p.current:
            p.snapshot("Stopped", by)
        await p.stop()
    elif a == "undo":
        if not p.undo:
            raise HTTPException(400, "Nothing to undo")
        snap = p.undo.pop()
        await p.restore(snap)
        msg = f"Undone: {snap['label']}"
    elif a == "restore":
        snap = next((s for s in p.undo if s["id"] == body.id), None)
        if not snap:
            raise HTTPException(404, "That queue is gone")
        p.snapshot("Before restoring an earlier queue", by)
        await p.restore(snap)
        msg = "Restored"
    else:
        raise HTTPException(400, "unknown action")
    await p.sync_armed()
    return {"ok": True, "message": msg}


class EqBody(BaseModel):
    preset: str
    custom: list[float] | None = None


class AccountBody(BaseModel):
    headers: str


def account_status() -> dict:
    return {"signedIn": AUTH_FILE.exists()}


@app.get("/api/settings")
async def get_settings():
    return {"volume": settings["volume"], "eq": settings["eq"], "bands": eq_bands(),
            "freqs": EQ_FREQS, "presets": EQ_PRESETS, "account": account_status(),
            "normalize": settings["normalize"], "autoplay": settings["autoplay"], "turns": settings["turns"],
            "quality": settings["quality"], "qualities": list(QUALITY), "alarm": settings["alarm"],
            "lists": [list_summary(p) for p in sorted_lists()]}


class OptionsBody(BaseModel):
    normalize: bool | None = None
    autoplay: bool | None = None
    turns: bool | None = None
    quality: str | None = None


@app.post("/api/options")
async def set_options(body: OptionsBody):
    if body.quality is not None and body.quality not in QUALITY:
        raise HTTPException(400, "unknown quality")
    if body.autoplay is not None:
        settings["autoplay"] = body.autoplay
        if body.autoplay:
            asyncio.get_running_loop().create_task(player.refill())
    if body.quality is not None and body.quality != settings["quality"]:
        settings["quality"] = body.quality

        def switch():
            with ydl_lock:
                ydl.params["format"] = QUALITY[body.quality]
        await asyncio.to_thread(switch)
        player.resolver.cache.clear()         # the next tracks resolve at the new quality
    if body.turns is not None:
        settings["turns"] = body.turns
    if body.normalize is not None:
        settings["normalize"] = body.normalize
        await player.mpv.apply_eq()
    save_settings()
    return await get_settings()


class SleepBody(BaseModel):
    minutes: float | None = None
    track: bool = False


@app.post("/api/sleep")
async def set_sleep(body: SleepBody):
    await player.set_sleep(body.minutes, body.track)
    return player.state()["sleep"] or {}


class AlarmBody(BaseModel):
    enabled: bool
    time: str
    days: list[int]
    list: str | None = None
    level: int = 45
    ramp: float = 5
    tz: str = "Europe/Belgrade"
    test: bool = False


@app.post("/api/alarm")
async def set_alarm(body: AlarmBody):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.time):
        raise HTTPException(400, "time must be HH:MM")
    try:
        ZoneInfo(body.tz)
    except Exception:
        raise HTTPException(400, "unknown time zone")
    a = settings["alarm"]
    a.update(enabled=body.enabled, time=body.time, days=sorted({d for d in body.days if 0 <= d <= 6}),
             list=body.list if body.list in playlists else None, level=max(1, min(100, body.level)),
             ramp=max(0, min(30, body.ramp)), tz=body.tz)
    save_settings()
    if body.test:
        await player.fire_alarm(ramp_s=TEST_RAMP)   # the full ramp starts 50 dB down: minutes of near-silence
    return await get_settings()


# ---------- history ----------
@app.get("/api/history")
async def get_history(limit: int = 100):
    return history[:max(1, min(limit, HISTORY_MAX))]


@app.delete("/api/history")
async def clear_history():
    history.clear()
    write_json(HISTORY_FILE, history)
    return {"ok": True}


# ---------- lyrics: LRCLIB (free, open, often time-synced) with YouTube Music as fallback ----------
lyrics_cache: dict[str, dict] = {}
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def secs(duration: str) -> int:
    try:
        n = 0
        for part in str(duration).split(":"):
            n = n * 60 + int(part)
        return n
    except ValueError:
        return 0


def clean_title(t: str) -> str:
    t = re.sub(r"\s*[\(\[][^)\]]*(remaster|version|live|edit|mix|mono|stereo|feat\.?|ft\.)[^)\]]*[\)\]]", "", t, flags=re.I)
    return re.sub(r"\s+-\s+.*(remaster|version|edit).*$", "", t, flags=re.I).strip()


def lrclib(path: str, params: dict):
    url = f"https://lrclib.net/api/{path}?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    req = urllib.request.Request(url, headers={"User-Agent": "Tunebox/1.0 (home music server)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def parse_lrc(text: str) -> list:
    out = []
    for line in text.splitlines():
        m = LRC_LINE.match(line.strip())
        if m:
            out.append([round(int(m[1]) * 60 + float(m[2]), 2), m[3].strip()])
    return out


def fetch_lyrics(vid: str, title: str, artist: str, album: str, duration: str) -> dict:
    artist1 = (artist or "").split(",")[0].strip()
    dur = secs(duration)
    hit = None
    try:
        hit = lrclib("get", {"track_name": title, "artist_name": artist1, "album_name": album, "duration": dur})
        if not hit or not (hit.get("syncedLyrics") or hit.get("plainLyrics")):
            found = lrclib("search", {"track_name": clean_title(title), "artist_name": artist1}) or []
            found = [f for f in found if f.get("syncedLyrics") or f.get("plainLyrics")]
            found.sort(key=lambda f: (not f.get("syncedLyrics"), abs((f.get("duration") or 0) - dur) if dur else 0))
            hit = found[0] if found and (not dur or abs((found[0].get("duration") or 0) - dur) < 15) else None
    except Exception:
        hit = None
    if hit and hit.get("instrumental"):
        return {"instrumental": True, "source": "LRCLIB"}
    if hit:
        synced = parse_lrc(hit.get("syncedLyrics") or "")
        return {"synced": synced or None, "plain": hit.get("plainLyrics") or "", "source": "LRCLIB"}
    try:
        w = yt.get_watch_playlist(vid, limit=1)
        if w.get("lyrics"):
            l = yt.get_lyrics(w["lyrics"])
            if l and l.get("lyrics"):
                return {"synced": None, "plain": l["lyrics"], "source": l.get("source") or "YouTube Music"}
    except Exception:
        pass
    return {"none": True}


@app.get("/api/lyrics")
async def lyrics(videoId: str, title: str = "", artist: str = "", album: str = "", duration: str = ""):
    if videoId not in lyrics_cache:
        res = await asyncio.to_thread(fetch_lyrics, videoId, title, artist, album, duration)
        if len(lyrics_cache) > 300:
            lyrics_cache.clear()
        lyrics_cache[videoId] = res
    return lyrics_cache[videoId]


# ---------- Tunebox playlists: one shared set for the whole house ----------
lists_lock = asyncio.Lock()
TRACK_KEYS = ("videoId", "title", "artist", "album", "duration", "thumb")


def clean_track(t: dict) -> dict | None:
    if not isinstance(t, dict) or not t.get("videoId"):
        return None
    return {k: str(t.get(k) or "")[:300] for k in TRACK_KEYS}


def save_lists():
    global lists_rev
    lists_rev += 1
    write_json(LISTS_FILE, playlists)


def sorted_lists():
    return sorted(playlists.values(), key=lambda p: (p["id"] != LIKED_ID, -p["updated"]))


def list_summary(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "count": len(p["tracks"]), "updated": p["updated"],
            "thumbs": [t["thumb"] for t in p["tracks"][:4]], "liked": p["id"] == LIKED_ID}


def get_list(list_id: str) -> dict:
    if list_id not in playlists:
        raise HTTPException(404, "No such playlist")
    return playlists[list_id]


class ListBody(BaseModel):
    name: str | None = None
    tracks: list[dict] | None = None
    fromQueue: bool = False


class ListTrackBody(BaseModel):
    track: dict


class LikeBody(BaseModel):
    track: dict
    liked: bool


class ListEditBody(BaseModel):
    op: str                                   # "move" or "remove"
    videoId: str
    at: int | None = None                     # where the client saw it (tells duplicates apart)
    to: int | None = None                     # move: the new position


@app.get("/api/lists")
async def all_lists():
    return [list_summary(p) for p in sorted_lists()]


@app.post("/api/lists")
async def create_list(body: ListBody):
    name = (body.name or "").strip()[:80] or "New playlist"
    src = player.queue[max(player.index, 0):] if body.fromQueue else (body.tracks or [])
    async with lists_lock:
        pid = secrets.token_hex(4)
        now = int(time.time())
        playlists[pid] = {"id": pid, "name": name, "tracks": [t for t in map(clean_track, src) if t],
                          "created": now, "updated": now}
        save_lists()
    return playlists[pid]


@app.get("/api/lists/{list_id}")
async def one_list(list_id: str):
    return get_list(list_id)


@app.patch("/api/lists/{list_id}")
async def edit_list(list_id: str, body: ListBody):
    async with lists_lock:
        p = get_list(list_id)
        if body.name is not None and body.name.strip() and list_id != LIKED_ID:
            p["name"] = body.name.strip()[:80]
        if body.tracks is not None:
            p["tracks"] = [t for t in map(clean_track, body.tracks) if t]
        p["updated"] = int(time.time())
        save_lists()
    return p


@app.patch("/api/lists/{list_id}/tracks")
async def edit_list_tracks(list_id: str, body: ListEditBody):
    """Moves or removes one song by videoId, so edits from two devices don't undo each other."""
    async with lists_lock:
        p = get_list(list_id)
        ts = p["tracks"]
        i = body.at
        if i is None or not 0 <= i < len(ts) or ts[i]["videoId"] != body.videoId:
            i = next((k for k, t in enumerate(ts) if t["videoId"] == body.videoId), None)
        if i is None:
            raise HTTPException(404, "That song is no longer in the playlist")
        if body.op == "remove":
            ts.pop(i)
        elif body.op == "move" and body.to is not None:
            ts.insert(max(0, min(len(ts) - 1, body.to)), ts.pop(i))
        else:
            raise HTTPException(400, "unknown op")
        p["updated"] = int(time.time())
        save_lists()
    return p


@app.post("/api/lists/{list_id}/tracks")
async def add_to_list(list_id: str, body: ListTrackBody):
    t = clean_track(body.track)
    if not t:
        raise HTTPException(400, "not a track")
    async with lists_lock:
        p = get_list(list_id)
        dup = any(x["videoId"] == t["videoId"] for x in p["tracks"])
        if not dup:
            p["tracks"].insert(0 if list_id == LIKED_ID else len(p["tracks"]), t)   # newest like first
            p["updated"] = int(time.time())
            save_lists()
    return {"ok": True, "duplicate": dup, "count": len(p["tracks"])}


@app.post("/api/like")
async def like(body: LikeBody, request: Request):
    """Adds the song to the top of Liked songs, or takes it out. The list is shared; likedBy
    remembers who liked each song (liking an already liked song adds your name)."""
    t = clean_track(body.track)
    if not t:
        raise HTTPException(400, "not a track")
    by = who(request)
    async with lists_lock:
        p = playlists[LIKED_ID]
        have = next((x for x in p["tracks"] if x["videoId"] == t["videoId"]), None)
        if body.liked and have is None:
            p["tracks"].insert(0, {**t, "likedBy": [by] if by else []})
        elif body.liked and by and by not in have.setdefault("likedBy", []):
            have["likedBy"].append(by)
        elif not body.liked and have is not None:
            p["tracks"] = [x for x in p["tracks"] if x["videoId"] != t["videoId"]]
        else:
            return {"liked": body.liked, "count": len(p["tracks"])}
        p["updated"] = int(time.time())
        save_lists()
    return {"liked": body.liked, "count": len(p["tracks"])}


@app.delete("/api/lists/{list_id}")
async def delete_list(list_id: str):
    if list_id == LIKED_ID:
        raise HTTPException(400, "Liked songs can't be deleted")
    async with lists_lock:
        get_list(list_id)
        del playlists[list_id]
        save_lists()
        if settings["alarm"].get("list") == list_id:
            settings["alarm"]["list"] = None
            save_settings()
    return {"ok": True}


# ---------- people: who's listening, picked per device, so the queue can show who added what ----------
people_lock = asyncio.Lock()
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def who(request: Request) -> str:
    """The person this device picked (cookie tb_who), or "" for nobody or a removed name."""
    pid = request.cookies.get("tb_who") or ""
    return pid if pid in people else ""


def need_who(request: Request) -> str:
    """Adding songs needs a name; the UI answers this 401 by showing its picker."""
    pid = who(request)
    if not pid:
        raise HTTPException(401, "pick")
    return pid


def save_people():
    global people_rev
    people_rev += 1
    write_json(PEOPLE_FILE, people)


class PersonBody(BaseModel):
    name: str | None = None
    color: str | None = None
    emoji: str | None = None


def person_fields(p: dict, body: PersonBody) -> None:
    if body.name is not None:
        name = " ".join(body.name.split())[:24]
        if not name:
            raise HTTPException(400, "Type a name")
        if any(q["name"].lower() == name.lower() and q["id"] != p.get("id") for q in people.values()):
            raise HTTPException(409, "That name is taken")
        p["name"] = name
    if body.color is not None:
        if not COLOR_RE.fullmatch(body.color):
            raise HTTPException(400, "bad colour")
        p["color"] = body.color.upper()
    if body.emoji is not None:
        e = body.emoji.strip()[:8]
        if any(ch.isascii() and ch not in "#*0123456789" for ch in e):   # emoji only (keycaps start with #, * or a digit)
            raise HTTPException(400, "Pick an emoji")
        p["emoji"] = e


@app.get("/api/people")
async def all_people():
    return sorted(people.values(), key=lambda p: p["name"].lower())


@app.post("/api/people")
async def add_person(body: PersonBody):
    async with people_lock:
        p = {"id": secrets.token_hex(4), "name": "", "color": "#1F5FBF", "emoji": ""}
        person_fields(p, PersonBody(name=body.name or "", color=body.color, emoji=body.emoji))
        people[p["id"]] = p
        save_people()
    return p


@app.patch("/api/people/{pid}")
async def edit_person(pid: str, body: PersonBody):
    async with people_lock:
        if pid not in people:
            raise HTTPException(404, "No such person")
        person_fields(people[pid], body)
        save_people()
    return people[pid]


@app.delete("/api/people/{pid}")
async def remove_person(pid: str):
    """Their songs stay where they are; they just show no name any more."""
    async with people_lock:
        people.pop(pid, None)
        save_people()
    return {"ok": True}


@app.post("/api/eq")
async def set_eq(body: EqBody):
    if body.preset != "custom" and body.preset not in EQ_PRESETS:
        raise HTTPException(400, "unknown preset")
    if body.custom is not None:
        if len(body.custom) != len(EQ_FREQS):
            raise HTTPException(400, "need 10 bands")
        settings["eq"]["custom"] = [round(max(-12, min(12, g)), 1) for g in body.custom]
    settings["eq"]["preset"] = body.preset
    save_settings()
    try:
        await player.mpv.apply_eq()
    except PlayerDown:
        raise
    except Exception as exc:
        raise HTTPException(500, f"mpv rejected the filter: {exc}")
    return await get_settings()


@app.post("/api/account")
async def set_account(body: AccountBody):
    """Accepts request headers copied from music.youtube.com, or just the Cookie value."""
    global yt
    raw = body.headers.strip().replace("\r", "")
    if not raw:
        raise HTTPException(400, "empty")
    lines = raw.split("\n")
    if not any(l.lower().startswith("cookie:") for l in lines):
        if len(lines) == 1 and "=" in raw:            # bare cookie string
            lines = [f"cookie: {raw}"]
        else:
            raise HTTPException(400, "No Cookie header found")
    if not any(l.lower().startswith("x-goog-authuser:") for l in lines):
        lines.append("x-goog-authuser: 0")
    cookie = next(l for l in lines if l.lower().startswith("cookie:"))
    if "SAPISID=" not in cookie:
        raise HTTPException(400, "That cookie has no SAPISID: copy it from music.youtube.com while signed in")
    if not any(l.lower().startswith("authorization:") for l in lines):
        lines.append("authorization: SAPISIDHASH 0_0")   # recomputed from the cookie on every request
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix="browser.", suffix=".new")   # unique, 0600 from the start
    os.close(fd)
    try:
        await asyncio.to_thread(yt_setup, tmp, "\n".join(lines))   # rewrites the file in place: stays 0600
        test = YTMusic(tmp)
        await asyncio.to_thread(test.get_library_playlists, 1)
    except Exception as exc:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(400, f"YouTube rejected these headers: {str(exc)[:160]}")
    os.replace(tmp, AUTH_FILE)
    yt = test
    return account_status()


@app.delete("/api/account")
async def clear_account():
    global yt
    AUTH_FILE.unlink(missing_ok=True)
    yt = YTMusic()
    return account_status()

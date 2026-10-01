"""The player: the queue (now playing, then the songs people added, then the radio), gapless
hand-over to mpv, undo snapshots, fades, the sleep timer and the wake-up alarm."""
import asyncio
import datetime
import json
import random
import secrets
import time

from . import blocklist, data, house, plays
from .audio import level_to_mpv
from .config import (FAIL_LIMIT, PAUSE_FADE, PLAYED_KEEP, PRELOAD_AT, RADIO_REFILL_AT, SESSION_EVERY,
                     SESSION_FILE, SKIP_GRACE, SLEEP_FADE, TRACK_FADE, UNDO_KEEP, UNDO_TRACKS, VOL_RANGE_DB)
from .files import read_json, write_json
from .mpv import Mpv
from .settings import save_settings, settings
from .youtube import Resolver, radio_for


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
        self.fading = asyncio.Event()         # wakes the volume loop, which sleeps while there's no sleep timer or ramp
        self.clock = asyncio.Event()          # wakes the alarm loop, which sleeps while there's no alarm or quiet hours
        self.restarting = False               # mpv is being restarted after a crash
        self.gen = 0                          # bumped by every play request; only the newest loads
        self.fails = 0                        # streams that failed in a row
        self.seed = None                      # the song the radio (auto songs) follows: the last added song to play
        self.seed_gen = 0                     # bumped on every re-seed; a radio that arrives late is dropped
        self.undo: list[dict] = []            # queue snapshots, oldest first
        self.pp_db = 0.0                      # play/pause fade, on top of fade_db
        self.pp_want: bool | None = None      # where a running play/pause fade is headed (True = playing)
        self.pp_gen = 0                       # bumped by every play/pause; an older fade stops stepping

    async def apply_volume(self):
        await self.mpv.send("set_property", "volume", level_to_mpv(settings["volume"], self.fade_db + self.pp_db))

    async def fade_toggle(self):
        """Play/pause with a short fade: out, then pause; or unpause silent, then in. Pressing again
        mid-fade turns it around from wherever the volume is."""
        self.pp_gen += 1
        gen = self.pp_gen
        play = (not self.pp_want) if self.pp_want is not None else bool(self.mpv.props.get("pause"))
        self.pp_want = play
        if play and self.mpv.props.get("pause"):
            if self.pp_db == 0:
                self.pp_db = -VOL_RANGE_DB
                await self.apply_volume()
            await self.mpv.send("set_property", "pause", False)
        target = 0.0 if play else -VOL_RANGE_DB
        start, t0 = self.pp_db, time.monotonic()
        span = PAUSE_FADE * abs(target - start) / VOL_RANGE_DB
        while span > 0:
            await asyncio.sleep(0.03)
            if gen != self.pp_gen:
                return                        # pressed again: the newer call carries on from here
            frac = min(1.0, (time.monotonic() - t0) / span)
            self.pp_db = start + (target - start) * frac
            await self.apply_volume()
            if frac >= 1:
                break
        if not play:
            await self.mpv.send("set_property", "pause", True)
        self.pp_db, self.pp_want = 0.0, None
        await self.apply_volume()

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
            data.save_stats()
            plays.flush()
            try:
                self.trim_played()
                now = self.session_data()
                now["position"] = round(now["position"])
                snap = json.dumps(now)       # a snapshot: the queue list itself is mutated in place
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
        saved = read_json(SESSION_FILE, None)
        try:
            self.queue, self.index = list(saved["queue"]), int(saved["index"])
            self.resume_at = float(saved.get("position") or 0)
            self.seed, self.undo = saved.get("seed"), list(saved.get("undo") or [])
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
        plays.seed()
        await self.mpv.start()
        loop = asyncio.get_running_loop()
        loop.create_task(self._preload_loop())
        loop.create_task(self._volume_loop())
        house.watchers.append(self.clock.set)
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
        self.pp_gen += 1                      # a play/pause fade cut short must not leave the volume down
        self.pp_db, self.pp_want = 0.0, None
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
        data.add_history(self.current)
        plays.begin(self.current)

    async def disarm(self):
        """Forgets the preloaded next track after the queue changed."""
        if self.armed:
            self.armed = None
            try:
                await self.mpv.send("playlist-clear")
            except Exception:
                pass

    async def _preload_loop(self):
        """Once a second while a song plays: the heard time, the next track's preload, the EQ. While nothing
        plays it bakes a live EQ change into the chain once, then sleeps until mpv starts or unpauses."""
        last = time.monotonic()
        while True:
            if self.mpv.props.get("pause") or self.mpv.props.get("idle-active"):
                try:
                    await self.mpv.eq_sync()
                except Exception:
                    pass
                self.mpv.stirred.clear()
                if self.mpv.props.get("pause") or self.mpv.props.get("idle-active"):
                    await self.mpv.stirred.wait()
                last = time.monotonic()
                continue
            await asyncio.sleep(1)
            now = time.monotonic()
            p = self.mpv.props
            if self.current and not (p.get("pause") or p.get("idle-active") or self.loading):
                plays.heard(self.current["videoId"], min(now - last, 5))   # what the play log counts as heard
            last = now
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

    def cut_short(self, how: str, by: str):
        """The song playing is about to be skipped (how "skip") or cut off by one played now ("cut"):
        the play log keeps who did it, for Stats. Paused counts; its last seconds, or nothing playing, don't."""
        p = self.mpv.props
        if not self.current or self.loading or p.get("idle-active"):
            return
        dur, pos = p.get("duration") or 0, p.get("time-pos") or 0
        if not dur or dur - pos > SKIP_GRACE:
            plays.mark(self.current["videoId"], how, by)

    async def stop(self):
        self.gen += 1                         # cancels a play request still resolving
        self.armed, self.cur_entry, self.loading = None, None, False
        plays.finish()
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
        now: in front, and the first one plays at once. The radio follows whichever added song now
        plays last (see follow). Returns the first song's place in the queue (1 = next, 0 = playing now)."""
        items = [{**t, "by": by, "src": "user", "at": int(time.time())} for t in tracks if not blocklist.blocked(t)]
        if not items:
            return 0
        self.snapshot(label or (f'Added "{items[0]["title"]}"' if len(items) == 1 else f"Added {len(items)} songs"), by)
        start_now = mode == "now" or self.finished()
        if mode == "now":
            self.cut_short("cut", by)
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
        self.follow(force=not self.queue[self.user_end():])    # no radio behind them yet: fetch it
        for t in items[:2]:
            self.resolver.prefetch(t["videoId"])
        return pos

    async def replace(self, tracks: list[dict], start: int = 0, by: str = "", label: str = ""):
        """Plays a list now; it becomes the songs up next (the radio follows its last song). What played
        before stays behind the current song, so Previous still goes back to it."""
        items = [{**t, "by": by, "src": "user", "at": int(time.time())} for t in tracks if t and not blocklist.blocked(t)]
        if not items:
            return
        self.snapshot(label or f'Played "{items[0]["title"]}"', by)
        self.cut_short("cut", by)
        keep = self.queue[:self.index + 1] if self.current else []
        await self.disarm()
        self.queue, self.fails = keep + items, 0   # a fresh run of FAIL_LIMIT tries
        self.reseed(items[-1])
        await self.play_index(len(keep) + max(0, min(start, len(items) - 1)))

    async def play_tracks(self, tracks: list[dict], start: int = 0):
        """The alarm's way in: replace the queue with a list."""
        await self.replace(tracks, start, label="Alarm")

    def follow(self, gone=(), force: bool = False):
        """Keeps the radio on the added song that plays last: the last one in the queue's order, not the
        newest one added (taking turns, Play next and Play now put a new song further up). Called after
        every change to the added songs. With none of them left it stays as it is, unless its own song
        was among the ones just taken out (`gone`): then it follows what is playing."""
        end = self.user_end()
        last = self.queue[end - 1] if end > 0 else None
        if not last or last.get("src") != "user":
            last = self.current if self.seed and any(t["videoId"] == self.seed["videoId"] for t in gone) else None
        if last and (force or not self.seed or last["videoId"] != self.seed["videoId"]):
            self.reseed(last)

    def reseed(self, track: dict, fill: bool = True):
        """The radio now follows `track`: its radio replaces the auto songs (in the background)."""
        self.seed = {k: str(track.get(k) or "") for k in ("videoId", "title", "artist", "thumb")}
        self.seed_gen += 1
        if fill and settings["autoplay"] and house.on("radio"):
            asyncio.get_running_loop().create_task(self._reseed(self.seed_gen))

    async def _reseed(self, gen: int, fresh: bool = False):
        """Replaces the auto songs with the seed's radio. fresh: avoid the songs it replaces (Refresh)."""
        items = await radio_for(self.seed["videoId"], 50 if fresh else 30)
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
        """Keeps the music going: when little is left, more radio of the seed (the added song that
        played last), or of the current song when the seed has nothing new."""
        if not (settings["autoplay"] or force) or not self.current or len(self.queue) - self.index > RADIO_REFILL_AT:
            return
        if not house.on("radio"):
            return
        gen = self.seed_gen
        for seed in (self.seed, self.current):
            if not seed:
                continue
            items = await radio_for(seed["videoId"])
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
        keep = self.index + 1                 # an earlier queue may hold songs blocked since
        self.queue[keep:] = [t for t in self.queue[keep:] if not blocklist.blocked(t)]

    async def drop_blocked(self, label: str) -> int:
        """Takes the songs the admin blocked out of what's up next; how many went."""
        keep = self.index + 1
        gone = [t for t in self.queue[keep:] if blocklist.blocked(t)]
        if gone:
            self.snapshot(label)
            self.queue[keep:] = [t for t in self.queue[keep:] if not blocklist.blocked(t)]
            await self.sync_armed()
            self.follow(gone)
        return len(gone)

    # ---------- sleep timer and alarm ----------
    async def set_sleep(self, minutes: float | None = None, track: bool = False):
        if track:
            await self.disarm()               # no gapless hand-over: playback stops after this track
            self.sleep = {"mode": "track"}
            self.fading.set()
        elif minutes and minutes > 0:
            minutes = min(minutes, 24 * 60)
            self.sleep = {"until": time.time() + minutes * 60, "minutes": minutes}
            self.fading.set()
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
        """Drives the sleep fade-out and the alarm ramp-up (4 steps a second). With neither set, and the
        volume back where it belongs, it sleeps until set_sleep or fire_alarm wakes it."""
        while True:
            if not (self.sleep or self.ramp or self.fade_db):
                self.fading.clear()
                await self.fading.wait()
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
        """Every 15 seconds: the quiet hours' volume cap, and the alarm. With no quiet hours set and no alarm
        on, it sleeps until a change to the house (save_house) or the alarm (api/alarm) wakes it."""
        while True:
            if not (house.house["quiet"]["hours"] or (house.on("alarm") and settings["alarm"]["enabled"])):
                self.clock.clear()
                await self.clock.wait()
            await asyncio.sleep(15)
            try:                              # the quiet hours began: a louder volume comes down to the cap
                cap = house.quiet_cap()
                if cap is not None and settings["volume"] > cap and not self.ramp:
                    settings["volume"] = cap
                    await self.apply_volume()
                    save_settings()
            except Exception:
                pass
            try:                              # nothing may end this loop, or the alarm never rings again
                a = settings["alarm"]
                now = datetime.datetime.now(house.tz())
                stamp = now.strftime("%Y-%m-%d") + " " + a["time"]
                if (a["enabled"] and house.on("alarm") and now.weekday() in a["days"] and now.strftime("%H:%M") == a["time"]
                        and a.get("last") != stamp):
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
        self.fading.set()
        await self.apply_volume()
        tracks = (data.playlists.get(a.get("list") or "") or {}).get("tracks")
        if tracks:
            await self.play_tracks(tracks)
        elif self.current and self.mpv.props.get("idle-active"):
            await self.play_index(self.index, self.resume_at)
        elif self.current:
            await self.mpv.send("set_property", "pause", False)
        elif data.history:
            await self.play_tracks([dict(data.history[0])])

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
            "alarm": bool(settings["alarm"]["enabled"]), "ramping": bool(self.ramp), "listsRev": data.lists_rev,
            "peopleRev": data.people_rev, "userCount": self.user_end() - max(self.index, 0) - 1 if self.current else 0,
            "seed": self.seed, "turns": settings["turns"],
            "undo": {"n": len(self.undo), "label": self.undo[-1]["label"]} if self.undo else None,
            **({"paused": True, "position": self.resume_at} if p.get("idle-active") and not self.loading else {}),
        }


player = Player()

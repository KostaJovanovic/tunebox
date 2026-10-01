"""A silent stand-in for mpv and yt-dlp, for server.bat --silent and for tests.

It is installed by patching the imported modules, never by editing them, so the code that
runs here is byte for byte the code that runs on the server.
"""
import asyncio
import time
from pathlib import Path


def _seconds(duration: str, default: float = 200.0) -> float:
    """"3:45" or "1:02:03" -> seconds."""
    try:
        parts = [int(p) for p in str(duration).split(":")]
    except ValueError:
        return default
    total = 0
    for p in parts:
        total = total * 60 + p
    return float(total) or default


def install_tunebox(speed: float = 1.0):
    """Replaces mpv with an in-process fake that keeps mpv's playlist, properties and
    events (start-file, file-loaded, end-file), and yt-dlp with instant fake URLs."""
    from tunebox import mpv, youtube
    from tunebox.player import player

    def extract(self, vid: str) -> str:
        time.sleep(0.3)                       # resolving takes a moment on ele too
        return f"fake://{vid}"
    youtube.Resolver._extract = extract

    def duration_of(url: str) -> float:
        vid = url.removeprefix("fake://")
        if vid == url:                        # a local song: the player was handed its file
            vid = "local:" + Path(url).stem
        for t in player.queue:
            if t["videoId"] == vid:
                return _seconds(t.get("duration"))
        return 200.0

    def event(self, **msg):
        self._dispatch(msg)

    def play_entry(self, i: int):
        self._cur = i
        e = self._pl[i]
        self.props.update({"idle-active": False, "time-pos": e["start"], "duration": e["dur"]})
        self.stirred.set()                    # real mpv reports idle-active as a property change
        event(self, event="start-file", playlist_entry_id=e["id"])
        asyncio.get_running_loop().call_later(0.2, lambda: event(self, event="file-loaded"))

    def finish(self, reason: str):
        """The current entry ends: tell the app, then go on like mpv would."""
        e = self._pl[self._cur]
        event(self, event="end-file", reason=reason, playlist_entry_id=e["id"])
        nxt = self._cur + 1
        if reason == "eof" and nxt < len(self._pl):
            play_entry(self, nxt)
        else:
            self._cur = None
            self.props.update({"idle-active": True, "time-pos": None, "duration": None})
            self.stirred.set()

    async def tick(self):
        step = 0.25
        while True:
            await asyncio.sleep(step)
            if self._cur is None or self.props.get("pause") or self.props.get("idle-active"):
                continue
            pos = (self.props.get("time-pos") or 0) + step * speed
            if pos >= self._pl[self._cur]["dur"]:
                finish(self, "eof")
            else:
                self.props["time-pos"] = pos

    async def start(self):
        self.props = {"pause": False, "time-pos": 0, "duration": 0, "volume": 70, "idle-active": True}
        self.stirred.set()
        self.eq_chain = self.eq_live = self.started = None
        self._pl, self._cur, self._eid = [], None, 0
        if getattr(self, "_ticker", None):
            self._ticker.cancel()
        self._ticker = asyncio.get_running_loop().create_task(tick(self))
        await self.apply_eq()

    async def quit(self):
        self.on_exit = None
        if getattr(self, "_ticker", None):
            self._ticker.cancel()

    async def send(self, *cmd):
        ok = {"error": "success"}
        name, args = cmd[0], cmd[1:]
        if name == "set_property":
            if args[0] in ("pause", "volume"):
                self.props[args[0]] = args[1]
                if args[0] == "pause":
                    self.stirred.set()
        elif name == "cycle" and args[0] == "pause":
            self.props["pause"] = not self.props.get("pause")
            self.stirred.set()
        elif name == "seek" and self._cur is not None:
            self.props["time-pos"] = max(0.0, min(float(args[0]), self._pl[self._cur]["dur"] - 0.5))
        elif name == "loadfile":
            url, mode = args[0], args[1] if len(args) > 1 else "replace"
            start = 0.0
            for opt in args[3:4]:             # loadfile url replace -1 "start=12.3"
                if str(opt).startswith("start="):
                    start = float(str(opt)[6:])
            self._eid += 1
            entry = {"id": self._eid, "url": url, "dur": duration_of(url), "start": start}
            if mode == "replace":
                if self._cur is not None:
                    event(self, event="end-file", reason="stop", playlist_entry_id=self._pl[self._cur]["id"])
                self._pl = [entry]
                play_entry(self, 0)
            else:
                self._pl.append(entry)
            return {**ok, "data": {"playlist_entry_id": entry["id"]}}
        elif name == "playlist-clear":
            self._pl = [self._pl[self._cur]] if self._cur is not None else []
            self._cur = 0 if self._pl else None
        elif name == "stop":
            if self._cur is not None:
                finish(self, "stop")
            self._pl, self._cur = [], None
        return ok

    mpv.Mpv.start, mpv.Mpv.quit, mpv.Mpv.send = start, quit, send

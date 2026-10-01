"""mpv, driven over its JSON IPC socket: start/stop, commands, events, and the live equaliser."""
import asyncio
import json
import os

from .audio import eq_bands, eq_filter, level_to_mpv, pre_cut
from .config import AUDIO_OUT, RUN_DIR, WINDOWS
from .settings import settings
from .tools import mpv_path


class PlayerDown(ConnectionError):
    """mpv is not answering (crashed, restarting, or stuck): the API reports 503."""


class Mpv:
    """Minimal async client for mpv's JSON IPC."""

    def __init__(self, name: str = "mpv"):
        self.sock = RUN_DIR / f"{name}.sock"   # its control socket (Windows: the pipe below)
        self.pipe = rf"\\.\pipe\tunebox-{os.getpid()}-{name}"
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
        self.stirred = asyncio.Event()        # set when pause or idle-active changes (the player's loop waits on it)
        self.eq_chain = None                  # (normalize, gains) written into the af string
        self.eq_live = None                   # gains currently applied (af string + af-command)

    async def start(self):
        if self.proc and self.proc.returncode is None:   # a restart: make sure the old mpv is gone
            self.proc.kill()
            await self.proc.wait()
        self.props = {"pause": False, "time-pos": 0, "duration": 0, "volume": 70, "idle-active": True}
        self.eq_chain = self.eq_live = self.started = None
        if not WINDOWS:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            self.sock.unlink(missing_ok=True)
        ao = AUDIO_OUT or ("" if WINDOWS else "alsa")   # Windows: mpv's own pick (WASAPI)
        self.proc = await asyncio.create_subprocess_exec(
            mpv_path() or "mpv", "--idle=yes", "--no-video", "--force-window=no", "--no-terminal", "--no-config",
            f"--input-ipc-server={self.pipe if WINDOWS else self.sock}", *([f"--ao={ao}"] if ao else []),
            f"--volume={level_to_mpv(settings['volume'])}",
            "--cache=yes", "--demuxer-max-bytes=16MiB", "--audio-buffer=0.5",
            "--prefetch-playlist=yes", "--gapless-audio=weak")
        reader = await (self._connect_pipe() if WINDOWS else self._connect_socket())
        asyncio.get_running_loop().create_task(self._read(reader))
        for i, prop in enumerate(self.props, 1):
            await self.send("observe_property", i, prop)
        await self.apply_eq()

    async def _connect_socket(self) -> asyncio.StreamReader:
        for _ in range(50):
            if self.sock.exists():
                break
            await asyncio.sleep(0.1)
        reader, self.writer = await asyncio.open_unix_connection(str(self.sock), limit=1 << 20)
        return reader

    async def _connect_pipe(self) -> asyncio.StreamReader:
        """Windows: mpv listens on a named pipe; asyncio reaches those only with its Proactor loop."""
        loop = asyncio.get_running_loop()
        if not hasattr(loop, "create_pipe_connection"):
            raise RuntimeError("Tunebox on Windows needs asyncio's Proactor event loop (start it with run.py)")
        reader = asyncio.StreamReader(limit=1 << 20)
        for _ in range(50):
            try:
                transport, protocol = await loop.create_pipe_connection(lambda: asyncio.StreamReaderProtocol(reader), self.pipe)
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("mpv did not open its control pipe")
        self.writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader

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
            if msg["name"] in ("pause", "idle-active"):
                self.stirred.set()
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


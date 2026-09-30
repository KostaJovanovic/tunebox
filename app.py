"""Tunebox: a lean YouTube Music player for the server's own speakers.

ytmusicapi provides search, browsing and YouTube Music's own radio ("up next")
recommendations; yt-dlp resolves each track to a direct audio stream (no ads);
mpv plays it through ALSA and is driven over its JSON IPC socket.

This file only puts the app together (systemd runs `uvicorn app:app`). The code lives in tunebox/:
  config.py    paths and tuning numbers         settings.py  settings.json (volume, EQ, alarm...)
  files.py     safe JSON reads and writes       data.py      history, playlists, people, play counts
  audio.py     volume curve and EQ filters      youtube.py   ytmusicapi, yt-dlp, the stream resolver
  mpv.py       the mpv IPC client               player.py    the queue, gapless play, fades, sleep, alarm
  lyrics.py    LRCLIB + YouTube lyrics          web.py       same-site guard, errors, who's asking
  auth.py      pass phrases and device keys     admin.py     the admin's sessions, lockout, local token
  house.py     house.json: features, groups...  audit.py     the admin's audit log
  plays.py     the play log (Stats, recap)      blocklist.py songs and artists the admin blocked
  local.py     uploaded songs: tags, converting, room
  api/         the HTTP routes, one file per area (pages, browse, queue, lists, people, admin, settings, lyrics...)
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tunebox/ sits next to this file

from fastapi import FastAPI  # noqa: E402

from tunebox import audit, data, local as local_songs, plays, web  # noqa: E402
from tunebox.api import admin, backup, browse, house, lists, local, lyrics, pages, people, queue, settings, stats  # noqa: E402
from tunebox.config import WEB_DIR  # noqa: E402
from tunebox.player import player  # noqa: E402
from tunebox.settings import flush_settings  # noqa: E402


@asynccontextmanager
async def lifespan(_app):
    local_songs.tidy()
    await player.start()
    yield
    player.save_session()
    data.save_stats()
    plays.finish()
    plays.flush()
    flush_settings()
    audit.flush()
    await player.mpv.quit()


app = FastAPI(title="Tunebox", lifespan=lifespan)
web.install(app)
for area in (pages, queue, browse, lists, people, admin, house, local, settings, lyrics, stats, backup):
    app.include_router(area.router)
app.mount("/web", pages.NoCacheFiles(directory=WEB_DIR, check_dir=False), name="web")

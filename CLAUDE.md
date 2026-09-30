# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# tunebox

A shared house jukebox: a FastAPI server plays YouTube Music through the speakers of the machine it runs on (mpv), and every browser on the LAN is a remote. ytmusicapi finds the music, yt-dlp resolves the audio stream, mpv plays it over its JSON IPC socket. The frontend is plain ES modules with no build step.

## Running it

- `server.bat` is the dev copy: `http://localhost:8000/music/`, served under `/music/` the way Caddy serves it on ele (the home server). It uses test data in `dev/data/` (gitignored). `server.bat --silent` swaps in `dev/fakes.py` (a fake mpv and instant fake streams, patched in at import time, not by editing the modules). Other flags: `--lan`, `--port N`, `--speed N`, `--no-browser`, `--data DIR`. Under the hood it runs `dev/emulate.py`.
- `start.bat` / `start.sh` / `python run.py` is the plain end-user run at `http://localhost:8888/` with no prefix. Production (systemd, `tunebox.service`) runs `uvicorn app:app`.
- `dev/env.bat` creates `.venv` and installs `dev/requirements.txt` (which includes `requirements.txt` plus paramiko). It only runs pip when a requirements file's hash changed.
- HTML, CSS and JS changes show on reload. Restart the server after changing Python.
- There is no test suite, linter or build step.

## Architecture

- `app.py` only wires things up: `web.install(app)`, one router per area from `tunebox/api/`, and the `lifespan` that starts the player and flushes every store on shutdown. Its docstring maps each `tunebox/` module to its job. Start reading there.
- `tunebox/player.py` holds the single `player` object. It owns the queue (now playing, then people's songs taking fair turns, then radio), gapless hand-over to mpv, undo snapshots, fades, the sleep timer and the alarm. `tunebox/mpv.py` is the IPC client, and `tunebox/audio.py` turns the volume and EQ settings into mpv numbers.
- **State lives in module-level containers that are mutated in place, never replaced**, so other modules can import them (`data.people`, `settings`, …). The exceptions are named in the module docstrings and must be read through the module: `data.lists_rev` / `data.people_rev`, and `youtube.yt` (replaced on sign-in and sign-out).
- Persistence: JSON files in `TUNEBOX_DATA` (default: the app folder, all gitignored), always written through `files.write_json` (atomic temp file, fsync, rename). Writes are batched and debounced (`save_settings_soon`, session and plays at most once a minute) to spare the server's SD card. `plays/YYYY-MM.jsonl` is an append-only play log that Stats and the recap read.
- `tunebox/web.py` is the middleware every request passes through. It has a same-site guard that rejects foreign Host/Origin (no logins; the LAN is trusted), readable errors, and `who(request)`: the person from the `tb_who` cookie, valid only if the device holds that person's signed key when the name has a pass phrase (`auth.py`).
- Frontend: `/` serves `web/bauhaus/` (the main UI), `/wall` serves `web/wall/` (TV/tablet screen), and both use `web/shared/`. Everything goes out with `Cache-Control: no-cache` so a deploy shows up at once. Every page polls `api/state` once a second (`web/shared/playback.js`); there are no websockets. **All URLs in the frontend are relative** (`api/state`, `web/...`), because the app must work under a path prefix like `/music/`. Keep them relative.
- `web/sw.js` exists only so the app can be installed. It caches nothing.

## Deploying

`dev/deploy.py` (run through `save.bat deploy` / `./save.sh deploy`) uploads only `FILES = ["app.py"]` and the mirrored `DIRS = ["tunebox", "web"]`. A new top-level file needed on the server must be added there. It backs up first, restarts only if Python changed, runs a health check, and rolls back on failure. It never installs the systemd unit; it only reports differences. Servers are kept per device in `dev/servers.json` (gitignored); without it, the built-in server is ele.

## Committing

`save.bat` is the only way to commit — never run `git commit` or `git push` directly. From a terminal, `save.bat quick "message"` commits and pushes with no menu or prompts; `save.bat quick-commit "message"` commits without pushing. (Run it from PowerShell: `.\save.bat quick "message"`. Not from Git Bash, which cannot start a .bat from a path with spaces and puts its Unix `find` ahead of the Windows one the script uses.) `quick` never deploys to ele; deploying stays a manual `save.bat deploy`.

Never add Co-Authored-By, "Generated with Claude Code", or any other Claude/AI attribution to commit messages or PR descriptions.

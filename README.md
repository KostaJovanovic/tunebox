# Tunebox

A lean YouTube Music player for the speakers of the computer it runs on. Everyone on the network opens it in a browser and controls the same queue; the audio comes out of that computer. Run it on a home server by the stereo, or on your own PC as a local app.

- [ytmusicapi](https://github.com/sigma67/ytmusicapi) for search, home shelves, albums, artists, playlists and YouTube Music's own radio ("up next")
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) resolves each track to a direct audio stream (no ads)
- [mpv](https://mpv.io) plays it, driven over its JSON IPC socket (a named pipe on Windows)

## Get it running

Get the code first: `git clone https://github.com/KostaJovanovic/tunebox.git` (or download the ZIP from GitHub and unpack it).

**Windows, as a local app.** Install [Python](https://www.python.org/downloads/) 3.11 or newer (tick "Add python.exe to PATH"), then double-click `start.bat`. The first start sets everything up in this folder (the Python packages, mpv and Node) and takes a few minutes; then Tunebox opens in your browser at `http://localhost:8888/` and plays through this PC's speakers. Closing the window stops it. `start.bat --lan` lets phones on the same network use it too.

**Linux, as a server** (a home server by the speakers; tested on Debian 13 / DietPi):

```sh
cd tunebox
./install.sh              # asks for sudo: mpv, a systemd service that starts at boot, open to the network
```

It installs mpv and Python's venv with apt, puts the Python packages in `.venv` and Node 22 in `tools/node`, adds your user to the `audio` group, and writes, enables and starts `/etc/systemd/system/tunebox.service` (it starts at boot and restarts if it stops). Then it prints the addresses to open, e.g. `http://myserver:8888/`. Without apt, install mpv and Python 3.11+ yourself first; the script does the rest. If the sound comes out of the wrong card, see [Audio output](#audio-output); to serve it under a path like `/music/`, see [Behind a reverse proxy](#behind-a-reverse-proxy-optional).

**Linux, as a local app** on your own computer:

```sh
./install.sh --desktop    # once
./start.sh                # then this (or Tunebox in the app menu); ./start.sh --lan for the network too
```

To update: `git pull`, then run the same command again (a server restarts with the new code). Options: `--port N` (default 8888). With a server, `sudo journalctl -u tunebox -f` shows the log.

Opening it by name from other devices works for the computer's own name (`http://myserver:8888/`, and `myserver.local`) and by IP address. For other names (your own DNS name, a reverse proxy's), list them in `TUNEBOX_HOSTS` (comma separated), e.g. `Environment=TUNEBOX_HOSTS=music.home` in the service.


## Working on it (Windows)

- **`server.bat`** runs it at <http://localhost:8000/music/>, under `/music/` the way ele's Caddy serves it, and opens the browser. It plays through this PC's speakers; `server.bat --silent` swaps in a fake player (`dev/fakes.py`), `--lan` and `--port` as usual. Its data lives in `dev/data/` (git-ignored).
- Edit, reload the page. HTML, CSS and JS changes show at once; restart `server.bat` after changing Python code.
- **`save.bat`** commits, pushes to GitHub when a remote exists, and then, **if ele is reachable**, deploys (`dev/deploy.py`):
  - Only files whose content differs from ele's are uploaded, after a list you confirm. The old copies go to `/opt/homeapps/tunebox/.bak/<time>/` (the last 10 are kept).
  - Changed Python files are compile-checked on ele first; then the service restarts and has to answer, or you're offered a rollback. If music was playing, it presses play again.
  - `tunebox.service` is only reported when it differs from ele's; install it by hand.
  - `save.bat status` shows what would change; `save.bat pull-data` copies ele's playlists, history, people and settings into `dev/data/`. The YouTube sign-in cookies stay on ele.
- The first `server.bat` or `save.bat` run creates `.venv` (the same one `start.bat` uses) and installs `dev/requirements.txt`.

The rest of ele (the launcher page, Caddy, Paper) lives in the separate homeapps repository.

## Features

- Search, Home, albums, artists and playlists; Explore has new releases and moods & genres
- Pasting a YouTube or YouTube Music link into the search box opens its song, album, playlist or artist
- Right-click (long press on a phone) on any song, album, playlist or artist for a menu: play, play next, add to the end of the queue, add to playlist, like, go to artist or album, copy link. Anywhere else it's the player's own menu; Shift + right-click keeps the browser's
- The artist and album names in the player, the now playing canvas and an album page open their pages; Back walks back through them
- Stats (T): for any period (last 30 days, a month, a year, all time or custom) and for the house, one person or one seminar: minutes, plays, top songs and artists, who added the most, seminars, and when the house listens
- A Wrapped-style recap for the same period and person or seminar: full-screen story slides (number one song, top songs and artists, minutes, range, when, seminars, who added the most), then play the top songs
- Home starts with the house's own shelves: Most played (last 30 days), Liked mix and House mix
- A two-part queue, like Spotify: the song playing, then the songs people added, then radio. Playing anything while a song is on (tapping a song, its play button, or Play on an album, playlist or history) asks first: Interrupt, Play next, or Add to the end of the queue (the end of the added songs). The Play next and Add all buttons skip the question. The radio always follows the last song someone added and stays after the added songs
- Take turns (on by default): songs from different people alternate, so nobody takes over the queue
- Undo for every queue change (the toast, the Up next drawer, or Z), and an Earlier queues list to restore from
- People: everyone picks a name (with colour and emoji) and one or more seminars (Ele, Fiz, Teh, or any 3-letter one typed under Other) once per device; the queue and history show who added each song, with their seminars, and likes remember who liked them. Adding songs asks for a name first
- Pass phrases (optional): a name can have one, asked once per device before it can be used; an admin pass phrase guards removing people and clearing the history, and resets a forgotten one
- On touch screens, swipe a queued song left to remove it or right to play it next; the grip drags it
- A wall screen at `/wall` for a tablet or TV: cover, synced lyrics and big controls; a dimmed clock when nothing plays. It keeps the screen on only over HTTPS (or localhost), since browsers allow wake locks only there
- Gapless hand-over: the next track is preloaded 20 s before the current one ends
- 10-band equaliser with presets and optional loudness normalisation; EQ changes are heard at once, without gaps (the normaliser sits before the EQ, since it looks seconds ahead)
- Volume slider linear in dB; audio quality setting (best / balanced / low)
- Sleep timer (minutes or end of track) with fade-out; wake-up alarm with volume ramp
- Shared playlists and play history for the whole house; Liked songs shows who liked each song and can show just one person's or one seminar's likes
- Lyrics from [LRCLIB](https://lrclib.net) (often time-synced), YouTube Music as fallback
- Queue and position survive restarts and crashes (restored paused); mpv is restarted automatically if it dies
- Skips streams that fail to load and stops after 3 failures in a row; keeps the last 50 played tracks in the queue
- Installable as an app (manifest, icons, a service worker that says when the server can't be reached). Browsers install it fully only over HTTPS or on localhost; over plain http a phone gets a home-screen shortcut
- The GitHub icon in Settings links to this code
- One interface at `/`; the old `/classic` and `/bauhaus` addresses redirect there
- Backup and restore (Settings): one file with people, seminars, pass phrases, playlists and likes, history, stats, the play log and settings (never the YouTube sign-in). A restore first saves what it replaces in `backups/`
- Optional sign-in with your YouTube Music cookies for personalised Home and radio (playback stays anonymous)

There are no accounts to sign in to (pass phrases only guard names and a few admin actions): it is meant for a trusted local network only. It does refuse requests that don't come from it:

- The `Host` header must be a private, loopback or Tailscale (100.64.0.0/10) address, a `*.ts.net` name, this computer's own name (plain or `.local`), or one of the names in `TUNEBOX_HOSTS` or `LOCAL_NAMES` in `tunebox/config.py`. Any other name gives `403 Unknown host` (by IP address always works). This blocks DNS-rebinding attacks from web pages.
- Writes carrying a foreign `Origin` are refused, and request bodies must be JSON, so other websites can't drive the player from your browser.

## How the code is laid out

| Path | What's in it |
|---|---|
| `run.py` | Starts it: fetches mpv and Node the first time, serves it, opens the browser (`start.bat`, `start.sh` and the service call it) |
| `install.sh`, `start.bat`, `start.sh` | Setup for Linux (server or desktop), and starting it on Windows and Linux |
| `app.py` | Builds the FastAPI app from the parts below (what uvicorn runs) |
| `tunebox/config.py` | Paths, limits, EQ presets, the allowed host names |
| `tunebox/tools.py` | Finding (or fetching) mpv and Node |
| `tunebox/player.py`, `mpv.py` | The queue, gapless playback, fades, sleep timer and alarm; talking to mpv |
| `tunebox/youtube.py`, `lyrics.py`, `audio.py` | YouTube Music and yt-dlp; lyrics lookup; volume and EQ maths |
| `tunebox/data.py`, `settings.py`, `files.py` | History, playlists, people, seminars, play counts, settings, and saving them |
| `tunebox/plays.py`, `auth.py` | The play log (Stats and the recap); pass phrases |
| `tunebox/web.py` | Host/origin checks and error handling for every request |
| `tunebox/api/` | The HTTP API, one file per area (queue, browse, lists, people, settings, stats, backup, lyrics, pages) |
| `web/bauhaus/`, `web/wall/` | The two pages (the player, and the wall screen), each an `index.html` with its `css/` and `js/` (ES modules, no build step) |
| `web/shared/` | JavaScript every page uses: the API, polling and the queue, likes, names, lyrics, queue gestures, theme |
| `web/manifest.webmanifest`, `web/icons/`, `web/sw.js` | What makes it installable as an app |

Buttons say what they do with `data-act="..."`; the module that owns the action registers it with `on(...)` from `web/shared/actions.js`. Pages and their files are sent with `Cache-Control: no-cache`, so a phone picks up a deploy on the next load.

## Requirements

What the setup installs or fetches, if you'd rather do it by hand:

- Python 3.11+ (tested with 3.13) and the packages in `requirements.txt`
- `mpv` (tested with 0.40): the `mpv` package on Linux; on Windows `run.py` fetches it into `tools/mpv`
- Node.js 22+ for yt-dlp's YouTube challenge solver (Debian's Node 20 is too old): `run.py` fetches it into `tools/node` unless it finds one (`../node/bin/node`, or 22+ on the PATH)

By hand on Linux: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then `.venv/bin/python run.py --lan` (`--no-browser` on a server).

Settings through the environment: `TUNEBOX_DATA` (where its files go; default this folder), `TUNEBOX_HOSTS` (more host names), `TUNEBOX_AO` (mpv's audio output; default `alsa` on Linux, WASAPI on Windows), `TUNEBOX_MPV` (the mpv program), `TUNEBOX_PORT`, `TUNEBOX_RUN` (where mpv's socket goes).

The ele server (homeapps) predates the setup: there it lives in `/opt/homeapps/tunebox` with `/opt/homeapps/node` and `/opt/homeapps/venv`, and `tunebox.service` in this folder is its unit (uvicorn directly).

### Audio output

On Linux mpv uses ALSA's default device. If the right card isn't picked, set it in `/etc/asound.conf`, e.g.:

```
pcm.!default { type hw card 0 device 0 }
ctl.!default { type hw card 0 }
```

### Behind a reverse proxy (optional)

The UI uses relative URLs, so it works under a sub-path. Caddy example:

```
redir /music /music/
handle_path /music/* {
	reverse_proxy 127.0.0.1:8888
}
```

## Files it creates

In the app folder, next to `app.py`, or in the folder named by `TUNEBOX_DATA` (`run.py --data DIR`) when that's set (all git-ignored). Setup adds `.venv/` (Python packages) and `tools/` (mpv on Windows, Node).

| File | Contents |
|---|---|
| `settings.json` | volume, EQ, options, alarm |
| `session.json` | queue, position and the last 15 queue snapshots (undo), saved at most every 60 s when changed (spares an SD card) and on shutdown |
| `history.json` | recently played (last 300) |
| `playlists.json` | Tunebox playlists |
| `people.json` | names picked on devices (name, colour, emoji, seminars) |
| `seminars.json` | seminars added under Other (Ele, Fiz and Teh are built in) |
| `plays/` | the play log, one file per month (`2026-09.jsonl`), kept for good: each song that played, who added it and their seminars, and how many seconds were heard. Appended at most once a minute. Stats and the recap read it |
| `stats.json` | when each song played, last 30 days (for Most played), saved at most every minute |
| `keys.json` | the admin pass phrase (salted hash) and the secret that signs devices' name keys |
| `backups/` | what a restore replaced (`before-restore-<time>.json`) |
| `browser.json` | YouTube Music sign-in headers, only if you sign in (contains your cookies) |

## Updating yt-dlp

YouTube changes often; when streams stop resolving, update yt-dlp first:

```sh
.venv/bin/pip install -U yt-dlp && sudo systemctl restart tunebox      # Linux server
.venv\Scripts\pip install -U yt-dlp                                    # Windows, then start it again
```

On ele: `/opt/homeapps/venv/bin/pip install -U yt-dlp && sudo systemctl restart tunebox`.

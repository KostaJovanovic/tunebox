# Tunebox

> The `music` module of homeapps. To develop it, run `server.bat` at the repository root; `save.bat` deploys it to ele. The steps below install it on a fresh server.

A lean YouTube Music player for a home server's own speakers. Everyone on the local network opens it in a browser and controls the same queue; the audio comes out of the server.

- [ytmusicapi](https://github.com/sigma67/ytmusicapi) for search, home shelves, albums, artists, playlists and YouTube Music's own radio ("up next")
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) resolves each track to a direct audio stream (no ads)
- [mpv](https://mpv.io) plays it through ALSA and is driven over its JSON IPC socket

## Features

- Search, Home, albums, artists and playlists; Explore has new releases and moods & genres
- Pasting a YouTube or YouTube Music link into the search box opens its song, album, playlist or artist
- Right-click (long press on a phone) on any song, album, playlist or artist for a menu: play, play next, add to the end of the queue, add to playlist, like, go to artist or album, copy link. Anywhere else it's the player's own menu; Shift + right-click keeps the browser's
- The artist and album names in the player, the now playing canvas and an album page open their pages; Back walks back through them
- Home starts with the house's own shelves: Most played (last 30 days), Liked mix and House mix
- A two-part queue, like Spotify: the song playing, then the songs people added, then radio. Playing anything while a song is on (tapping a song, its play button, or Play on an album, playlist or history) asks first: Interrupt, Play next, or Add to the end of the queue (the end of the added songs). The Play next and Add all buttons skip the question. The radio always follows the last song someone added and stays after the added songs
- Take turns (on by default): songs from different people alternate, so nobody takes over the queue
- Undo for every queue change (the toast, the Up next drawer, or Z), and an Earlier queues list to restore from
- People: everyone picks a name (with colour and emoji) and one or more seminars (Ele, Fiz, Teh, or any 3-letter one typed under Other) once per device; the queue and history show who added each song, with their seminars, and likes remember who liked them. Adding songs asks for a name first
- On touch screens, swipe a queued song left to remove it or right to play it next; the grip drags it
- A wall screen at `/wall` for a tablet or TV: cover, synced lyrics and big controls; a dimmed clock when nothing plays. It keeps the screen on only over HTTPS (or localhost), since browsers allow wake locks only there
- Gapless hand-over: the next track is preloaded 20 s before the current one ends
- 10-band equaliser with presets and optional loudness normalisation; EQ changes are heard at once, without gaps (the normaliser sits before the EQ, since it looks seconds ahead)
- Volume slider linear in dB; audio quality setting (best / balanced / low)
- Sleep timer (minutes or end of track) with fade-out; wake-up alarm with volume ramp
- Shared playlists and play history for the whole house
- Lyrics from [LRCLIB](https://lrclib.net) (often time-synced), YouTube Music as fallback
- Queue and position survive restarts and crashes (restored paused); mpv is restarted automatically if it dies
- Skips streams that fail to load and stops after 3 failures in a row; keeps the last 50 played tracks in the queue
- One interface at `/`; the old `/classic` and `/bauhaus` addresses redirect there
- Optional sign-in with your YouTube Music cookies for personalised Home and radio (playback stays anonymous)

There is no authentication: it is meant for a trusted local network only. It does refuse requests that don't come from it:

- The `Host` header must be a private, loopback or Tailscale (100.64.0.0/10) address, a `*.ts.net` name, or one of the names in `LOCAL_NAMES` in `tunebox/config.py`. **Put your server's hostname(s) there**, otherwise opening it by name gives `403 Unknown host` (by IP address always works). This blocks DNS-rebinding attacks from web pages.
- Writes carrying a foreign `Origin` are refused, and request bodies must be JSON, so other websites can't drive the player from your browser.

## How the code is laid out

| Path | What's in it |
|---|---|
| `app.py` | The entry point uvicorn runs: builds the FastAPI app from the parts below |
| `tunebox/config.py` | Paths, limits, EQ presets, the allowed host names |
| `tunebox/player.py`, `mpv.py` | The queue, playback, fades, sleep timer and alarm; talking to mpv |
| `tunebox/youtube.py`, `lyrics.py`, `audio.py` | YouTube Music and yt-dlp; lyrics lookup; volume and EQ maths |
| `tunebox/data.py`, `settings.py`, `files.py` | History, playlists, people, play counts, settings, and saving them |
| `tunebox/web.py` | Host/origin checks and error handling for every request |
| `tunebox/api/` | The HTTP API, one file per area (queue, browse, lists, people, settings, lyrics, pages) |
| `web/bauhaus/`, `web/wall/` | The two pages (the player, and the wall screen), each an `index.html` with its `css/` and `js/` (ES modules, no build step) |
| `web/shared/` | JavaScript every page uses: the API, polling and the queue, likes, names, lyrics, queue gestures, theme |

Buttons say what they do with `data-act="..."`; the module that owns the action registers it with `on(...)` from `web/shared/actions.js`. Pages and their files are sent with `Cache-Control: no-cache`, so a phone picks up a deploy on the next load.

## Requirements

- Linux with ALSA (tested on Debian 13 / DietPi, x86_64)
- Python 3.11+ (tested with 3.13)
- `mpv` (tested with 0.40)
- Node.js 22+ for yt-dlp's YouTube challenge solver (Debian's Node 20 is too old)

## Install

The app expects this layout (the Node path is resolved relative to the app folder):

```
/opt/homeapps/
├── tunebox/   <- this folder (music/ in the homeapps repository)
├── node/      <- official Node 22 build (node/bin/node)
└── venv/      <- Python virtualenv
```

```sh
sudo apt install mpv python3-venv
sudo mkdir -p /opt/homeapps && sudo chown "$USER" /opt/homeapps
cd /opt/homeapps
# copy this folder (music/ in homeapps) to /opt/homeapps/tunebox

# Node 22 (official build; pick the archive for your architecture)
curl -fsSL https://nodejs.org/dist/v22.23.3/node-v22.23.3-linux-x64.tar.xz | tar -xJ
ln -s node-v22.23.3-linux-x64 node

python3 -m venv venv
venv/bin/pip install -r tunebox/requirements.txt
```

Run it as a service (edit `User=` in the unit file first; the user must be in the `audio` group):

```sh
sudo cp tunebox/tunebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tunebox
```

Then open `http://<server>:8888/` (add the name you use to `LOCAL_NAMES` in `tunebox/config.py` first, see above).

For a quick manual run instead: `TUNEBOX_RUN=/tmp/tunebox ../venv/bin/uvicorn app:app --host 0.0.0.0 --port 8888` from the `tunebox` folder.

### Audio output

mpv uses ALSA's default device. If the right card isn't picked, set it in `/etc/asound.conf`, e.g.:

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

In the app folder, next to `app.py` (all git-ignored):

They go in the folder named by `TUNEBOX_DATA` instead when that's set (the emulator does this).

| File | Contents |
|---|---|
| `settings.json` | volume, EQ, options, alarm |
| `session.json` | queue, position and the last 15 queue snapshots (undo), saved at most every 60 s when changed (spares an SD card) and on shutdown |
| `history.json` | recently played (last 300) |
| `playlists.json` | Tunebox playlists |
| `people.json` | names picked on devices (name, colour, emoji, seminars) |
| `seminars.json` | seminars added under Other (Ele, Fiz and Teh are built in) |
| `stats.json` | when each song played, last 30 days (for Most played), saved at most every minute |
| `browser.json` | YouTube Music sign-in headers, only if you sign in (contains your cookies) |

## Updating yt-dlp

YouTube changes often; when streams stop resolving, update yt-dlp first:

```sh
/opt/homeapps/venv/bin/pip install -U yt-dlp && sudo systemctl restart tunebox
```

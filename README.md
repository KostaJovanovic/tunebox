# Tunebox

**One speaker. Everyone's the DJ.**

Tunebox turns any computer with speakers into the house jukebox. It plays YouTube Music with no ads. Anyone on the Wi-Fi opens it in a browser and adds songs to one shared queue. The music plays from that one computer.

No accounts. No app to install. No fights about the aux cable.

---

## Get it running

```sh
git clone https://github.com/KostaJovanovic/tunebox.git
```

**Windows**: install [Python](https://www.python.org/downloads/) 3.11+ (tick *Add to PATH*), then double-click **`start.bat`**. The first start installs what it needs in a few minutes. Then it opens at <http://localhost:8888/>. Close the window to stop it.

**Linux server**, a box by the stereo that starts at boot:

```sh
cd tunebox && ./install.sh
```

**Linux desktop:**

```sh
./install.sh --desktop     # once
./start.sh                 # or Tunebox in the app menu
```

That's it. Open the address it prints from any phone or laptop on the network.

**Update:** `git pull`, then run the same command again.

<details>
<summary>What <code>install.sh</code> actually does</summary>

It installs mpv with apt, puts the Python packages in `.venv` and Node 22 in `tools/`, and adds you to the `audio` group. For a server, it also creates a systemd service that starts at boot and restarts if it stops.

No apt? Install mpv and Python 3.11+ yourself first. Options: `--port N` (default 8888). Logs: `sudo journalctl -u tunebox -f`.
</details>

---

## What it does

🎵 **Play anything.** Search, browse Home and Explore, or paste any YouTube link. Right-click (or long-press) anything for a menu.

👥 **Share the queue fairly.** Songs from different people take turns, so no one person controls the music. Radio plays when the queue is empty. You can undo every change.

🙋 **Know who's who.** Everyone picks a name, colour, emoji and seminar. You can see who queued each song and who liked it. Names can have an optional pass phrase.

📊 **Stats and a Wrapped-style recap.** See the top songs, artists and people for any period. Look at the whole house, one person or one seminar. The recap shows it as full-screen story slides.

🎛️ **Sound right.** Gapless playback, a 10-band EQ with presets, loudness normalisation, and a volume slider that feels even.

🌙 **Sleep and wake.** A sleep timer that fades out, and an alarm that fades in.

🎤 **Lyrics**, time-synced when available.

📺 **Wall screen** at `/wall` for a tablet or TV: cover art, lyrics and big buttons.

📱 **Installable** as an app on your phone's home screen.

💾 **Backup and restore** everything in one file, from Settings.

---

## Good to know

**It's for a home network.** There are no logins. It trusts the devices on the local network. It refuses requests from other addresses, so a website can't control your speakers.

**Songs won't play?** YouTube probably changed something. Update yt-dlp:

```sh
.venv/bin/pip install -U yt-dlp && sudo systemctl restart tunebox
```

**Wrong speaker?** Pick the card in `/etc/asound.conf`:

```
pcm.!default { type hw card 0 device 0 }
ctl.!default { type hw card 0 }
```

**Opening it by another name** (your own DNS name or a reverse proxy's)? Add it to `TUNEBOX_HOSTS`, e.g. `Environment=TUNEBOX_HOSTS=music.home` in the service. The machine's own name and its IP always work.

**Want it under a path like `/music/`?** It works behind a reverse proxy. With Caddy:

```
redir /music /music/
handle_path /music/* {
	reverse_proxy 127.0.0.1:8888
}
```

<details>
<summary>Settings you can set in the environment</summary>

| Variable | What it sets |
|---|---|
| `TUNEBOX_DATA` | where it keeps its files (default: this folder) |
| `TUNEBOX_PORT` | the port (default 8888) |
| `TUNEBOX_HOSTS` | extra host names to answer to |
| `TUNEBOX_AO` | mpv's audio output (default ALSA on Linux, WASAPI on Windows) |
| `TUNEBOX_MPV` | a specific mpv program |
| `TUNEBOX_RUN` | where mpv's control socket goes |
</details>

<details>
<summary>The files it keeps</summary>

Everything lives in the app folder (or `TUNEBOX_DATA`). Git ignores all of it.

| File | What's in it |
|---|---|
| `settings.json` | volume, EQ, options, alarm |
| `session.json` | the queue and undo history |
| `history.json` | the last 300 songs played |
| `playlists.json` | playlists and likes |
| `people.json`, `seminars.json` | names and seminars |
| `plays/` | the play log behind Stats and the recap, one file per month |
| `stats.json` | the last 30 days of plays, for *Most played* |
| `keys.json` | the admin pass phrase (hashed) and the device-key secret |
| `backups/` | the copy a restore saves before it replaces anything |
| `browser.json` | your YouTube Music sign-in, only if you signed in |
</details>

---

## Hacking on it

It's Python ([FastAPI](https://fastapi.tiangolo.com)) on the back and plain JavaScript modules on the front, with no build step. [ytmusicapi](https://github.com/sigma67/ytmusicapi) finds the music, [yt-dlp](https://github.com/yt-dlp/yt-dlp) gets the audio stream, and [mpv](https://mpv.io) plays it.

| | |
|---|---|
| **`server.bat`** | runs a dev copy at <http://localhost:8000/music/> with test data in `dev/data/`. Add `--silent` for a fake player. |
| **`save.bat`** (Windows) or **`./save.sh`** (macOS, Linux) | commits, pushes, and deploys to a server: only changed files, backed up first, health-checked, with a rollback if something breaks. |

Edit and reload: HTML, CSS and JS changes show at once. Restart `server.bat` after changing Python.

<details>
<summary>Deploying to your own server</summary>

The deploy works with any server that runs Tunebox as a systemd service, like one set up with `install.sh`. It reads the folder, the Python and the port from the service.

1. Run `save.bat` and pick **servers**, or run `./save.sh servers`.
2. Add the server: a name, its address and the SSH user.
3. Pick **deploy**. With more than one server, it asks which. You can also name one: `save.bat deploy office`.

Each device keeps its own list in `dev/servers.json`, and git ignores it. The deploy logs in with your SSH key. If the key doesn't work, it asks for the password. If sudo needs a password too, it asks once per deploy.
</details>

<details>
<summary>Where things are</summary>

| Path | What's in it |
|---|---|
| `run.py`, `install.sh`, `start.*` | starting it and setting it up |
| `app.py` | puts the app together |
| `tunebox/player.py`, `mpv.py` | the queue, gapless playback, the sleep timer, the alarm, and mpv control |
| `tunebox/youtube.py`, `lyrics.py`, `audio.py` | YouTube Music and yt-dlp, lyrics, volume and EQ maths |
| `tunebox/data.py`, `plays.py`, `auth.py` | playlists, people, the play log, pass phrases |
| `tunebox/web.py`, `api/` | request checks and the HTTP API |
| `web/bauhaus/`, `web/wall/`, `web/shared/` | the player, the wall screen, and code both use |
| `dev/` | the dev server, the fake player, the deploy tool |

Buttons declare what they do with `data-act="..."`. The module that owns the action registers it with `on(...)`.
</details>

<details>
<summary>About ele</summary>

ele is the home server Tunebox started on. Its setup is by hand. Tunebox lives in `/opt/homeapps/tunebox`, and `tunebox.service` from this folder starts it. `save.bat` updates it, not `git pull`. ele is the server the deploy uses when a device has no server list yet. The rest of ele (the launcher, Caddy, Paper) is in the homeapps repository.
</details>

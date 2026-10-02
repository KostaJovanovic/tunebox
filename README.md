# Tunebox

**One speaker. Everyone's the DJ.**

Tunebox turns any computer with speakers into the house jukebox. It plays YouTube Music with no ads. Anyone on the Wi-Fi opens it in a browser and adds songs to one shared queue. The music plays from that one computer.

No accounts. No app to install. No fights about the aux cable.

---

## Get it running

```sh
git clone https://github.com/KostaJovanovic/tunebox.git
```

**Windows**: install [Python](https://www.python.org/downloads/) 3.11+ (tick *Add to PATH*), then double-click **`start.bat`**. The first start installs what it needs in a few minutes. Then it opens at <http://localhost:8888/>, and phones on the network open the address it prints (when Windows asks about the firewall, allow private networks). `start.bat --local` keeps it to this PC. Close the window to stop it.

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

📁 **Your own files too.** Upload the songs YouTube doesn't have, on the *Local* page: drop the files in, and they play, queue, go into playlists and count in Stats like any other song. Titles, artists and covers come from the files' tags and can be changed. WAV and AIFF are stored as FLAC (lossless, half the size); mp3, FLAC, m4a, Ogg and Opus stay as they are.

👥 **Share the queue fairly.** Songs from different people take turns, so no one person controls the music. When the queue runs out, the radio carries on from its last song. You can undo every change.

🙋 **Know who's who.** Everyone picks a name, colour, emoji and group (call them seminars, teams, rooms: your word). You can see who queued each song and who liked it. Names can have an optional pass phrase.

📊 **Stats and a Wrapped-style recap.** See the top songs, artists and people for any period. Look at the whole house, one person or one group. The recap shows it as full-screen story slides.

🎛️ **Sound right.** Gapless playback, a 10-band EQ with presets, loudness normalisation, and a volume slider that feels even.

🌙 **Sleep and wake.** A sleep timer that fades out, and an alarm that fades in.

🎤 **Lyrics**, time-synced when available.

📺 **Wall screen** at `/wall` for a tablet or TV: cover art, lyrics and big buttons.

📱 **Installable** as an app on your phone's home screen.

💾 **Backup and restore** everything in one file, from Settings. The admin can also download a full backup: a zip with that file and the audio of the local songs.

⌨️ **From a terminal too.** `tunebox add daft punk`, `tunebox next`, `tunebox vol +5`: everything the page does is a command, on the server or from any computer on the network. `tunebox tui` is the whole player full-screen in the terminal.

🔑 **One admin for the house.** Type the Konami code (↑ ↑ ↓ ↓ ← → ← → B A), or tap the word *Settings* ten times on a phone. The first time, you choose the admin password. The admin can edit, merge, block and remove people, see what each person played, and clean up plays, likes and playlists.

🧩 **Only what you need.** The admin can switch off any part: names, groups, playlists, likes, Home and Explore, pasted links, local songs, radio, lyrics, stats, the recap, the wall screen, the alarm, the sleep timer, the equaliser. What is off is hidden for everyone and nothing is deleted. Four presets (Home, Office, Party, Solo) set all the switches at once, and a setup can be copied to another Tunebox as a file.

🏠 **Make it yours.** Give the house its own name and accent colour, set its time zone, decide who may add names and groups, choose what the wall screen shows, and block songs or artists nobody wants to hear again. For local songs, the admin sees how full the disk is and sets how much they may take, how much free space always stays, and the biggest file.

---

## Command line

`install.sh` adds the `tunebox` command; on Windows it is `tunebox.bat` in the Tunebox folder. It needs only Python 3.11+, so you can also copy `tunebox/cli.py` (and `tunebox/tui.py` next to it, for `tunebox tui`) to any computer and run `python cli.py`.

```sh
tunebox status                       # what is playing
tunebox iam Ana                      # say who you are, once (iam Ana --new adds the name)
tunebox add daft punk one more time  # finds the song and queues it; --next, --now, --replace, --pick 2
tunebox add https://youtu.be/...     # a song, album or playlist link
tunebox next                         # also: prev, pause, play, toggle, stop, seek 1:30, vol +5, sleep 30, undo
tunebox queue                        # up next; queue rm 2, queue mv 4 1, queue top 3, queue clear
tunebox search discovery -k albums   # then: tunebox album ID --add
tunebox lists play "Friday" --shuffle
tunebox local upload *.flac          # your own files
tunebox tui                          # the whole thing full-screen: tabs, lists and keys
tunebox -h                           # every command; tunebox COMMAND -h for one
```

It talks to the Tunebox on the same machine. For another one, name it: `tunebox --server http://ele.local/music/ status`, or save it once with `tunebox server add home http://ele.local/music/`.

What needs the admin asks for the password once (`tunebox features off lyrics`, `tunebox people`, `tunebox house set name Studio`, `tunebox block add --artist NAME`, `tunebox backup --full`, `tunebox restore FILE`). On the server itself no password is needed: reading Tunebox's own files is proof enough, so `ssh server tunebox admin reset` works when the password is lost.

**`tunebox tui`** is Tunebox as a full-screen program in the terminal, also over SSH: Home, Search, Queue, Playlists, History, Local, Stats, Lyrics, Settings and the admin's panel as tabs (`1` to `9` and `0`), the player on the bottom line, and Up next beside it when the window is wide. Arrows or `j` and `k` move, Enter adds or opens, `/` searches, Space pauses, `n` and `p` skip, `+` and `-` set the volume, `?` lists every key, `q` leaves. If the lines or emoji look wrong in your terminal, start it with `tunebox tui --ascii`; set `NO_COLOR` for no colours.

For scripts: `--json` prints the server's answer, `--no-input` never asks, `--yes` confirms, and `TUNEBOX_ADMIN_PASSWORD` gives the password. Exit codes: 0 done, 1 refused, 2 wrong usage, 3 no Tunebox there.

**Bringing local songs back from a full backup?** Unzip its `local` folder into Tunebox's data folder on the server, then restore the `tunebox-backup.json` from the same zip in Settings.

---

## Good to know

**It's for a home network.** There are no logins. It trusts the devices on the local network. It refuses requests from other addresses, so a website can't control your speakers. Only a few things need the admin password: managing people, the house's setup, clearing the history, the YouTube sign-in and restoring a backup.

**Forgot the admin password?** Run this on the server, in the Tunebox folder (add `--port N` if it isn't 8888). The music keeps playing, and the next person to open the admin panel chooses a new password:

```sh
.venv/bin/python run.py --reset-admin      # or: tunebox admin reset
```

**Songs won't play?** YouTube probably changed something. Update yt-dlp: when songs keep failing, the admin sees a bar with an Update button (also in the admin panel's yt-dlp tab, or `tunebox update-ytdlp`). Then restart Tunebox. By hand:

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
| `playlists.json` | playlists (with who made each) and likes |
| `people.json`, `seminars.json` | names and groups |
| `plays/` | the play log behind Stats and the recap, one file per month |
| `stats.json` | the last 30 days of plays, for *Most played* |
| `keys.json` | the admin password (hashed) and the device-key secret |
| `house.json` | what the admin set for the house: name, accent, time zone, feature switches, group rules, wall options |
| `blocklist.json` | the songs and artists the admin blocked |
| `local.json`, `local/` | the uploaded songs: their details, and the audio files and covers |
| `audit.json` | the admin's log: unlocks, wrong passwords, changes |
| `cli.token` | a token written at every start; it lets `run.py --reset-admin` and the `tunebox` command on the server act as the admin |
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

When Tunebox needs a Python package the server doesn't have yet, the deploy names it and asks before installing only that one.

Each device keeps its own list in `dev/servers.json`, and git ignores it. The deploy logs in with your SSH key. If the key doesn't work, it asks for the password. If sudo needs a password too, it asks once per deploy.

To log in to the server with a different address or SSH user, pick **logout**, or run `save.bat logout` or `./save.sh logout`. It moves `dev/servers.json` to `dev/servers.json.old`, and the next deploy asks for the address and user again. The SSH password is never saved. The GitHub login is not touched.
</details>

<details>
<summary>Where things are</summary>

| Path | What's in it |
|---|---|
| `run.py`, `install.sh`, `start.*` | starting it and setting it up |
| `app.py` | puts the app together |
| `tunebox/player.py`, `mpv.py` | the queue, gapless playback, the sleep timer, the alarm, and mpv control |
| `tunebox/youtube.py`, `lyrics.py`, `audio.py` | YouTube Music and yt-dlp, lyrics, volume and EQ maths |
| `tunebox/local.py` | uploaded songs: tags and covers ([mutagen](https://mutagen.readthedocs.io)), converting with mpv, room on the disk |
| `tunebox/data.py`, `plays.py`, `auth.py` | playlists, people, the play log, pass phrases |
| `tunebox/web.py`, `api/` | request checks and the HTTP API |
| `tunebox/cli.py`, `tunebox.bat` | the `tunebox` command |
| `web/bauhaus/`, `web/wall/`, `web/shared/` | the player, the wall screen, and code both use |
| `dev/` | the dev server, the fake player, the deploy tool |

Buttons declare what they do with `data-act="..."`. The module that owns the action registers it with `on(...)`.
</details>

<details>
<summary>About ele</summary>

ele is the home server Tunebox started on. Its setup is by hand. Tunebox lives in `/opt/homeapps/tunebox`, and `tunebox.service` from this folder starts it. `save.bat` updates it, not `git pull`. ele is the server the deploy uses when a device has no server list yet. The rest of ele (the launcher, Caddy, Paper) is in the homeapps repository.
</details>

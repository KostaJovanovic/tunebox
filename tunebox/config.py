"""Where Tunebox keeps its files, and the numbers that tune its behaviour."""
import ipaddress
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent   # music/ here, /opt/homeapps/tunebox on ele
WEB_DIR = APP_DIR / "web"                            # the pages, their CSS and JS
RUN_DIR = Path(os.environ.get("TUNEBOX_RUN", "/run/tunebox"))
DATA = Path(os.environ.get("TUNEBOX_DATA") or APP_DIR)   # where the files below live (the dev emulator moves them)
NODE = APP_DIR.parent / "node" / "bin" / "node"     # official Node 22 build (Debian's Node 20 is too old for yt-dlp)

AUTH_FILE = DATA / "browser.json"          # optional: personal YT Music headers
SETTINGS_FILE = DATA / "settings.json"     # volume + equaliser, survives restarts
SESSION_FILE = DATA / "session.json"       # queue + position, restored paused after a restart
HISTORY_FILE = DATA / "history.json"       # recently played, newest first (shared by everyone)
LISTS_FILE = DATA / "playlists.json"       # Tunebox playlists (shared, editable by anyone)
PEOPLE_FILE = DATA / "people.json"         # who's listening: names picked per device (cookie tb_who)
STATS_FILE = DATA / "stats.json"           # when each song played, last STATS_DAYS days (for "Most played")
KEYS_FILE = DATA / "keys.json"             # pass phrase hashes (admin) and the secret that signs device cookies
PLAYS_DIR = DATA / "plays"                 # the play log, a file per month, kept for good (Stats, recap)
SEMINARS_FILE = DATA / "seminars.json"     # seminars people added themselves (the built-in ones are below)

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
CROSSFADE_MAX = 12                          # the crossfade setting goes up to this many seconds
XF_GIVE_UP = 3                              # after this many crossfades that couldn't start, stop trying until a restart
HISTORY_MAX = 300
STATS_DAYS = 30

SEMINARS = {                                # built in; people can add their own 3-letter ones
    "ele": {"id": "ele", "name": "Ele", "color": "#1F5FBF"},
    "fiz": {"id": "fiz", "name": "Fiz", "color": "#E63B2E"},
    "teh": {"id": "teh", "name": "Teh", "color": "#1E8F5A"},
}
SEMINAR_COLORS = ["#6A4BC4", "#EE6A1F", "#C8327A", "#F2C230", "#0E8C8C", "#8A5A2B", "#5C5953"]   # for added ones, in turn

VOL_RANGE_DB = 50                           # the volume slider spans -50 dB .. 0 dB (0 = mute)
PAUSE_FADE = 0.5                            # play/pause fades in or out over half a second
SLEEP_FADE = 30                             # sleep timer fades out over the last 30 s
TRACK_FADE = 8                              # "end of track" sleep fades over the last 8 s
TEST_RAMP = 10                              # an alarm test ramps up over 10 s, not the alarm's minutes

QUALITY = {                                 # yt-dlp format per audio quality setting
    "best": "bestaudio[acodec=opus]/bestaudio",
    "balanced": "250/bestaudio[abr<=100]/bestaudio",
    "low": "249/bestaudio[abr<=64]/worstaudio",
}
NORMALIZE_FILTER = "dynaudnorm=f=500:g=31:p=0.9:m=8"

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

LOCAL_NAMES = {"ele.local", "ele", "ele.home", "localhost", "print-scan-server", "print-scan-server.local"}
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale addresses

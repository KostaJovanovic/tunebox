"""Where Tunebox keeps its files, and the numbers that tune its behaviour."""
import ipaddress
import os
import socket
import tempfile
from pathlib import Path

WINDOWS = os.name == "nt"
APP_DIR = Path(__file__).resolve().parent.parent   # the Tunebox folder (app.py, run.py, web/)
WEB_DIR = APP_DIR / "web"                            # the pages, their CSS and JS
TOOLS = APP_DIR / "tools"                            # mpv (Windows) and Node, when run.py fetched them
DATA = Path(os.environ.get("TUNEBOX_DATA") or APP_DIR)   # where the files below live
# mpv's control socket: systemd makes /run/tunebox for the service; anything else uses a temp folder
RUN_DIR = Path(os.environ.get("TUNEBOX_RUN") or ("/run/tunebox" if os.path.isdir("/run/tunebox")
                                                 else Path(tempfile.gettempdir()) / f"tunebox-{os.getpid()}"))
AUDIO_OUT = os.environ.get("TUNEBOX_AO", "")        # mpv's --ao (alsa, pipewire, pulse, wasapi...); empty: mpv picks

AUTH_FILE = DATA / "browser.json"          # optional: personal YT Music headers
SETTINGS_FILE = DATA / "settings.json"     # volume + equaliser, survives restarts
SESSION_FILE = DATA / "session.json"       # queue + position, restored paused after a restart
HISTORY_FILE = DATA / "history.json"       # recently played, newest first (shared by everyone)
LISTS_FILE = DATA / "playlists.json"       # Tunebox playlists (shared; anyone adds songs, the owner renames and deletes)
PEOPLE_FILE = DATA / "people.json"         # who's listening: names picked per device (cookie tb_who)
STATS_FILE = DATA / "stats.json"           # when each song played, last STATS_DAYS days (for "Most played")
KEYS_FILE = DATA / "keys.json"             # the admin password's hash and the secret that signs device cookies
PLAYS_DIR = DATA / "plays"                 # the play log, a file per month, kept for good (Stats, recap)
SEMINARS_FILE = DATA / "seminars.json"     # the groups people are in (a house calls them what it likes; here they began as seminars)
HOUSE_FILE = DATA / "house.json"           # what the admin set for the whole house
BLOCK_FILE = DATA / "blocklist.json"       # songs and artists the admin blocked
WALL_FILE = DATA / "wall.json"              # when songs were added from the wall screen (wall.py), for Stats
AUDIT_FILE = DATA / "audit.json"           # what the admin did, and who tried to get in
LOCAL_FILE = DATA / "local.json"            # the local songs: what each uploaded file is (local.py)
LOCAL_DIR = DATA / "local"                  # the files themselves, their covers, and uploads on their way in
TOKEN_FILE = DATA / "cli.token"            # written at every start: reading it proves you are on the server (admin.py)

LIKED_ID = "liked"                          # the built-in "Liked songs" playlist: pinned first, can't be renamed or deleted
TOP_ID = "top"                              # "Top 30": the most played songs of the last STATS_DAYS days, made on every read, never stored
TOP_SIZE = 30
URL_TTL = 4 * 3600                          # stream URLs expire after ~6 h; re-resolve well before that
SESSION_EVERY = 60                          # save queue + position at most this often (seconds), spares the SD card
PLAYED_KEEP = 50                            # played tracks kept in the queue before the current one
FAIL_LIMIT = 3                              # stop after this many streams in a row failed
FAIL_TTL = 60                               # don't retry resolving a failed videoId in the background for this long
RADIO_REFILL_AT = 3                         # refill when this few tracks remain
UNDO_KEEP = 15                              # queue snapshots kept for undo (saved with the session)
UNDO_TRACKS = 200                           # songs kept per snapshot (the current one and what's up next)
PRELOAD_AT = 20                             # hand the next track to mpv this many seconds before the end
SKIP_GRACE = 10                             # Next pressed this close to a song's end is no skip (Stats)
HISTORY_MAX = 300
ADMIN_IDLE = 15 * 60                        # an admin session locks itself after this long without admin work
LOCK_AFTER = 5                              # wrong admin passwords in a row before the lockout
LOCK_FOR = 5 * 60                           # how long nobody can try again
AUDIT_KEEP = 300                            # entries kept in the audit log
STATS_DAYS = 30

SEMINARS = {                                # the groups a new Tunebox starts with; the admin changes them
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

# Host names Tunebox answers to (by IP address it always does): this machine's own name (and name.local),
# the ones in $TUNEBOX_HOSTS (comma separated), and the names of the house it was written for.
_me = socket.gethostname().lower().split(".")[0]
LOCAL_NAMES = ({"localhost", _me, f"{_me}.local", "ele.local", "ele", "ele.home", "print-scan-server", "print-scan-server.local"}
               | {h.strip().lower() for h in os.environ.get("TUNEBOX_HOSTS", "").split(",") if h.strip()})
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale addresses

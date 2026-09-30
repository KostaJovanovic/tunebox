"""Local songs: audio files people uploaded, kept in DATA/local and listed in local.json. They play
like any other song; a local song's videoId is "local:<16 hex>".

There is no ffmpeg here: mpv decodes everything and can encode, and mutagen reads the tags and covers.
WAV and AIFF become FLAC (nothing is lost), formats mpv plays but little else does (WMA, APE, ...)
become Opus, and the common ones (mp3, FLAC, m4a, AAC, Ogg, Opus) stay as uploaded. When mpv can't
encode, the file is kept as it came: mpv plays it anyway.

How much room local songs may take is the admin's to set (house["local"]): a cap in GB, free space
to always leave on the disk, and the biggest file.

`songs` is changed in place, never replaced."""
import asyncio
import base64
import random
import secrets
import shutil
import time
from pathlib import Path

from .config import LOCAL_DIR, LOCAL_FILE, WINDOWS
from .files import read_json, write_json
from .house import house
from .tools import mpv_path

PREFIX = "local:"
COVERS = LOCAL_DIR / "covers"
INCOMING = LOCAL_DIR / ".incoming"            # uploads on their way in: the same disk, so the last step is a rename
GB, MB = 1 << 30, 1 << 20
KEPT = {"mp3", "flac", "m4a", "aac", "ogg", "opus"}   # stay as uploaded
TO_FLAC = {"wav", "aiff"}                     # lossless in, lossless out; everything else becomes Opus
OPUS_RATE = "160k"
COVER_MAX = 5 * MB
IMAGES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}

# {id: {id, title, artist, album, secs, ext, size, sha, by, at, orig, cv, cx}}; cv: the cover's version
# (0: none), cx: its file type
songs: dict[str, dict] = read_json(LOCAL_FILE, {})
_converting = asyncio.Lock()                  # one conversion at a time: the server has music to play
_caps: dict | None = None


def load():
    """The file was replaced (a restore): read it afresh, in place."""
    new = read_json(LOCAL_FILE, {})
    songs.clear()
    songs.update(new)


def save():
    write_json(LOCAL_FILE, songs)


def tidy():
    """At start: uploads that never finished are dropped."""
    shutil.rmtree(INCOMING, ignore_errors=True)


# ---------- ids, paths, the song as the queue knows it ----------
def is_local(vid) -> bool:
    return str(vid or "").startswith(PREFIX)


def song_of(vid) -> dict | None:
    return songs.get(str(vid)[len(PREFIX):]) if is_local(vid) else None


def path_of(vid: str) -> str:
    """The file mpv plays."""
    s = song_of(vid)
    p = LOCAL_DIR / f'{s["id"]}.{s["ext"]}' if s else None
    if not p or not p.exists():
        raise FileNotFoundError("That local song is gone")
    return str(p)


def clock(secs: float) -> str:
    secs = int(round(secs or 0))
    return f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}" if secs else ""


def track(s: dict) -> dict:
    """A local song in the shape every song has (data.TRACK_KEYS). The cover's address is relative, like
    every address the pages use."""
    return {"videoId": PREFIX + s["id"], "title": s["title"], "artist": s["artist"], "album": s["album"],
            "duration": clock(s["secs"]), "thumb": f'api/local/{s["id"]}/cover?v={s["cv"]}' if s.get("cv") else "",
            "artistId": "", "albumId": ""}


def track_of(vid) -> dict | None:
    s = song_of(vid)
    return track(s) if s else None


def search(q: str, limit: int = 20) -> list[dict]:
    """Local songs with every word of q in their title, artist or album."""
    words = q.lower().split()
    hits = [s for s in songs.values() if all(w in f'{s["title"]} {s["artist"]} {s["album"]}'.lower() for w in words)]
    return [track(s) for s in sorted(hits, key=lambda s: s["title"].lower())[:limit]]


def shuffled(but: str = "", limit: int = 30) -> list[dict]:
    """Other local songs in a random order: the radio after a local song YouTube doesn't know."""
    rest = [track(s) for s in songs.values() if PREFIX + s["id"] != but]
    random.shuffle(rest)
    return rest[:limit]


# ---------- room ----------
def used() -> int:
    return sum(s.get("size", 0) for s in songs.values())


def disk() -> dict:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    d = shutil.disk_usage(LOCAL_DIR)
    return {"total": d.total, "free": d.free, "used": used(), "count": len(songs)}


def room() -> int:
    """How many more bytes of local songs fit: under the admin's cap, and leaving the reserve free."""
    lim, d = house["local"], disk()
    left = d["free"] - int((lim.get("reserveGB") or 0) * GB)
    if lim.get("capGB") is not None:
        left = min(left, int(lim["capGB"] * GB) - d["used"])
    return max(0, left)


# ---------- what a file is ----------
def sniff(head: bytes) -> str | None:
    """The kind of audio file that starts with these bytes, or None. Only real audio is kept and handed
    to mpv: a playlist dressed up as a song would make mpv open whatever it lists."""
    four = head[:4]
    if four == b"fLaC":
        return "flac"
    if four == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if four == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if four == b"OggS":
        return "opus" if b"OpusHead" in head[:64] else "ogg"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "aac"                          # ADTS
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        return "mp3"
    if head[:16] == bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"):
        return "wma"
    return {b"MAC ": "ape", b"wvpk": "wv", b"MPCK": "mpc", b"TTA1": "tta", b".snd": "au", b"caff": "caf", b"DSD ": "dsf",
            b"\x1aE\xdf\xa3": "mka"}.get(four) or ("mpc" if head[:3] == b"MP+" else "amr" if head[:5] == b"#!AMR" else
                                                    "ac3" if head[:2] == b"\x0bw" else None)


def image_kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "gif" if data[:6] in (b"GIF87a", b"GIF89a") else None


def _cover(f) -> bytes | None:
    """The picture inside an audio file, wherever its format keeps it."""
    tags = f.tags
    if getattr(f, "pictures", None):          # FLAC
        return f.pictures[0].data
    if tags is None:
        return None
    for k in tags.keys():
        if str(k).startswith("APIC"):         # ID3: mp3, and WAV or AIFF that carry ID3
            return tags[k].data
    if "covr" in tags:                        # m4a
        return bytes(tags["covr"][0])
    for b64 in tags.get("metadata_block_picture") or []:   # Ogg Vorbis, Opus
        from mutagen.flac import Picture
        return Picture(base64.b64decode(b64)).data
    return None


def read_tags(path: Path) -> dict:
    """Title, artist, album, length and cover from the file's own tags; empty where it has none."""
    out = {"title": "", "artist": "", "album": "", "secs": 0.0, "cover": None}
    try:
        import mutagen
        f = mutagen.File(path)
        if f is None:
            return out
        out["secs"] = float(getattr(f.info, "length", 0) or 0)
        try:
            out["cover"] = _cover(f)
        except Exception:
            pass
        easy = mutagen.File(path, easy=True)
        for k in ("title", "artist", "album"):
            v = (easy.tags or {}).get(k) if easy is not None else None
            out[k] = " ".join(str(v[0]).split())[:300] if v else ""
    except Exception:
        pass                                  # a file mutagen can't read: mpv may still know it
    return out


# ---------- mpv as the converter ----------
async def run_mpv(*args: str, timeout: float = 900) -> tuple[int, str]:
    """mpv on its own, away from the one that plays: (exit code, what it printed)."""
    exe = mpv_path()
    if not exe:
        return 1, ""
    nice = [] if WINDOWS or not shutil.which("nice") else ["nice", "-n", "15"]   # the music comes first
    try:
        proc = await asyncio.create_subprocess_exec(
            *nice, exe, "--no-config", "--no-video", "--ytdl=no", "--load-unsafe-playlists=no", *args,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except (OSError, NotImplementedError):
        return 1, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, ""
    return proc.returncode or 0, out.decode(errors="replace")


async def mpv_caps() -> dict:
    """Which encoders this mpv has: {"mpv": found at all, "flac": ..., "opus": ...}. Asked once."""
    global _caps
    if _caps is None:
        rc, out = await run_mpv("--oac=help", timeout=20)
        names = {line.split()[0].removeprefix("--oac=") for line in out.splitlines() if line.strip().startswith("--oac=")}
        _caps = {"mpv": bool(mpv_path()), "flac": "flac" in names, "opus": "libopus" in names}
    return _caps


async def mpv_secs(path: Path) -> float:
    """A file's length, as mpv sees it (for files mutagen doesn't know); 0 if mpv can't play it."""
    rc, out = await run_mpv("--ao=null", "--length=0.05", "--term-playing-msg=TBLEN=${=duration}", str(path), timeout=60)
    for line in out.splitlines():
        if line.startswith("TBLEN="):
            try:
                return float(line[6:])
            except ValueError:
                pass
    return 0.0


async def convert(src: Path, kind: str) -> tuple[Path, str]:
    """WAV and AIFF to FLAC, odd formats to Opus; (the file to keep, its type). On any trouble the
    original stays."""
    if kind in KEPT:
        return src, kind
    to = "flac" if kind in TO_FLAC else "opus"
    if not (await mpv_caps())[to]:
        return src, kind
    out = src.with_name(f"{src.stem}.conv.{to}")
    codec = ["--oac=flac"] if to == "flac" else ["--oac=libopus", f"--oacopts=b={OPUS_RATE}"]
    async with _converting:
        rc, _ = await run_mpv(str(src), f"--o={out}", *codec, "--msg-level=all=error")
    if rc != 0 or not out.exists() or not out.stat().st_size:
        out.unlink(missing_ok=True)
        return src, kind
    src.unlink(missing_ok=True)
    return out, to


# ---------- adding, changing, removing ----------
def title_from(name: str) -> str:
    stem = Path(name.replace("\\", "/").rsplit("/", 1)[-1]).stem
    return " ".join(stem.replace("_", " ").split())[:300] or "Untitled"


def put_cover(s: dict, data: bytes | None) -> bool:
    """Saves a song's cover (the caller saves the index); False if these bytes aren't a picture."""
    kind = image_kind(data or b"")
    if not kind or len(data) > COVER_MAX:
        return False
    COVERS.mkdir(parents=True, exist_ok=True)
    for old in COVERS.glob(f'{s["id"]}.*'):
        old.unlink(missing_ok=True)
    (COVERS / f'{s["id"]}.{kind}').write_bytes(data)
    s["cv"], s["cx"] = s.get("cv", 0) + 1, kind
    return True


def cover_of(sid: str) -> tuple[Path, str] | None:
    s = songs.get(sid)
    p = COVERS / f'{sid}.{s["cx"]}' if s and s.get("cv") else None
    return (p, IMAGES[s["cx"]]) if p and p.exists() else None


async def add_file(part: Path, name: str, sha: str, by: str) -> dict:
    """An upload that arrived whole becomes a song. ValueError (with the message for the person) if it
    isn't audio. `part` is gone afterwards either way."""
    try:
        with part.open("rb") as f:
            kind = sniff(f.read(64))
        if not kind:
            raise ValueError("That isn't an audio file")
        tags = await asyncio.to_thread(read_tags, part)   # from the file as it came: a conversion drops the cover
        src = part.with_suffix("." + kind)
        part.replace(src)
        part = src
        part, ext = await convert(part, kind)
        secs = tags["secs"] or (await asyncio.to_thread(read_tags, part))["secs"] or await mpv_secs(part)
        if not secs:
            raise ValueError("That isn't an audio file Tunebox can read")
        sid = secrets.token_hex(8)
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        final = LOCAL_DIR / f"{sid}.{ext}"
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    s = {"id": sid, "title": tags["title"] or title_from(name), "artist": tags["artist"], "album": tags["album"],
         "secs": round(secs, 1), "ext": ext, "size": final.stat().st_size, "sha": sha, "by": by, "at": int(time.time()),
         "orig": name.replace("\\", "/").rsplit("/", 1)[-1][:200], "was": kind, "cv": 0, "cx": ""}
    put_cover(s, tags["cover"])
    songs[sid] = s
    save()
    return s


def remove(sid: str) -> dict | None:
    s = songs.pop(sid, None)
    if s:
        for p in [LOCAL_DIR / f'{sid}.{s["ext"]}', *COVERS.glob(f"{sid}.*")]:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass                          # Windows: mpv still has it open; the file stays behind, unlisted
        save()
    return s

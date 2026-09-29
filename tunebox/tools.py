"""The programs Tunebox drives: mpv (plays the audio) and Node (yt-dlp needs it for YouTube's
challenges). Found where they're installed, or fetched into tools/ next to the app by run.py.

  mpv:  $TUNEBOX_MPV, tools/mpv/mpv.exe (Windows), or mpv on the PATH (Linux: the mpv package)
  Node: ../node/bin/node (the server layout), tools/node, or node on the PATH if it's 22 or newer"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import APP_DIR, TOOLS, WINDOWS

NODE_MAJOR = 22                               # yt-dlp's challenge solver needs this or newer
MPV_BUILDS = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"


def say(msg: str):
    print(f"[tunebox] {msg}", flush=True)


# ---------- finding them ----------
def mpv_path() -> str | None:
    for p in (os.environ.get("TUNEBOX_MPV"), TOOLS / "mpv" / "mpv.exe" if WINDOWS else None):
        if p and Path(p).exists():
            return str(p)
    return shutil.which("mpv")


def node_major(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def node_path() -> str | None:
    for p in (APP_DIR.parent / "node" / "bin" / "node", TOOLS / "node" / "bin" / "node", TOOLS / "node" / "node.exe"):
        if p.exists():
            return str(p)
    exe = shutil.which("node")
    return exe if exe and node_major(exe) >= NODE_MAJOR else None


# ---------- fetching them (run.py, the first time) ----------
def download(url: str, dest: Path):
    with urllib.request.urlopen(url, timeout=600) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def fetch_mpv() -> str:
    """Windows only: the usual mpv build for 64-bit PCs (Linux gets mpv from its packages)."""
    with urllib.request.urlopen(MPV_BUILDS, timeout=30) as r:
        rel = json.load(r)
    asset = next(a for a in rel["assets"] if a["name"].startswith("mpv-x86_64-") and "-v3-" not in a["name"])
    say(f"downloading mpv ({asset['size'] // 1048576} MB, first run only)")
    dest = TOOLS / "mpv"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset["name"]
        download(asset["browser_download_url"], archive)
        # Windows' own tar (libarchive) reads these .7z files; Python's 7z modules can't (BCJ2 filter)
        tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
        subprocess.run([str(tar), "-xf", str(archive), "-C", str(dest)], check=True)
    exe = dest / "mpv.exe"
    if not exe.exists():
        raise RuntimeError(f"mpv.exe was not in {asset['name']}")
    return str(exe)


def fetch_node() -> str:
    """The newest Node 22 from nodejs.org, unpacked into tools/node."""
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armv7l"}.get(platform.machine().lower())
    if not arch:
        raise RuntimeError(f"no Node build for {platform.machine()}")
    kind = f"win-{arch}-zip" if WINDOWS else f"linux-{arch}"
    with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=30) as r:
        rel = next(v for v in json.load(r) if v["version"].startswith(f"v{NODE_MAJOR}.") and kind in v["files"])
    name = f"node-{rel['version']}-{'win' if WINDOWS else 'linux'}-{arch}"
    url = f"https://nodejs.org/dist/{rel['version']}/{name}.{'zip' if WINDOWS else 'tar.xz'}"
    say(f"downloading Node {rel['version']} (first run only)")
    TOOLS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / url.rsplit("/", 1)[1]
        download(url, archive)
        if WINDOWS:
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="tar")
        shutil.rmtree(TOOLS / "node", ignore_errors=True)
        shutil.move(str(Path(tmp) / name), str(TOOLS / "node"))
    return node_path() or ""


def ensure() -> bool:
    """Everything Tunebox needs to play; False (with the reason printed) if something is missing."""
    ok = True
    if not mpv_path():
        if WINDOWS:
            try:
                fetch_mpv()
            except Exception as exc:
                say(f"could not get mpv: {exc}")
                ok = False
        else:
            say("mpv is missing: install it (Debian/Ubuntu: sudo apt install mpv), or run install.sh")
            ok = False
    if not node_path():
        try:
            fetch_node()
        except Exception as exc:              # it still plays most songs without it
            say(f"could not get Node {NODE_MAJOR}: {exc}. Some songs may not play.")
    return ok


def end_children_with_us():
    """Windows: every child process (mpv) ends when this one does, however it ends; otherwise
    closing the window could leave mpv playing on its own."""
    if not WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))   # JobObjectExtendedLimitInformation
    k.AssignProcessToJobObject(job, k.GetCurrentProcess())
    end_children_with_us.job = job            # the handle must live as long as we do


if __name__ == "__main__":
    sys.exit(0 if ensure() else 1)

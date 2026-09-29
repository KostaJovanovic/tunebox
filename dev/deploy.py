"""Pushes Tunebox to ele and pulls ele's Tunebox data for the emulator.

  python dev/deploy.py check       is ele reachable from here? (exit 0 = yes)
  python dev/deploy.py deploy      upload what changed, restart what needs it
  python dev/deploy.py status      same comparison as deploy, but changes nothing
  python dev/deploy.py pull-data   copy ele's live data (playlists, history, people...) into dev/data

Only app code is deployed (MODULES). The systemd unit is compared and reported, never
installed: that stays a deliberate job by hand. ele's other apps (the launcher, Caddy,
Paper) live in the homeapps repository, with a deploy tool of their own.

It logs in with this PC's SSH key when ele accepts it; otherwise the SSH user and
password are asked for every run and never stored.
"""
import datetime
import difflib
import getpass
import hashlib
import json
import os
import posixpath
import shlex
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ele's address comes from DHCP (it was 10.100.0.62, then 10.100.0.105), so try its mDNS name
# first; ELE_HOST overrides. HOST becomes whichever answers first (see reachable()).
CANDIDATES = [os.environ["ELE_HOST"]] if os.environ.get("ELE_HOST") else ["ele.local", "10.100.0.105", "10.100.0.62"]
HOST = CANDIDATES[0]
KEEP_BACKUPS = 10

# local folder -> folder on ele, what gets deployed, and how to tell it's healthy.
#   files: single files in the folder.  dirs: whole folders, mirrored (a file deleted here is
#   deleted on ele too).  retired: old files that no longer belong on ele and are removed there.
MODULES = [
    {"name": "music", "local": ".", "remote": "/opt/homeapps/tunebox",
     "files": ["app.py"], "dirs": ["tunebox", "web"], "retired": ["index.html", "classic.html", "wall.html"],
     "health": "http://127.0.0.1:8888/api/state"},
]
SKIP = {"__pycache__", ".bak"}                           # never deployed, never removed on ele
# compared and reported only
SYSTEM_FILES = [
    ("tunebox.service", "/etc/systemd/system/tunebox.service"),
]
# ele's live data -> dev/data (browser.json, the YouTube sign-in cookies, is left on ele)
DATA_FILES = [(f"/opt/homeapps/tunebox/{f}", f) for f in
              ("settings.json", "playlists.json", "history.json", "session.json", "people.json",
               "stats.json", "seminars.json", "keys.json")]


def say(tag, msg=""):
    print(f"[{tag}]".ljust(8) + msg, flush=True)


def reachable(timeout=3.0) -> bool:
    """True when ele answers on SSH at one of the candidate addresses; HOST is set to that one."""
    global HOST
    for host in CANDIDATES:
        try:
            with socket.create_connection((host, 22), timeout=timeout):
                HOST = host
                return True
        except OSError:
            continue
    return False


def connect():
    import paramiko
    # this PC's SSH key (~/.ssh/id_ed25519, installed for dietpi on 2026-09-29) first, no prompts
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username="dietpi", look_for_keys=True, allow_agent=True, timeout=10)
        say("ssh", f"key login as dietpi@{HOST}")
        return c
    except paramiko.AuthenticationException:
        pass
    except (paramiko.SSHException, OSError):
        pass
    for attempt in range(3):
        user = input(f"ssh user for {HOST} [dietpi]: ").strip() or "dietpi"
        pw = getpass.getpass(f"password for {user}@{HOST}: ")
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(HOST, username=user, password=pw, look_for_keys=False, allow_agent=False, timeout=10)
            return c
        except paramiko.AuthenticationException:
            say("err", "wrong user or password")
        except OSError as e:
            say("err", f"can't connect: {e}")
            return None
    return None


class Ele:
    def __init__(self, client):
        self.c = client
        self.sftp = client.open_sftp()

    def run(self, cmd, check=True):
        _, out, err = self.c.exec_command(cmd)
        rc = out.channel.recv_exit_status()
        o, e = out.read().decode(errors="replace"), err.read().decode(errors="replace")
        if check and rc != 0:
            raise RuntimeError(f"`{cmd}` failed ({rc}): {(e or o).strip()[:400]}")
        return rc, o, e

    def read(self, path) -> bytes | None:
        try:
            with self.sftp.open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def hashes(self, paths) -> dict:
        _, o, _ = self.run("sha256sum " + " ".join(shlex.quote(p) for p in paths) + " 2>/dev/null", check=False)
        return {line[66:]: line[:64] for line in o.splitlines() if len(line) > 66}

    def service_for(self, remote_dir) -> str | None:
        """The systemd unit that runs from this folder, found rather than hard-coded."""
        _, o, _ = self.run(f"grep -l '^WorkingDirectory={remote_dir}$' /etc/systemd/system/*.service 2>/dev/null",
                           check=False)
        units = [posixpath.basename(u).removesuffix(".service") for u in o.split()]
        return units[0] if units else None


def quoted(paths) -> str:
    return " ".join(shlex.quote(p) for p in paths)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_delta(old: bytes | None, new: bytes) -> str:
    if old is None:
        return "new file"
    a, b = old.decode(errors="replace").splitlines(), new.decode(errors="replace").splitlines()
    plus = minus = 0
    for d in difflib.unified_diff(a, b, lineterm="", n=0):
        if d.startswith("+") and not d.startswith("+++"):
            plus += 1
        elif d.startswith("-") and not d.startswith("---"):
            minus += 1
    return f"+{plus} -{minus} lines"


def local_files(m) -> list[str]:
    """The module's deployable files, as paths relative to its folder (posix style)."""
    base = ROOT / m["local"]
    out = [f for f in m["files"] if (base / f).is_file()]
    for d in m.get("dirs", []):
        for p in sorted((base / d).rglob("*")):
            rel = p.relative_to(base)
            if p.is_file() and not SKIP & set(rel.parts) and not p.name.startswith("."):
                out.append(rel.as_posix())
    return out


def remote_files(ele: Ele, m) -> list[str]:
    """What ele has in the module's mirrored folders (plus retired files still there), relative to its folder."""
    out = []
    for d in m.get("dirs", []):
        _, o, _ = ele.run(f"cd {m['remote']} && find {shlex.quote(d)} -type f 2>/dev/null", check=False)
        out += [f for f in o.split("\n") if f and not SKIP & set(f.split("/"))]
    return out + [f for f in m.get("retired", []) if ele.read(posixpath.join(m["remote"], f)) is not None]


def compare(ele: Ele):
    """Files whose content differs from ele's copy, and files on ele that should go."""
    changes, removals = [], []
    for m in MODULES:
        mine = local_files(m)
        theirs = ele.hashes(posixpath.join(m["remote"], f) for f in mine)
        for f in mine:
            remote, local = posixpath.join(m["remote"], f), ROOT / m["local"] / f
            if sha(local) != theirs.get(remote):
                changes.append((m, f, line_delta(ele.read(remote), local.read_bytes())))
        removals += [(m, f) for f in remote_files(ele, m) if f not in mine]
    return changes, removals


def report_system(ele: Ele):
    theirs = ele.hashes([r for _, r in SYSTEM_FILES])
    for local, remote in SYSTEM_FILES:
        lp = ROOT / local
        if not lp.exists():
            continue
        if remote not in theirs:
            say("sys", f"{local}: not found at {remote} on ele (or not readable)")
        elif sha(lp) != theirs[remote]:
            say("sys", f"{local} differs from {remote} - NOT deployed, install it by hand if intended")


def healthy(ele: Ele, m, service) -> bool:
    for _ in range(20):
        time.sleep(1)
        rc, o, _ = ele.run(f"systemctl is-active {service}", check=False)
        if o.strip() != "active":
            continue
        if not m["health"]:
            return True
        rc, o, _ = ele.run(f"curl -s -o /dev/null -w '%{{http_code}}' {m['health']}", check=False)
        if o.strip() == "200":
            return True
    return False


def tunebox_playing(ele: Ele) -> bool:
    """Tunebox restores its queue paused after a restart; note whether it was playing."""
    rc, o, _ = ele.run("curl -s --max-time 5 http://127.0.0.1:8888/api/state", check=False)
    try:
        st = json.loads(o)
        return bool(st.get("current")) and not st.get("paused") and not st.get("idle")
    except ValueError:
        return False


def resume_tunebox(ele: Ele):
    """Presses play again, so a deploy is only a short gap in the music."""
    for _ in range(10):
        rc, o, _ = ele.run("curl -s --max-time 5 -H 'Content-Type: application/json' "
                           "-d '{\"action\":\"toggle\"}' http://127.0.0.1:8888/api/control", check=False)
        if '"ok"' in o:
            say("ok", "music was playing - pressed play again")
            return
        time.sleep(1)
    say("warn", "music was playing but didn't resume - press play in Tunebox")


def deploy(dry=False) -> int:
    if not reachable():
        say("ele", f"{HOST} is not reachable from here - nothing deployed")
        return 1
    client = connect()
    if not client:
        return 1
    ele = Ele(client)
    changes, removals = compare(ele)
    report_system(ele)
    if not changes and not removals:
        say("ele", "ele already runs exactly these files - nothing to deploy")
        return 0
    print()
    for m, f, delta in changes:
        say("diff", f"{m['local']}/{f}  ->  {m['remote']}/{f}   ({delta})")
    for m, f in removals:
        say("gone", f"{m['remote']}/{f}   (no longer in {m['local']}/, will be removed)")
    if dry:
        return 0
    if input("\nupload these to ele? (y/n): ").strip().lower() != "y":
        say("ele", "skipped - nothing uploaded")
        return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = f"/tmp/tunebox-deploy-{stamp}"
    failed = False
    by_module = {}
    for m, f, _ in changes:
        by_module.setdefault(m["name"], [m, [], []])[1].append(f)
    for m, f in removals:
        by_module.setdefault(m["name"], [m, [], []])[2].append(f)
    for name, (m, files, gone) in by_module.items():
        rdir, bak = m["remote"], f"{m['remote']}/.bak/{stamp}"
        existing = []
        try:
            for f in files:
                ele.run(f"mkdir -p {tmp}/{name}/{posixpath.dirname(f) or '.'}")
                ele.sftp.put(str(ROOT / m["local"] / f), f"{tmp}/{name}/{f}")
                if f.endswith(".py"):     # never swap in a file that doesn't even compile
                    ele.run(f"/opt/homeapps/venv/bin/python -m py_compile {tmp}/{name}/{f}")
            existing = [f for f in files + gone if ele.read(f"{rdir}/{f}") is not None]
            ele.run(f"sudo mkdir -p {bak} && sudo chown --reference={rdir} {rdir}/.bak {bak}"   # the app's owner, not root
                    + (f" && cd {rdir} && sudo cp -p --parents {quoted(existing)} {bak}/" if existing else ""))
            ele.run(f"cd {rdir}/.bak && ls -1d */ | head -n -{KEEP_BACKUPS} | xargs -r sudo rm -rf")
            for f in files:              # cp onto the old file keeps its owner and mode
                d = posixpath.dirname(f)
                ele.run((f"sudo mkdir -p {rdir}/{d} && sudo chown --reference={rdir} {rdir}/{d} && " if d else "")
                        + f"sudo cp {tmp}/{name}/{f} {rdir}/{f} && sudo chown --reference={rdir} {rdir}/{f}")
            if gone:
                ele.run(f"cd {rdir} && sudo rm -f {quoted(gone)}")
                for d in m.get("dirs", []):   # folders left empty go too
                    ele.run(f"cd {rdir} && [ -d {d} ] && sudo find {d} -mindepth 1 -type d -empty -delete", check=False)
            say("up", f"{name}: {len(files)} updated, {len(gone)} removed (old copies in {bak})")
        except RuntimeError as e:
            say("err", f"{name}: {e}")
            failed = True
            continue

        if not any(f.endswith(".py") for f in files + gone):
            continue                     # pages, CSS and JS are read from disk per request
        service = ele.service_for(rdir)
        if not service:
            say("warn", f"{name}: no systemd unit runs from {rdir} - restart it by hand")
            continue
        playing = name == "music" and tunebox_playing(ele)
        say("svc", f"restarting {service}")
        ele.run(f"sudo systemctl restart {service}", check=False)
        if healthy(ele, m, service):
            say("ok", f"{service} is up")
            if playing:
                resume_tunebox(ele)
            continue
        failed = True
        say("err", f"{service} did not come back healthy. Last log lines:")
        print(ele.run(f"sudo journalctl -u {service} -n 25 --no-pager", check=False)[1])
        if input(f"roll {name} back to the previous files? (y/n): ").strip().lower() == "y":
            added = [f for f in files if f not in existing]
            if added:
                ele.run(f"cd {rdir} && sudo rm -f {quoted(added)}", check=False)
            if existing:
                ele.run(f"sudo cp -a {bak}/. {rdir}/", check=False)
            ele.run(f"sudo systemctl restart {service}", check=False)
            back = healthy(ele, m, service)
            say("ok" if back else "err", f"{service} rolled back" + ("" if back else " but still not healthy"))
    ele.run(f"rm -rf {tmp}", check=False)
    client.close()
    return 1 if failed else 0


def pull_data() -> int:
    if not reachable():
        say("ele", f"{HOST} is not reachable from here")
        return 1
    print("This replaces the emulator's local data with ele's live data (the old local copy is kept).")
    print("Stop server.bat first, or it may write over what arrives.")
    client = connect()
    if not client:
        return 1
    ele = Ele(client)
    data = ROOT / "dev" / "data"
    keep = data / ".old" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for remote, local in DATA_FILES:
        body = ele.read(remote)
        if body is None:
            say("skip", f"{remote} (not on ele)")
            continue
        dest = data / local
        if dest.exists():
            (keep / local).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, keep / local)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        say("got", f"{remote} -> dev/data/{local}")
    client.close()
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        ok = reachable()
        say("ele", f"reachable at {HOST}" if ok else f"not reachable (tried {', '.join(CANDIDATES)})")
        return 0 if ok else 1
    if cmd in ("deploy", "status"):
        return deploy(dry=cmd == "status")
    if cmd == "pull-data":
        return pull_data()
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)

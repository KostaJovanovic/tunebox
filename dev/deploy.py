"""Pushes Tunebox to a server and pulls a server's Tunebox data for the emulator.

  python dev/deploy.py check [SERVER]       is the server reachable from here? (exit 0 = yes)
  python dev/deploy.py deploy [SERVER]      upload what changed, restart Tunebox if Python changed
  python dev/deploy.py status [SERVER]      same comparison as deploy, but changes nothing
  python dev/deploy.py pull-data [SERVER]   copy the server's data (playlists, history, people...) into dev/data
  python dev/deploy.py servers              list, add or remove servers
  --ask: with several servers and none named, ask which one instead of taking the default

The servers live in dev/servers.json on each device (see servers.py). Without it, ele is the
server. Where Tunebox lives on a server, which Python runs it and on which port is read from
its systemd unit (`tunebox` unless the server names another "service"), so it works for ele
and for a server set up with install.sh. A server can pin these in servers.json instead:
"dir", "python", "port", "data", "service".

Only app code is deployed. The systemd unit is compared and reported (on a server that runs
this repo's tunebox.service, like ele), never installed: that stays a deliberate job by hand.
"""
import datetime
import difflib
import hashlib
import json
import posixpath
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import servers  # noqa: E402
from servers import Server, say  # noqa: E402

KEEP_BACKUPS = 10
# ele, the home server, is the built-in server. Its address comes from DHCP (10.100.0.62, then
# 10.100.0.105), so its mDNS name is tried first.
BUILTIN = {"name": "ele", "hosts": ["ele.local", "10.100.0.105", "10.100.0.62"], "user": "dietpi"}

# what gets deployed, relative to this folder and to Tunebox's folder on the server
#   files: single files.  dirs: whole folders, mirrored (a file deleted here is deleted there
#   too).  retired: old files that no longer belong there and are removed.
FILES = ["app.py"]
DIRS = ["tunebox", "web"]
RETIRED = ["index.html", "classic.html", "wall.html"]
SKIP = {"__pycache__", ".bak"}                           # never deployed, never removed there
UNIT = ROOT / "tunebox.service"                          # ele's unit: compared and reported only
# the server's live data -> dev/data (browser.json, the YouTube sign-in cookies, stays there)
DATA_FILES = ["settings.json", "playlists.json", "history.json", "session.json", "people.json",
              "stats.json", "seminars.json", "keys.json"]


def open_server(name: str, choose: bool):
    """The server to use and an SSH session to it, or (server, None) when that fails."""
    server = servers.pick(BUILTIN, name, choose)
    if not server:
        return None, None
    host = servers.reachable(server)
    if not host:
        say("srv", f"{server['name']} is not reachable from here (tried {', '.join(server['hosts'])})")
        return server, None
    return server, Server.connect(server, host)


def target(server: dict, srv: Server) -> dict | None:
    """Where Tunebox lives on the server: its unit, folder, Python, port and data folder."""
    service = server.get("service", "tunebox")
    unit = srv.unit(service)
    start = unit.get("ExecStart", "")
    exe = shlex.split(start)[0].lstrip("@-:+!") if start else ""
    python = server.get("python") or (exe if posixpath.basename(exe).startswith("python")
                                      else posixpath.join(posixpath.dirname(exe), "python") if "/" in exe else "")
    port = re.search(r"--port[= ](\d+)", start)
    t = {"service": service, "dir": server.get("dir") or unit.get("WorkingDirectory", ""), "python": python,
         "port": int(server.get("port") or unit["env"].get("TUNEBOX_PORT") or (port and port.group(1)) or 8888)}
    t["data"] = server.get("data") or unit["env"].get("TUNEBOX_DATA") or t["dir"]
    if not t["dir"] or not t["python"]:
        say("err", f"no {service}.service on {server['name']} to read Tunebox's folder and Python from. Set "
                   f"\"dir\" and \"python\" for it in {servers.FILE.name}, or set Tunebox up there with install.sh")
        return None
    say("srv", f"{server['name']}: {t['dir']} ({service}.service, port {t['port']})")
    return t


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


def local_files() -> list[str]:
    """The deployable files, as paths relative to this folder (posix style)."""
    out = [f for f in FILES if (ROOT / f).is_file()]
    for d in DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            rel = p.relative_to(ROOT)
            if p.is_file() and not SKIP & set(rel.parts) and not p.name.startswith("."):
                out.append(rel.as_posix())
    return out


def remote_files(srv: Server, rdir) -> list[str]:
    """What the server has in the mirrored folders (plus retired files still there), relative to rdir."""
    out = []
    for d in DIRS:
        _, o, _ = srv.run(f"cd {rdir} && find {shlex.quote(d)} -type f 2>/dev/null", check=False)
        out += [f for f in o.split("\n") if f and not SKIP & set(f.split("/"))]
    return out + [f for f in RETIRED if srv.read(posixpath.join(rdir, f)) is not None]


def compare(srv: Server, rdir):
    """Files whose content differs from the server's copy, and files there that should go."""
    mine = local_files()
    theirs = srv.hashes(posixpath.join(rdir, f) for f in mine)
    changes = [(f, line_delta(srv.read(posixpath.join(rdir, f)), (ROOT / f).read_bytes()))
               for f in mine if sha(ROOT / f) != theirs.get(posixpath.join(rdir, f))]
    removals = [f for f in remote_files(srv, rdir) if f not in mine]
    return changes, removals


def report_system(srv: Server, t):
    """This repo's tunebox.service is ele's unit: report when a server that runs it has another version."""
    if f"WorkingDirectory={t['dir']}\n" not in UNIT.read_text(encoding="utf-8"):
        return                                           # a server set up with install.sh has its own unit
    remote = f"/etc/systemd/system/{t['service']}.service"
    theirs = srv.hashes([remote])
    if remote not in theirs:
        say("sys", f"tunebox.service: not found at {remote} (or not readable)")
    elif sha(UNIT) != theirs[remote]:
        say("sys", f"tunebox.service differs from {remote} - NOT deployed, install it by hand if intended")


def healthy(srv: Server, t) -> bool:
    for _ in range(20):
        time.sleep(1)
        rc, o, _ = srv.run(f"systemctl is-active {t['service']}", check=False)
        if o.strip() != "active":
            continue
        rc, o, _ = srv.run(f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{t['port']}/api/state", check=False)
        if o.strip() == "200":
            return True
    return False


def tunebox_playing(srv: Server, t) -> bool:
    """Tunebox restores its queue paused after a restart; note whether it was playing."""
    rc, o, _ = srv.run(f"curl -s --max-time 5 http://127.0.0.1:{t['port']}/api/state", check=False)
    try:
        st = json.loads(o)
        return bool(st.get("current")) and not st.get("paused") and not st.get("idle")
    except ValueError:
        return False


def resume_tunebox(srv: Server, t):
    """Presses play again, so a deploy is only a short gap in the music."""
    for _ in range(10):
        rc, o, _ = srv.run("curl -s --max-time 5 -H 'Content-Type: application/json' "
                           f"-d '{{\"action\":\"toggle\"}}' http://127.0.0.1:{t['port']}/api/control", check=False)
        if '"ok"' in o:
            say("ok", "music was playing - pressed play again")
            return
        time.sleep(1)
    say("warn", "music was playing but didn't resume - press play in Tunebox")


def deploy(name="", choose=False, dry=False) -> int:
    server, srv = open_server(name, choose)
    if not srv:
        return 1
    try:
        t = target(server, srv)
        return push(server, srv, t, dry) if t else 1
    finally:
        srv.close()


def push(server, srv: Server, t, dry) -> int:
    rdir, where = t["dir"], server["name"]
    changes, removals = compare(srv, rdir)
    report_system(srv, t)
    if not changes and not removals:
        say("srv", f"{where} already runs exactly these files - nothing to deploy")
        return 0
    print()
    for f, delta in changes:
        say("diff", f"{f}  ->  {rdir}/{f}   ({delta})")
    for f in removals:
        say("gone", f"{rdir}/{f}   (no longer here, will be removed)")
    if dry:
        return 0
    if input(f"\nupload these to {where}? (y/n): ").strip().lower() != "y":
        say("srv", "skipped - nothing uploaded")
        return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp, bak = f"/tmp/tunebox-deploy-{stamp}", f"{rdir}/.bak/{stamp}"
    files, gone = [f for f, _ in changes], removals
    existing = []
    try:
        for f in files:
            srv.run(f"mkdir -p {tmp}/{posixpath.dirname(f) or '.'}")
            srv.sftp.put(str(ROOT / f), f"{tmp}/{f}")
            if f.endswith(".py"):         # never swap in a file that doesn't even compile
                srv.run(f"{t['python']} -m py_compile {tmp}/{f}")
        existing = [f for f in files + gone if srv.read(f"{rdir}/{f}") is not None]
        srv.run(f"sudo mkdir -p {bak} && sudo chown --reference={rdir} {rdir}/.bak {bak}"   # the app's owner, not root
                + (f" && cd {rdir} && sudo cp -p --parents {quoted(existing)} {bak}/" if existing else ""))
        srv.run(f"cd {rdir}/.bak && ls -1d */ | head -n -{KEEP_BACKUPS} | xargs -r sudo rm -rf")
        for f in files:                   # cp onto the old file keeps its owner and mode
            d = posixpath.dirname(f)
            srv.run((f"sudo mkdir -p {rdir}/{d} && sudo chown --reference={rdir} {rdir}/{d} && " if d else "")
                    + f"sudo cp {tmp}/{f} {rdir}/{f} && sudo chown --reference={rdir} {rdir}/{f}")
        if gone:
            srv.run(f"cd {rdir} && sudo rm -f {quoted(gone)}")
            for d in DIRS:                # folders left empty go too
                srv.run(f"cd {rdir} && [ -d {d} ] && sudo find {d} -mindepth 1 -type d -empty -delete", check=False)
        say("up", f"{len(files)} updated, {len(gone)} removed (old copies in {bak})")
    except RuntimeError as e:
        say("err", str(e))
        srv.run(f"rm -rf {tmp}", check=False)
        return 1
    srv.run(f"rm -rf {tmp}", check=False)

    if not any(f.endswith(".py") for f in files + gone):
        return 0                          # pages, CSS and JS are read from disk per request
    service = t["service"]
    playing = tunebox_playing(srv, t)
    say("svc", f"restarting {service}")
    srv.run(f"sudo systemctl restart {service}", check=False)
    if healthy(srv, t):
        say("ok", f"{service} is up")
        if playing:
            resume_tunebox(srv, t)
        return 0
    say("err", f"{service} did not come back healthy. Last log lines:")
    print(srv.run(f"sudo journalctl -u {service} -n 25 --no-pager", check=False)[1])
    if input("roll back to the previous files? (y/n): ").strip().lower() == "y":
        added = [f for f in files if f not in existing]
        if added:
            srv.run(f"cd {rdir} && sudo rm -f {quoted(added)}", check=False)
        if existing:
            srv.run(f"sudo cp -a {bak}/. {rdir}/", check=False)
        srv.run(f"sudo systemctl restart {service}", check=False)
        back = healthy(srv, t)
        say("ok" if back else "err", f"{service} rolled back" + ("" if back else " but still not healthy"))
    return 1


def pull_data(name="", choose=False) -> int:
    server, srv = open_server(name, choose)
    if not srv:
        return 1
    print(f"This replaces the emulator's local data with {server['name']}'s live data (the old local copy is kept).")
    print("Stop server.bat first, or it may write over what arrives.")
    try:
        t = target(server, srv)
        if not t:
            return 1
        data = ROOT / "dev" / "data"
        keep = data / ".old" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        for f in DATA_FILES:
            remote = posixpath.join(t["data"], f)
            body = srv.read(remote)
            if body is None:
                say("skip", f"{remote} (not there)")
                continue
            dest = data / f
            if dest.exists():
                keep.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, keep / f)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            say("got", f"{remote} -> dev/data/{f}")
        return 0
    finally:
        srv.close()


def main():
    args = [a for a in sys.argv[1:] if a != "--ask"]
    choose = "--ask" in sys.argv
    cmd, name = (args + ["", ""])[:2]
    if cmd == "check":                    # never asks anything: save.bat runs it quietly
        server = servers.pick(BUILTIN, name, interactive=False)
        if not server:
            return 1
        host = servers.reachable(server)
        say("srv", f"{server['name']} reachable at {host}" if host
            else f"{server['name']} not reachable (tried {', '.join(server['hosts'])})")
        return 0 if host else 1
    if cmd in ("deploy", "status"):
        return deploy(name, choose, dry=cmd == "status")
    if cmd == "pull-data":
        return pull_data(name, choose)
    if cmd == "servers":
        return servers.manage(BUILTIN)
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)

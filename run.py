"""Starts Tunebox: fetches what it needs the first time (mpv on Windows, Node), then serves it and
opens it in the browser. start.bat (Windows) and install.sh (Linux) call this; so does the service.

  python run.py                 http://localhost:8888/ here, and phones and computers on the network can use it too
  python run.py --local         this computer only (nobody else on the network can reach it)
  python run.py --port 9000     another port
  python run.py --no-browser    don't open the browser (a server)
  python run.py --setup-only    fetch mpv and Node, then stop
  python run.py --reset-admin   forget the admin password (run it on the server; add --port or --data as it runs)

Tunebox plays through the speakers of the computer it runs on; every browser is a remote for it."""
import argparse
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def addresses(port: int) -> list[str]:
    """Where phones and other computers reach it: its LAN addresses (the default route's first), then its name."""
    from tunebox import network
    return [f"http://{ip}:{port}/" for ip in network.addresses()] + [f"http://{socket.gethostname().lower()}:{port}/"]


def open_when_up(url: str):
    """Opens the browser once the server answers (the first start can take a few seconds)."""
    def wait():
        for _ in range(120):
            try:
                urllib.request.urlopen(url + "api/state", timeout=2)
                webbrowser.open(url)
                return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=wait, daemon=True).start()


def reset_admin(port: int):
    """The admin password is forgotten; whoever opens the admin panel next sets a new one. A running
    Tunebox is told (the token in cli.token proves this is the server), so the music plays on; when
    none runs, keys.json is changed here."""
    import json
    from tunebox.config import KEYS_FILE, TOKEN_FILE
    from tunebox.files import read_json, write_json
    base = os.environ.get("TUNEBOX_URL") or f"http://127.0.0.1:{port}/"
    try:
        token = TOKEN_FILE.read_text().strip()
        req = urllib.request.Request(base.rstrip("/") + "/api/admin/reset", method="POST", headers={"X-Tunebox-Local": token})
        json.load(urllib.request.urlopen(req, timeout=5))
        print("[tunebox] the admin password is forgotten; Tunebox keeps running")
        return
    except urllib.error.HTTPError as exc:
        print(f"[tunebox] Tunebox at {base} refused ({exc.code}): it is not the one that keeps its files here")
        sys.exit(1)
    except OSError:
        pass                                  # nothing running there (or no token yet): change the file
    keys = read_json(KEYS_FILE, {})
    if not keys.get("admin"):
        print("[tunebox] no admin password is set")
        return
    owner = KEYS_FILE.stat()
    keys["admin"] = None
    write_json(KEYS_FILE, keys)
    if hasattr(os, "chown"):                  # run as root: the file stays the service user's
        try:
            os.chown(KEYS_FILE, owner.st_uid, owner.st_gid)
        except OSError:
            pass
    print("[tunebox] the admin password is forgotten")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("TUNEBOX_PORT", 8888)))
    ap.add_argument("--local", action="store_true", help="this computer only: nobody else on the network can reach it")
    ap.add_argument("--lan", action="store_true", help=argparse.SUPPRESS)   # the old way to ask for what is now the default
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--data", type=Path, help="keep Tunebox's files here (default: this folder)")
    ap.add_argument("--setup-only", action="store_true", help="fetch mpv and Node, then stop")
    ap.add_argument("--reset-admin", action="store_true", help="forget the admin password, then stop")
    args = ap.parse_args()
    if args.data:
        os.environ["TUNEBOX_DATA"] = str(args.data.resolve())
        args.data.mkdir(parents=True, exist_ok=True)
    if args.reset_admin:
        reset_admin(args.port)
        return

    from tunebox import tools
    ready = tools.ensure()
    if args.setup_only:
        sys.exit(0 if ready else 1)
    if not ready:
        tools.say("can't play without mpv; see above")
        sys.exit(1)
    tools.end_children_with_us()               # Windows: closing this window also stops mpv

    import uvicorn
    host = "127.0.0.1" if args.local else "0.0.0.0"
    local = f"http://localhost:{args.port}/"
    tools.say(f"Tunebox on {local}")
    if not args.local:
        tools.say("phones and other computers open it at:" + "".join(f"\n           {a}" for a in addresses(args.port)))
    tools.say("Ctrl+C stops it")
    if not args.no_browser:
        open_when_up(local)
    os.chdir(HERE)
    # loop="asyncio" is the Proactor loop on Windows, which mpv's control pipe needs
    uvicorn.run("app:app", host=host, port=args.port, log_level="warning", access_log=False, loop="asyncio")


if __name__ == "__main__":
    main()

"""Starts Tunebox: fetches what it needs the first time (mpv on Windows, Node), then serves it and
opens it in the browser. start.bat (Windows) and install.sh (Linux) call this; so does the service.

  python run.py                 this computer only: http://localhost:8888/
  python run.py --lan           phones and other computers on the network can use it too
  python run.py --port 9000     another port
  python run.py --no-browser    don't open the browser (a server)
  python run.py --setup-only    fetch mpv and Node, then stop

Tunebox plays through the speakers of the computer it runs on; every browser is a remote for it."""
import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def addresses(port: int) -> list[str]:
    """Where other devices can reach it: this machine's name and its LAN addresses."""
    out = [f"http://{socket.gethostname().lower()}:{port}/"]
    try:
        for ip in {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}:
            if not ip.startswith("127."):
                out.append(f"http://{ip}:{port}/")
    except OSError:
        pass
    return out


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("TUNEBOX_PORT", 8888)))
    ap.add_argument("--lan", action="store_true", help="listen on every network interface, not only this computer")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--data", type=Path, help="keep Tunebox's files here (default: this folder)")
    ap.add_argument("--setup-only", action="store_true", help="fetch mpv and Node, then stop")
    args = ap.parse_args()
    if args.data:
        os.environ["TUNEBOX_DATA"] = str(args.data.resolve())
        args.data.mkdir(parents=True, exist_ok=True)

    from tunebox import tools
    ready = tools.ensure()
    if args.setup_only:
        sys.exit(0 if ready else 1)
    if not ready:
        tools.say("can't play without mpv; see above")
        sys.exit(1)
    tools.end_children_with_us()               # Windows: closing this window also stops mpv

    import uvicorn
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    local = f"http://localhost:{args.port}/"
    tools.say(f"Tunebox on {local}" + ("".join(f"\n           {a}" for a in addresses(args.port)) if args.lan else ""))
    tools.say("Ctrl+C stops it")
    if not args.no_browser:
        open_when_up(local)
    os.chdir(HERE)
    # loop="asyncio" is the Proactor loop on Windows, which mpv's control pipe needs
    uvicorn.run("app:app", host=host, port=args.port, log_level="warning", access_log=False, loop="asyncio")


if __name__ == "__main__":
    main()

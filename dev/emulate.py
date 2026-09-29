"""Runs Tunebox on this PC the way ele serves it: under /music/, as Caddy puts it there.

  python dev/emulate.py [--port 8000] [--lan] [--silent] [--speed 1] [--no-browser] [--data DIR]

It plays through this PC's speakers with the real mpv (fetched into tools/ on first use, as
start.bat does), or silently with --silent (dev/fakes.py: a fake mpv and instant fake streams).
Local data lives in dev/data (gitignored); `save.bat pull-data` copies ele's real data there.
For a plain local Tunebox without the /music/ prefix, use start.bat instead.
"""
import argparse
import asyncio
import importlib.util
import os
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "dev"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="listen on every interface, so phones on the LAN can open it")
    ap.add_argument("--silent", action="store_true", help="play silently (fake mpv) instead of through the speakers")
    ap.add_argument("--speed", type=float, default=1.0, help="with --silent: how fast fake songs play")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--data", type=Path, help="Tunebox's data folder, instead of dev/data (for tests)")
    args = ap.parse_args()
    data = args.data.resolve() if args.data else DEV / "data"
    (data / "run").mkdir(parents=True, exist_ok=True)
    os.environ.update(TUNEBOX_DATA=str(data), TUNEBOX_RUN=str(data / "run"))

    sys.path.insert(0, str(ROOT))
    from tunebox import tools
    tools.end_children_with_us()               # Windows: closing this window also stops mpv
    if args.silent:
        sys.path.insert(0, str(DEV))
        import fakes
        fakes.install_tunebox(args.speed)
        sound = "silently (fake player)"
    else:
        if not tools.ensure():
            sys.exit("can't play without mpv; see above (or use --silent)")
        sound = "through this PC's speakers"
    spec = importlib.util.spec_from_file_location("tunebox_app", ROOT / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)

    from starlette.applications import Starlette
    from starlette.responses import RedirectResponse
    from starlette.routing import Mount, Route

    async def to_music(request):
        return RedirectResponse("/music/")
    site = Starlette(lifespan=lambda _: app.app.router.lifespan_context(app.app),   # mounted apps get no startup of their own
                     routes=[Route("/", to_music), Route("/music", to_music), Mount("/music", app=app.app)])

    url = f"http://localhost:{args.port}/music/"
    print(f"\n  Tunebox emulator: {url}\n  plays {sound}")
    if args.lan:
        print(f"  also on the LAN: http://<this PC's address>:{args.port}/music/")
    print(f"  data: {data}\n  Ctrl+C stops it\n")

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(site, host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, log_level="warning"))
    if not args.no_browser:
        def opener():
            import time
            while not server.started:
                time.sleep(0.2)
            webbrowser.open(url)
        threading.Thread(target=opener, daemon=True).start()
    asyncio.run(server.serve())                # Windows: the Proactor loop, which mpv's control pipe needs


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

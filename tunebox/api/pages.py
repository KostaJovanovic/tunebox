"""The pages: / (the player), /wall and /patch (the patch notes), plus their CSS and JS under /web/, and the app manifest with
the house's name in it.

Everything is sent with Cache-Control: no-cache, so a phone checks for a newer file on every load
(a quick 304 when nothing changed) and picks up a deploy straight away."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import admin, house
from ..config import WEB_DIR

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-cache"}
PAGES = {name: WEB_DIR / name / "index.html" for name in ("bauhaus", "wall")}


def page(name: str, **headers) -> FileResponse:
    return FileResponse(PAGES[name], headers={**NO_CACHE, **headers})


@router.get("/")
def index():
    return page("bauhaus")


@router.get("/bauhaus")
@router.get("/classic")
def old_address():
    """Bookmarks from when there were two interfaces (Classic is gone)."""
    return RedirectResponse("./", 301)


@router.get("/sw.js")
def service_worker():
    """At the root, so it may look after every page (a worker only covers its own folder and below)."""
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers=NO_CACHE)


@router.get("/wall")
def wall(request: Request):
    """The wall screen: a tablet or TV showing what plays."""
    if not house.on("wall") and not admin.is_admin(request, touch=False):
        return RedirectResponse("./", 302, headers=NO_CACHE)
    return page("wall")


@router.get("/patch")
def patch_notes():
    """What changed, version by version (made by dev/patch.py from patch-notes.md)."""
    return FileResponse(WEB_DIR / "patch.html", headers=NO_CACHE)


@router.get("/web/manifest.webmanifest")
def manifest():
    """The installed app carries the house's name (this route comes before the /web files)."""
    m = json.loads((WEB_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
    m["name"] = m["short_name"] = house.house["name"]
    if not house.on("wall"):
        m.pop("shortcuts", None)
    return Response(json.dumps(m), media_type="application/manifest+json", headers=NO_CACHE)


class NoCacheFiles(StaticFiles):
    """StaticFiles that tells browsers to re-check each file (they still get 304s when nothing changed)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response

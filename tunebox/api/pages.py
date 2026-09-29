"""The pages: / (the device's chosen look), /bauhaus, /classic and /wall, plus their CSS and JS under /web/.

Everything is sent with Cache-Control: no-cache, so a phone checks for a newer file on every load
(a quick 304 when nothing changed) and picks up a deploy straight away."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import APP_DIR

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-cache"}
PAGES = {"bauhaus": APP_DIR / "index.html", "classic": APP_DIR / "classic.html", "wall": APP_DIR / "wall.html"}


def page(name: str, **headers) -> FileResponse:
    return FileResponse(PAGES[name], headers={**NO_CACHE, **headers})


@router.get("/")
def index(request: Request):
    classic = request.cookies.get("tb_ui") == "classic"
    return page("classic" if classic else "bauhaus", Vary="Cookie")


@router.get("/bauhaus")
def bauhaus():
    return page("bauhaus")


@router.get("/classic")
def classic():
    return page("classic")


@router.get("/wall")
def wall():
    """The wall screen: a tablet or TV showing what plays."""
    return page("wall")


class NoCacheFiles(StaticFiles):
    """StaticFiles that tells browsers to re-check each file (they still get 304s when nothing changed)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response

"""The pages: / (the player) and /wall, plus their CSS and JS under /web/.

Everything is sent with Cache-Control: no-cache, so a phone checks for a newer file on every load
(a quick 304 when nothing changed) and picks up a deploy straight away."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

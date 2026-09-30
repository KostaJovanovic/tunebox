"""Lyrics for the drawer, the canvas and the wall screen."""
from fastapi import APIRouter

from ..lyrics import lyrics_for
from ..web import feature

router = APIRouter(dependencies=[feature("lyrics")])


@router.get("/api/lyrics")
async def lyrics(videoId: str, title: str = "", artist: str = "", album: str = "", duration: str = ""):
    return await lyrics_for(videoId, title, artist, album, duration)

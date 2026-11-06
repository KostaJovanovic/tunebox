"""Builds the demo: a static site with the whole interface, for Cloudflare Pages (or any static host).

  python dev/demo/build.py          -> dev/demo/dist/

dist/ is committed: Cloudflare Pages serves it from the repo as it is (output directory
dev/demo/dist, no build command). Run this and commit to update the demo.

web/ is copied as it is; the pages get demo/boot.js first, and sw.js is the demo's server
(dev/demo/sw.js), which answers api/ from dev/demo/music.json (dev/demo/capture.py records it).
/wall and /patch work because Pages serves wall.html and patch.html at those addresses.
Standard library only.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
BOOT = '<script src="demo/boot.js"></script>\n'


def page(src: Path, dest: Path):
    html = src.read_text(encoding="utf-8")
    at = html.index("<head>") + len("<head>\n")
    dest.write_text(html[:at] + BOOT + html[at:], encoding="utf-8")


def main():
    if not (HERE / "music.json").exists():
        raise SystemExit("No dev/demo/music.json yet: run dev/demo/capture.py first")
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(ROOT / "web", DIST / "web")
    page(ROOT / "web/bauhaus/index.html", DIST / "index.html")
    page(ROOT / "web/wall/index.html", DIST / "wall.html")
    shutil.copy(ROOT / "web/patch.html", DIST / "patch.html")
    shutil.copy(HERE / "sw.js", DIST / "sw.js")
    (DIST / "demo").mkdir()
    for f in ("boot.js", "music.json"):
        shutil.copy(HERE / f, DIST / "demo" / f)
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"built {DIST} ({size // 1024} KB)")


if __name__ == "__main__":
    main()

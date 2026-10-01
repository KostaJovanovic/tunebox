"""The version and the patch notes page.

  python dev/patch.py           build web/patch.html (and web/patch.json, for the Ele home page) from patch-notes.md
  python dev/patch.py bump      the next version into web/shared/version.js, then build
  python dev/patch.py unbump    take that back (a commit that failed), then build

save.bat and save.sh run bump just before they commit, and unbump when the commit fails. The count is
read from version.js and raised by one, never taken from git: a shallow clone counts wrong. The rules for
writing the notes are at the top of patch-notes.md. Standard library only."""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "patch-notes.md"
PAGE = ROOT / "web" / "patch.html"
FEED = ROOT / "web" / "patch.json"           # the same notes for the Ele home page's /patch/ (homeapps)
VERSION_JS = ROOT / "web" / "shared" / "version.js"
TAGS = {"new": "New", "fix": "Fix", "faster": "Faster"}


def read_version() -> tuple[int, list[int]]:
    text = VERSION_JS.read_text(encoding="utf-8")
    count = re.search(r"export const COMMIT_COUNT = (\d+);", text)
    crowned = re.search(r"export const RELEASE_COMMITS = \[([\d,\s]*)\];", text)
    if not count or not crowned:
        sys.exit(f"[err]  {VERSION_JS.relative_to(ROOT)} has no COMMIT_COUNT or RELEASE_COMMITS line - refusing to guess")
    return int(count.group(1)), [int(n) for n in re.findall(r"\d+", crowned.group(1))]


def label(n: int, crowned: list[int]) -> str:
    """0.NN before the first crowned commit; that one is 1.0, the next 1.01, and so on."""
    major, base = 0, 0
    for r in sorted(crowned):
        if n >= r:
            major, base = major + 1, r
    if major == 0:
        return f"0.{n:02d}"
    return f"{major}.0" if n == base else f"{major}.{n - base:02d}"


def stamp(step: int):
    n, crowned = read_version()
    n += step
    if n < 1:
        sys.exit("[err]  the commit count would fall below 1")
    text = VERSION_JS.read_text(encoding="utf-8")
    text = re.sub(r"export const COMMIT_COUNT = \d+;", f"export const COMMIT_COUNT = {n};", text)
    text = re.sub(r'export const VERSION = "[^"]*";', f'export const VERSION = "{label(n, crowned)}";', text)
    VERSION_JS.write_text(text, encoding="utf-8", newline="\n")
    print(f"[ver]  {label(n, crowned)} (commit {n})")


# ---------- patch-notes.md ----------

def parse(text: str) -> list[dict]:
    """The releases under "## Releases": [{name, version, date, items: [("h", text) | ("li", text)]}]."""
    lines = text.splitlines()
    try:
        start = lines.index("## Releases") + 1
    except ValueError:
        sys.exit("[err]  patch-notes.md has no '## Releases' line")
    releases, last = [], None
    for no, line in enumerate(lines[start:], start + 1):
        if not line.strip():
            last = None
            continue
        if line.startswith("## "):
            releases.append({"name": line[3:].strip(), "version": "", "date": "", "items": []})
            last = None
            continue
        if not releases:
            sys.exit(f"[err]  patch-notes.md:{no}: text before the first release")
        rel = releases[-1]
        if line.startswith("### "):
            rel["items"].append(["h", line[4:].strip()])
        elif m := re.match(r"(version|date):\s*(.+)$", line):
            rel[m.group(1)] = m.group(2).strip()
        elif line.startswith("- "):
            last = ["li", line[2:].strip()]
            rel["items"].append(last)
        elif line.startswith("  ") and last:
            last[1] += " " + line.strip()
        else:
            sys.exit(f"[err]  patch-notes.md:{no}: not a heading, a version, a date or a bullet: {line.strip()[:60]}")
    for r in releases:
        if not r["version"] or not r["date"]:
            sys.exit(f"[err]  patch-notes.md: '{r['name']}' needs both a version: and a date: line")
    return releases


def inline(s: str) -> str:
    """**bold**, _accent_ and `code`; everything else escaped. Code is set aside first, so a bold run
    may hold a `label` and a label may hold ** or _."""
    codes = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1), quote=False)}</code>")
        return f"\x00{len(codes) - 1}\x00"
    s = html.escape(re.sub(r"`([^`]+)`", keep, s), quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w/])_([^_]+)_(?![\w/])", r"<em>\1</em>", s)
    s = s.replace("'", "&rsquo;")
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def anchor(version: str) -> str:
    return "v" + version.split("-")[-1].strip().replace(".", "-")


def release_json(r: dict) -> dict:
    """A release as the Ele home page's /patch/ page reads it (the same shape homeapps' dev/patch.py
    writes): items are {"h": html} for a subhead, or {"tag": "new" | "fix" | "faster" | "lead" | "plain",
    "html": html} for a bullet."""
    items, first = [], True
    for kind, text in r["items"]:
        if kind == "h":
            items.append({"h": inline(text)})
            continue
        m = re.match(r"\[(new|fix|faster)\]\s+", text)
        items.append({"tag": m.group(1), "html": inline(text[m.end():])} if m else
                     {"tag": "lead" if first else "plain", "html": inline(text)})
        first = False
    return {"name": r["name"], "version": r["version"], "date": r["date"], "items": items}


def release_html(r: dict) -> str:
    out = [f'<section class="rel" id="{anchor(r["version"])}">',
           f'  <header><h2>{html.escape(r["name"])}</h2>'
           f'<p class="meta"><span>{html.escape(r["version"])}</span><span>{html.escape(r["date"])}</span></p></header>']
    open_list, first = False, True
    for kind, text in r["items"]:
        if kind == "h":
            if open_list:
                out.append("  </ul>")
                open_list = False
            out.append(f"  <h3><i></i>{inline(text)}</h3>")
            continue
        if not open_list:
            out.append("  <ul>")
            open_list = True
        m = re.match(r"\[(new|fix|faster)\]\s+", text)
        if m:
            out.append(f'    <li><span class="tag is-{m.group(1)}">{TAGS[m.group(1)]}</span>{inline(text[m.end():])}</li>')
        else:
            out.append(f'    <li class="{"lead" if first else "plain"}">{inline(text)}</li>')
        first = False
    if open_list:
        out.append("  </ul>")
    out.append("</section>")
    return "\n".join(out)


PAGE_HEAD = """<!doctype html>
<!-- GENERATED by dev/patch.py from patch-notes.md - do not edit; write there and run python dev/patch.py.
     All addresses are relative (web/..., ./): Tunebox can live under a prefix like /music/. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" id="themeColor" content="#111111">
<title>Patch notes - Tunebox</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect width='24' height='24' fill='%23111'/><circle cx='9' cy='12' r='6' fill='%23E63B2E'/><path d='M14 6l8 12h-8z' fill='%23F2C230'/></svg>">
<script src="web/shared/look.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Jost:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="web/bauhaus/css/base.css">
<style>
  body { user-select: text; -webkit-user-select: text; font-size: 15px; line-height: 1.55; }
  .pn { max-width: 760px; margin: 0 auto; padding: 24px 16px 64px; padding-top: max(24px, env(safe-area-inset-top)); }
  .back { position: sticky; top: 0; z-index: 1; display: flex; padding: 10px 0; background: var(--bg); }
  .back a { display: inline-flex; align-items: center; gap: 8px; min-height: var(--hit); padding: 0 14px;
    border: 1px solid var(--line-2); color: var(--text); text-decoration: none; font: 600 13px var(--ui); }
  .back a:hover { border-color: var(--text); }
  .mark { display: inline-flex; gap: 3px; align-items: center; }
  .mark i { width: 10px; height: 10px; display: block; }
  .mark .c { background: var(--red); border-radius: 50%; }
  .mark .t { width: 0; height: 0; border: 5px solid transparent; border-bottom: 10px solid var(--yellow); border-top: 0; }
  .mark .s { background: var(--blue); }
  .top h1 { font: 700 clamp(40px, 9vw, 64px)/1 var(--display); letter-spacing: -.01em; margin: 28px 0 10px; }
  .top p { margin: 0; color: var(--muted); }
  .top b { color: var(--text); }
  .rel { border-top: 2px solid var(--text); margin-top: 48px; padding-top: 18px; }
  .rel header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 16px; }
  .rel h2 { margin: 0; font: 700 28px/1.15 var(--display); }
  .meta { margin: 0; display: flex; gap: 14px; color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
  .meta span:first-child { color: var(--text); font-weight: 600; }
  .rel h3 { display: flex; align-items: center; gap: 10px; margin: 26px 0 4px; font: 600 12px var(--display);
    letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  .rel h3 i { width: 10px; height: 10px; background: var(--red); flex: none; }
  .rel h3:nth-of-type(3n+2) i { background: var(--yellow); }
  .rel h3:nth-of-type(3n) i { background: var(--blue); }
  .rel ul { list-style: none; margin: 0; padding: 0; }
  .rel li { padding: 9px 0; border-bottom: 1px solid var(--line); color: var(--muted); }
  .rel li:last-child { border-bottom: 0; }
  .rel li strong { color: var(--text); font-weight: 600; }
  .rel li.lead { color: var(--text); font-size: 17px; padding: 14px 0; }
  .rel li.lead strong { font-weight: 700; }
  .rel em { font-style: normal; color: var(--red); }
  .rel code { font: 500 .9em ui-monospace, "Cascadia Mono", Consolas, monospace; color: var(--text);
    background: var(--s2); padding: 1px 5px; }
  .tag { display: inline-block; margin-right: 8px; padding: 1px 6px; border: 1px solid var(--line-2);
    font: 600 10px/1.5 var(--display); letter-spacing: .1em; text-transform: uppercase; vertical-align: 2px; color: var(--muted); }
  .tag.is-new { border-color: var(--red); color: var(--red); }
  .tag.is-faster { border-color: var(--yellow); color: var(--text); }
  .foot { margin-top: 48px; color: var(--faint); font-size: 13px; }
</style>
</head>
<body>
<main class="pn">
<nav class="back"><a href="./"><span class="mark"><i class="c"></i><i class="t"></i><i class="s"></i></span>Back to the player</a></nav>
"""


def build(releases: list[dict]):
    n, crowned = read_version()
    version = label(n, crowned)
    newest = releases[0]["version"].split("-")[-1].strip() if releases else ""
    if newest != version:
        print(f"[warn] patch-notes.md ends at {newest or 'nothing'}, but this is version {version}: "
              f"add the new commits to the top day, or start a new one", file=sys.stderr)
    days = len(releases)
    body = [PAGE_HEAD,
            '<header class="top"><h1>Patch notes</h1>',
            f'<p>Version <b>{version}</b> &middot; {n} updates over {days} day{"" if days == 1 else "s"}, newest first.</p></header>',
            *(release_html(r) for r in releases),
            f'<p class="foot">Tunebox {version}</p>',
            "</main>\n</body>\n</html>\n"]
    PAGE.write_text("\n".join(body), encoding="utf-8", newline="\n")
    feed = {"app": "Tunebox", "version": version, "page": "patch", "releases": [release_json(r) for r in releases]}
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"[gen]  {PAGE.relative_to(ROOT).as_posix()} and patch.json ({days} days, version {version})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd not in ("build", "bump", "unbump"):
        sys.exit(__doc__)
    notes = parse(SOURCE.read_text(encoding="utf-8"))   # first: notes that don't parse stamp nothing
    if cmd == "bump":
        stamp(+1)
    elif cmd == "unbump":
        stamp(-1)
    build(notes)

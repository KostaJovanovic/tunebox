"""Tunebox from a terminal. Everything the page does, as commands:

  tunebox status                     what is playing, and what is up next
  tunebox add daft punk around       finds the song and adds it to the queue (--next, --now, --replace, --pick 3)
  tunebox add https://youtu.be/...   a song, album or playlist link
  tunebox next | prev | toggle | vol +5 | seek 1:30 | sleep 30 | undo
  tunebox queue                      up next; queue rm 2, queue mv 4 1, queue top 3, queue jump 2, queue clear
  tunebox search QUERY, album ID, artist ID, playlist ID, home, explore, lyrics --follow, stats
  tunebox lists, like, history, people, groups, local upload FILE..., backup, restore FILE
  tunebox admin login, features off lyrics, house set name Studio, block add --artist NAME
  tunebox watch                      a live view with keys: space, n, p, + and -, q
  tunebox COMMAND -h                 everything a command takes

It talks to a running Tunebox over HTTP, like a browser does, and keeps its cookies (who you are, the
admin session) per server in ~/.config/tunebox/cli.json (%APPDATA%\\tunebox\\cli.json on Windows).

Which Tunebox: --server URL or a saved name (tunebox server add NAME URL), else $TUNEBOX_URL, else the
saved default, else http://127.0.0.1:$TUNEBOX_PORT/ (8888).

On the server itself the file cli.token makes this the admin with no password (tunebox admin reset
forgets a lost one). Anywhere else, what needs the admin asks for the password once; a script can
give it in $TUNEBOX_ADMIN_PASSWORD.

--json prints the server's answer as it is. --no-input never asks anything (for scripts). --yes answers
the "are you sure" questions. Exit codes: 0 done, 1 refused, 2 wrong usage, 3 no Tunebox there.

This file uses only Python's standard library and nothing else of Tunebox, so any Python 3.11+ runs it."""
import argparse
import getpass
import http.cookies
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINK = re.compile(r"^(https?://|www\.)\S+$|^([\w-]+\.)*(youtube\.com|youtu\.be)(/\S*)?$", re.I)
VIDEO_ID = re.compile(r"(?=.*[A-Z0-9_-])[A-Za-z0-9_-]{11}")     # eleven characters, not all lower case letters
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WALL = ("lyrics", "queue", "who", "clock", "controls")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # Tunebox is on this network: never through a proxy


class Refused(Exception):
    """The server said no: its status and its message."""
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class Unreachable(Exception):
    pass


class Usage(Exception):
    pass


# ---------- what is kept between runs: servers and their cookies ----------
def config_file() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / "tunebox" / "cli.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tunebox" / "cli.json"


def load_config() -> dict:
    try:
        c = json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    return {"default": c.get("default"), "servers": c.get("servers") or {}, "jars": c.get("jars") or {}}


def save_config(c: dict):
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # it holds the admin session: yours alone
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(c, out, indent=1)
    os.replace(tmp, f)


def clean_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/") + "/"              # paths are relative to it, so Tunebox under /music/ works


def server_url(config: dict, named: str | None) -> str:
    if named:
        return clean_url(config["servers"].get(named) or named)
    if os.environ.get("TUNEBOX_URL"):
        return clean_url(os.environ["TUNEBOX_URL"])
    if config["default"] in config["servers"]:
        return config["servers"][config["default"]]
    return f"http://127.0.0.1:{os.environ.get('TUNEBOX_PORT') or 8888}/"


def local_token(base: str) -> str:
    """The token a Tunebox on this machine wrote at its start (cli.token, in its data folder). Only a
    Tunebox on this machine is ever sent it."""
    if urllib.parse.urlsplit(base).hostname not in ("127.0.0.1", "localhost", "::1"):
        return ""
    folders = [os.environ.get("TUNEBOX_DATA"), HERE.parent]
    for d in filter(None, folders):
        try:
            return (Path(d) / "cli.token").read_text().strip()
        except OSError:
            pass
    return ""


# ---------- talking to the server ----------
class Client:
    def __init__(self, base: str, config: dict, ask: bool):
        self.base, self.config, self.ask = base, config, ask
        self.jar = config["jars"].setdefault(base, {})
        self.token = local_token(base)
        self._people = None

    def once(self, method, path, body, params, data, ctype, timeout, raw):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json"}
        if self.jar:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        if self.token:
            headers["X-Tunebox-Local"] = self.token
        payload = None
        if body is not None:
            payload, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif data is not None:
            payload = data() if callable(data) else data
            headers["Content-Type"] = ctype or "application/octet-stream"
            if hasattr(payload, "size"):
                headers["Content-Length"] = str(payload.size)
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            r = OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            self.cookies(exc.headers)
            text = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(text)["detail"]
            except (ValueError, KeyError, TypeError):      # a proxy's error page, or some other program's
                raise Unreachable(f"{self.base} answered {exc.code}, but not as Tunebox does. Is that its address, and is it running?")
            raise Refused(exc.code, str(detail))
        except (urllib.error.URLError, OSError) as exc:
            raise Unreachable(f"no Tunebox answers at {self.base} ({getattr(exc, 'reason', exc)})")
        finally:
            if hasattr(payload, "close"):
                payload.close()
        self.cookies(r.headers)
        if raw:
            return r                           # the caller reads it (a download)
        text = r.read().decode("utf-8", "replace")
        try:
            return json.loads(text)
        except ValueError:
            raise Unreachable(f"{self.base} answered, but not as Tunebox does. Is that its address?")

    def cookies(self, headers):
        changed = False
        for line in headers.get_all("Set-Cookie") or []:
            for k, m in http.cookies.SimpleCookie(line).items():
                if m.value and m["max-age"] != "0":
                    self.jar[k] = m.value
                else:
                    self.jar.pop(k, None)
                changed = True
        if changed:
            save_config(self.config)

    def call(self, method, path, body=None, *, params=None, data=None, ctype=None, timeout=30, raw=False, again=True):
        """One request. A 401 "pick" asks who you are and a 403 "admin" for the admin password, then it
        is tried once more."""
        try:
            return self.once(method, path, body, params, data, ctype, timeout, raw)
        except Refused as exc:
            if exc.status == 401 and exc.detail == "pick":
                if not (again and self.ask and pick_name(self)):
                    raise Refused(401, "Say who you are first: tunebox iam NAME")
            elif exc.status == 403 and exc.detail == "admin":
                if not (again and (self.ask or os.environ.get("TUNEBOX_ADMIN_PASSWORD")) and unlock(self)):
                    raise Refused(403, "That needs the admin: tunebox admin login")
            else:
                raise
        return self.call(method, path, body, params=params, data=data, ctype=ctype, timeout=timeout, raw=raw, again=False)

    def get(self, path, **params):
        return self.call("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    def post(self, path, body=None, method="POST"):
        return self.call(method, path, {} if body is None and method == "POST" else body)

    # ----- who is who
    def people(self) -> list[dict]:
        if self._people is None:
            self._people = self.get("api/people")
        return self._people

    def person(self, name: str) -> dict:
        return match(self.people(), name, "name", "No one is called")

    def name_of(self, pid: str) -> str:
        return next((p["name"] for p in self.people() if p["id"] == pid), "")

    def me(self) -> dict | None:
        return next((p for p in self.people() if p["id"] == self.jar.get("tb_who")), None)

    def is_admin(self) -> bool:
        return bool(self.token or self.jar.get("tb_admin")) and self.get("api/admin")["admin"]

    def set_who(self, pid: str | None):
        if pid:
            self.jar["tb_who"] = pid
        else:
            self.jar.pop("tb_who", None)
        save_config(self.config)


def match(items: list[dict], wanted: str, key: str, none: str) -> dict:
    """The one item called that: by id, by its exact name, else by the only name that starts with it."""
    w = wanted.strip().lower()
    for test in (lambda x: str(x.get("id", "")).lower() == w, lambda x: str(x[key]).lower() == w,
                 lambda x: str(x[key]).lower().startswith(w), lambda x: w in str(x[key]).lower()):
        hits = [x for x in items if test(x)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise Refused(409, f'"{wanted}" could be ' + ", ".join(str(x[key]) for x in hits[:6]) + ": say which")
    raise Refused(404, f'{none} "{wanted}"')


# ---------- asking (only on a terminal, never with --no-input) ----------
def prompt(text: str) -> str:
    try:
        return input(text).strip()
    except EOFError:
        return ""


def sure(a, question: str):
    """For what can't be undone: --yes, or a "y" typed here."""
    if a.yes:
        return
    if not a.ask:
        raise Usage(f"{question} Add --yes to go ahead.")
    if prompt(f"{question} (y/n): ").lower() != "y":
        raise Refused(1, "Nothing was changed")


def use_person(c: Client, p: dict):
    if p.get("locked") and not p.get("mine"):
        if not c.ask:
            raise Refused(403, f"{p['name']} has a pass phrase: run tunebox iam {p['name']} on a terminal")
        c.call("POST", f"api/people/{p['id']}/unlock", {"phrase": getpass.getpass(f"{p['name']}'s pass phrase: ")})
    c.set_who(p["id"])


def new_person(c: Client, name: str, groups: list[str] | None = None, **more) -> dict:
    house = c.get("api/house")
    g = house["groups"]
    if groups is None and c.ask and "groups" not in house["off"] and "people" not in house["off"]:
        have = ", ".join(s["name"] for s in c.get("api/seminars"))
        typed = prompt(f"{g['one']}{' (' + have + ')' if have else ''}: ")
        groups = [x.strip() for x in typed.split(",") if x.strip()]
    body = {"name": name, **({"seminars": groups} if groups else {}), **{k: v for k, v in more.items() if v is not None}}
    c._people = None
    return c.call("POST", "api/people", body)


def pick_name(c: Client) -> bool:
    people = c.people()
    print("Who's listening?", file=sys.stderr)
    for i, p in enumerate(people, 1):
        print(f"  {i}  {p['name']}{'  (pass phrase)' if p.get('locked') and not p.get('mine') else ''}", file=sys.stderr)
    typed = prompt("A number, or a new name: ")
    if not typed:
        return False
    if typed.isdigit() and 1 <= int(typed) <= len(people):
        use_person(c, people[int(typed) - 1])
    else:
        c.set_who(new_person(c, typed)["id"])
    return True


def unlock(c: Client) -> bool:
    st = c.get("api/admin")
    if st["admin"]:
        return True
    if st["lockedFor"]:
        raise Refused(403, f"Too many wrong passwords. Try again in {-(-st['lockedFor'] // 60)} min")
    given = os.environ.get("TUNEBOX_ADMIN_PASSWORD")
    if st["set"] or given:
        c.call("POST", "api/admin/login", {"password": given or getpass.getpass("Admin password: "), "create": not st["set"]}, again=False)
        return True
    print("Nobody has set an admin password yet. Choose one (at least 4 characters).", file=sys.stderr)
    pw = getpass.getpass("New admin password: ")
    if pw != getpass.getpass("Type it again: "):
        raise Refused(1, "That's not the same")
    c.call("POST", "api/admin/login", {"password": pw, "create": True}, again=False)
    return True


# ---------- saying things ----------
JSON = False


def show(data, text: str = ""):
    """The answer: the server's own JSON with --json, a sentence or a list otherwise."""
    if JSON:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    elif text:
        print(text)


def clock(s) -> str:
    s = max(0, int(s or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def seconds(text: str) -> float:
    try:
        n = 0.0
        for part in text.split(":"):
            n = n * 60 + float(part)
        return n
    except ValueError:
        raise Usage(f'"{text}" is not a time: 90, or 1:30')


def song(t: dict) -> str:
    return t["title"] + (f" - {t['artist']}" if t.get("artist") else "")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def size(b: float) -> str:
    return f"{b / 2**30:.1f} GB" if b >= 2**30 else f"{round(b / 2**20)} MB"


def when(t: float) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(t))


def rows(items, line) -> str:
    return "\n".join(f"{i:>3}  {line(x)}" for i, x in enumerate(items, 1))


def onoff(text: str) -> bool:
    if text.lower() in ("on", "yes", "true", "1", "open"):
        return True
    if text.lower() in ("off", "no", "false", "0", "closed", "admin"):
        return False
    raise Usage(f'"{text}": on or off')


# ---------- servers, and who you are ----------
def cmd_server(c, a):
    cfg = c.config
    if a.action == "ls":
        lines = [f"{'*' if n == cfg['default'] else ' '} {n}  {u}" for n, u in sorted(cfg["servers"].items())]
        return show(cfg["servers"], "\n".join(lines) or f"No saved servers. This one is {c.base}")
    if not a.name:
        raise Usage("which server? tunebox server ls")
    if a.action == "add":
        if not a.url:
            raise Usage("tunebox server add NAME URL")
        cfg["servers"][a.name] = clean_url(a.url)
        cfg["default"] = cfg["default"] or a.name
        text = f"Saved {a.name}: {cfg['servers'][a.name]}" + (" (the default)" if cfg["default"] == a.name else "")
    elif a.name not in cfg["servers"]:
        raise Refused(404, f'No saved server "{a.name}"')
    elif a.action == "use":
        cfg["default"], text = a.name, f"{a.name} is the default now"
    else:
        cfg["jars"].pop(cfg["servers"].pop(a.name), None)
        if cfg["default"] == a.name:
            cfg["default"] = None
        text = f"Forgot {a.name}"
    save_config(cfg)
    show(cfg["servers"], text)


def cmd_whoami(c, a):
    st, me, house = c.get("api/admin"), c.me(), c.get("api/house")
    who = me["name"] if me else "nobody yet (tunebox iam NAME)"
    how = "yes, by this machine's token" if c.token and st["admin"] else "yes" if st["admin"] else "no"
    show({"server": c.base, "house": house["name"], "who": me, "admin": st["admin"]},
         f"{house['name']} at {c.base}\nYou are {who}\nAdmin: {how}")


def cmd_iam(c, a):
    if a.none:
        c.set_who(None)
        return show({"who": None}, "You are nobody here now")
    if not a.name:
        raise Usage("tunebox iam NAME (or --none)")
    try:
        p = c.person(a.name)
    except Refused as exc:
        if exc.status != 404 or not a.new:
            raise Refused(exc.status, exc.detail + ("" if exc.status != 404 else f'. Add the name with: tunebox iam "{a.name}" --new'))
        p = new_person(c, a.name, a.group)
    use_person(c, p)
    show(p, f"You are {p['name']}")


# ---------- playing ----------
def state(c) -> dict:
    return c.get("api/state")


def cmd_status(c, a):
    s = state(c)
    t = s["current"]
    if not t:
        return show(s, "Nothing is playing")
    by = c.name_of(t.get("by", "")) if t.get("src") == "user" else "the radio"
    what = "Loading" if s["loading"] else "Paused" if s["paused"] else "Playing"
    lines = [f"{what}: {song(t)}  ({clock(s['position'])} / {clock(s['duration'])})" + (f", added by {by}" if by else "")]
    rest, n = len(s["queue"]) - 1, s["userCount"]
    lines.append(f"Volume {s['volume']}. " + (f"{plural(n, 'song')} up next" if n else "Nothing up next")
                 + (f", then {plural(rest - n, 'radio song')}" if rest > n else "") + ".")
    if s["sleep"]:
        lines.append("Stops after this song" if s["sleep"]["mode"] == "track" else f"Sleep timer: {clock(s['sleep']['left'])} left")
    if s["error"]:
        lines.append(f"Problem: {s['error']}")
    show(s, "\n".join(lines))


def control(c, action, **more):
    return c.call("POST", "api/control", {"action": action, **more})


def cmd_transport(c, a):
    s = state(c)
    if a.cmd in ("play", "pause"):
        if not s["current"]:
            raise Refused(1, "Nothing is playing. Add a song: tunebox add QUERY")
        if s["paused"] == (a.cmd == "pause"):
            return show({"ok": True}, "Already " + ("paused" if s["paused"] else "playing"))
        r = control(c, "toggle")
    else:
        r = control(c, a.cmd)
    said = {"play": "Playing", "pause": "Paused", "toggle": "Playing" if s["paused"] else "Paused", "next": "Skipped",
            "prev": "Back", "stop": "Stopped"}
    show(r, said[a.cmd])


def cmd_seek(c, a):
    s = state(c)
    if not s["current"]:
        raise Refused(1, "Nothing is playing")
    to = s["position"] + seconds(a.to[1:]) * (1 if a.to[0] == "+" else -1) if a.to[0] in "+-" else seconds(a.to)
    to = max(0, min(to, max(0, s["duration"] - 1)))
    show(control(c, "seek", value=to), f"At {clock(to)}")


def cmd_vol(c, a):
    s = state(c)
    if a.level is None:
        return show({"volume": s["volume"]}, f"Volume {s['volume']}")
    try:
        v = s["volume"] + int(a.level) if a.level[0] in "+-" else int(a.level)
    except ValueError:
        raise Usage("tunebox vol 60, vol +5 or vol -5")
    v = max(0, min(100, v))
    show(control(c, "volume", value=v), f"Volume {v}")


def cmd_sleep(c, a):
    if a.what is None:
        sl = state(c)["sleep"]
        return show(sl, "No sleep timer" if not sl else "Stops after this song" if sl["mode"] == "track" else f"{clock(sl['left'])} left")
    if a.what == "off":
        return show(c.call("POST", "api/sleep", {"minutes": 0}), "Sleep timer off")
    if a.what == "track":
        return show(c.call("POST", "api/sleep", {"track": True}), "Stops after this song")
    try:
        minutes = float(a.what)
    except ValueError:
        raise Usage("tunebox sleep 30 (minutes), sleep track, or sleep off")
    show(c.call("POST", "api/sleep", {"minutes": minutes}), f"Fades out and pauses in {minutes:g} min")


def cmd_undo(c, a):
    r = control(c, "undo")
    show(r, r["message"])


# ---------- finding and adding ----------
def find_tracks(c, what: str, pick: int) -> tuple[list[dict], str]:
    """The songs an argument means (a link, an id, or words to search for), and their name if they are
    an album or a playlist."""
    if what.startswith("local:"):
        hit = [t for t in c.get("api/local")["songs"] if t["videoId"] == what]
        if not hit:
            raise Refused(404, "No such local song")
        return hit, ""
    link = bool(LINK.match(what))
    if link or VIDEO_ID.fullmatch(what):
        try:
            r = c.get("api/resolve", url=what if link else "https://youtu.be/" + what)
        except Refused:
            if link:
                raise
            r = None                           # eleven characters that weren't an id: words after all
        if r and r["type"] == "song":
            return [r["track"]], ""
        if r:
            page = c.get(f"api/{r['type']}/{urllib.parse.quote(r['id'], safe='')}")
            if not page["tracks"]:
                raise Refused(404, "Nothing to play in there")
            return page["tracks"], page["title"]
    found = [x for x in c.get("api/search", q=what) if x.get("videoId")]
    if not found:
        raise Refused(404, f'Nothing found for "{what}"')
    if not 1 <= pick <= len(found):
        raise Usage(f"--pick: 1 to {len(found)}")
    return [found[pick - 1]], ""


def queue_up(c, tracks, mode, label="") -> tuple[dict, str]:
    r = c.call("POST", "api/play", {"tracks": tracks, "mode": mode, "label": label or None})
    what = f'{plural(len(tracks), "song")} from "{label}"' if label else song(tracks[0]) if len(tracks) == 1 else plural(len(tracks), "song")
    return r, f"{what}: {r['message']}"


def cmd_add(c, a):
    tracks, label = find_tracks(c, " ".join(a.what), a.pick)
    show(*queue_up(c, tracks, "next" if a.next else "now" if a.now else "replace" if a.replace else "add", label))


def cmd_radio(c, a):
    r = control(c, "refresh" if a.action == "refresh" else "clear_auto")
    show(r, r["message"] or "Nothing to do")


def cmd_queue(c, a):
    s = state(c)
    q, off = s["queue"], s["offset"]
    if a.action in ("rm", "mv", "top", "jump"):
        if a.n is None or not 1 <= a.n < len(q):
            raise Usage(f"which song? 1 to {len(q) - 1} (tunebox queue)" if len(q) > 1 else "Nothing is up next")
        t, at = q[a.n], off + a.n             # the song and its place as the server has them now
        if a.action == "mv":
            if a.to is None or not 1 <= a.to < len(q):
                raise Usage(f"tunebox queue mv {a.n} PLACE (1 to {len(q) - 1})")
            r, said = control(c, "move", value=at, videoId=t["videoId"], to=off + a.to), f"Moved {song(t)} to {a.to}"
        else:
            action, said = {"rm": ("remove", "Removed"), "top": ("promote", "Plays next:"), "jump": ("jump", "Playing")}[a.action]
            r, said = control(c, action, value=at, videoId=t["videoId"]), f"{said} {song(t)}"
        return show(r, said)
    if a.action in ("shuffle", "clear"):
        r = control(c, a.action)
        return show(r, r["message"] or "Nothing up next to " + a.action)
    if a.action == "history":
        h = c.get("api/queue/history")
        return show(h, "\n".join(f"{x['id']}  {when(x['at'])}  {x['label']}  ({plural(x['count'], 'song')})" for x in h) or "No earlier queues")
    if a.action == "restore":
        if not a.id:
            raise Usage("tunebox queue restore ID (tunebox queue history)")
        return show(control(c, "restore", id=a.id), "Restored")
    if not q:
        return show(s, "The queue is empty")
    lines = [f"now  {song(q[0])}  ({clock(s['position'])} / {clock(s['duration'])})"]
    for i, t in enumerate(q[1:], 1):
        if i == s["userCount"] + 1:
            lines.append("     radio" + (f" of {s['seed']['title']}" if s["seed"] else "") + ":")
        by = c.name_of(t.get("by", "")) if t.get("src") == "user" else ""
        lines.append(f"{i:>3}  {song(t)}  {t.get('duration', '')}" + (f"  ({by})" if by else ""))
    show(s, "\n".join(lines))


def cards(items) -> str:
    def line(x):
        if x.get("videoId"):
            return f"{song(x)}  {x.get('duration', '')}  [{x['videoId']}]"
        return f"{x['title']}" + (f" - {x['subtitle']}" if x.get("subtitle") else "") + f"  [{x['type']} {x['id']}]"
    return rows(items, line)


def cmd_search(c, a):
    found = c.get("api/search", q=" ".join(a.query), kind=a.kind)
    show(found, cards(found) or "Nothing found")


def cmd_page(c, a):
    page = c.get(f"api/{a.cmd}/{urllib.parse.quote(a.id, safe='')}")
    mode = "replace" if a.play else "next" if a.next else "add" if a.add else None
    if mode:
        if not page["tracks"]:
            raise Refused(404, "Nothing to play in there")
        return show(*queue_up(c, page["tracks"], mode, page["title"]))
    text = f"{page['title']}" + (f" - {page['subtitle']}" if page.get("subtitle") else "") + "\n" + cards(page["tracks"])
    if page.get("albums"):
        text += "\nAlbums:\n" + cards(page["albums"])
    show(page, text)


def cmd_home(c, a):
    shelves = c.get("api/forme") + c.get("api/home")
    show(shelves, "\n\n".join(f"{s['title']}\n{cards(s['items'])}" for s in shelves) or "Nothing here yet")


def cmd_explore(c, a):
    ex = c.get("api/explore")
    moods = "\n".join(f"{g['title']}: " + ", ".join(m["title"] for m in g["items"]) for g in ex["moods"])
    show(ex, "New releases\n" + cards(ex["releases"]) + "\n\n" + moods)


def cmd_resolve(c, a):
    r = c.get("api/resolve", url=a.url)
    show(r, f"song  {song(r['track'])}  [{r['track']['videoId']}]" if r["type"] == "song" else f"{r['type']}  {r['id']}")


def cmd_lyrics(c, a):
    def fetch(t):
        return c.get("api/lyrics", videoId=t["videoId"], title=t["title"], artist=t["artist"], album=t.get("album", ""), duration=t.get("duration", ""))

    def plain(ly):
        return ("(instrumental)" if ly.get("instrumental") else ly.get("plain") or "\n".join(x[1] for x in ly.get("synced") or [])
                or "No lyrics for this song")
    s = state(c)
    if not s["current"]:
        raise Refused(1, "Nothing is playing")
    ly = fetch(s["current"])
    if not a.follow or JSON:
        return show(ly, plain(ly))
    vid, said = None, -1                       # each line as it is sung, song after song, until Ctrl+C
    while True:
        s = state(c)
        t = s["current"]
        if t and t["videoId"] != vid:
            vid, said, ly = t["videoId"], -1, fetch(t)
            print(f"\n{song(t)}\n")
            if not ly.get("synced"):
                print(plain(ly))
        lines = (ly.get("synced") or []) if t else []
        now = max((i for i, x in enumerate(lines) if x[0] <= s["position"] + 0.3), default=-1)
        for x in lines[said + 1:now + 1] if now > said else []:
            print(x[1] or "")
        said = max(said, now)
        sys.stdout.flush()
        time.sleep(0.5)


def cmd_stats(c, a):
    who = None
    if a.who:
        who = c.person(a.who)["id"]
    elif a.group:
        who = "sem:" + match(c.get("api/seminars"), a.group, "name", "No group is called")["id"]
    st = c.get("api/stats", since=time.time() - a.days * 86400 if a.days else 0, who=who)
    span = f"the last {plural(a.days, 'day')}" if a.days else "all time"
    lines = [f"{plural(st['plays'], 'play')}, {st['minutes']} min, {plural(st['songs'], 'song')} by {plural(st['artists'], 'artist')} ({span})"]
    if st["topSongs"]:
        lines += ["", "Top songs"] + [f"{i:>3}  {song(t)}  x{t['plays']}" for i, t in enumerate(st["topSongs"], 1)]
    if st["topArtists"]:
        lines += ["", "Top artists"] + [f"{i:>3}  {x['name']}  x{x['plays']}" for i, x in enumerate(st["topArtists"], 1)]
    if st["people"]:
        lines += ["", "Who played the most"] + [f"     {c.name_of(p['id'])}  {p['minutes']} min" for p in st["people"]]
    show(st, "\n".join(lines))


# ---------- playlists, likes, history ----------
def the_list(c, name: str) -> dict:
    ls = c.get("api/lists")
    return c.get("api/lists/" + match(ls, name, "name", "No playlist is called")["id"])


def cmd_lists(c, a):
    if a.action == "ls":
        ls = c.get("api/lists")
        return show(ls, "\n".join(f"{p['name']}  ({plural(p['count'], 'song')}" + (f", {c.name_of(p['owner'])}'s" if c.name_of(p["owner"]) else "") + ")"
                                  for p in ls) or "No playlists yet")
    if not a.name:
        raise Usage(f"tunebox lists {a.action} NAME")
    if a.action == "new":
        p = c.call("POST", "api/lists", {"name": a.name, "fromQueue": a.from_queue})
        return show(p, f'Made "{p["name"]}"' + (f" with {plural(len(p['tracks']), 'song')} from the queue" if a.from_queue else ""))
    p = the_list(c, a.name)
    if a.action == "show":
        return show(p, f"{p['name']}\n" + (rows(p["tracks"], lambda t: f"{song(t)}  {t.get('duration', '')}") or "Empty"))
    if a.action == "rename":
        if not a.arg:
            raise Usage("tunebox lists rename NAME NEW-NAME")
        return show(c.call("PATCH", f"api/lists/{p['id']}", {"name": " ".join(a.arg)}), f'"{p["name"]}" is "{" ".join(a.arg)}" now')
    if a.action == "rm":
        return show(c.call("DELETE", f"api/lists/{p['id']}"), f'Deleted "{p["name"]}"')
    if a.action == "play":
        tracks = list(p["tracks"])
        if not tracks:
            raise Refused(404, "That playlist is empty")
        if a.shuffle:
            random.shuffle(tracks)
        return show(*queue_up(c, tracks, "next" if a.next else "add" if a.append else "replace", p["name"]))
    if a.action == "add":
        t = find_tracks(c, " ".join(a.arg), 1)[0][0] if a.arg else state(c)["current"]
        if not t:
            raise Refused(1, "Nothing is playing: say which song")
        r = c.call("POST", f"api/lists/{p['id']}/tracks", {"track": t})
        return show(r, f'{song(t)} is already in "{p["name"]}"' if r["duplicate"] else f'Added {song(t)} to "{p["name"]}"')
    try:                                       # drop: the song at that number
        n = int(a.arg[0])
        t = p["tracks"][n - 1] if n >= 1 else None
    except (IndexError, ValueError):
        t = None
    if not t:
        raise Usage(f"tunebox lists drop NAME NUMBER (1 to {len(p['tracks'])})")
    show(c.call("PATCH", f"api/lists/{p['id']}/tracks", {"op": "remove", "videoId": t["videoId"], "at": n - 1}), f'Took {song(t)} out of "{p["name"]}"')


def cmd_like(c, a):
    t = state(c)["current"]
    if not t:
        raise Refused(1, "Nothing is playing")
    show(c.call("POST", "api/like", {"track": t, "liked": not a.off}), ("Unliked " if a.off else "Liked ") + song(t))


def cmd_history(c, a):
    if a.n == "clear":
        sure(a, "Clear the history for everyone?")
        return show(c.call("DELETE", "api/history"), "History cleared")
    try:
        n = int(a.n)
    except ValueError:
        raise Usage("tunebox history [HOW MANY], or history clear")
    h = c.get("api/history", limit=n)
    show(h, "\n".join(f"{when(t['at'])}  {song(t)}" if t.get("at") else song(t) for t in h) or "Nothing played yet")


# ---------- people and groups ----------
def person_body(a) -> dict:
    b = {"name": getattr(a, "rename", None), "color": a.color, "emoji": a.emoji, "seminars": a.group}
    if getattr(a, "no_phrase", False):
        b["phrase"] = ""
    elif a.phrase:
        b["phrase"] = getpass.getpass("Pass phrase: ") if a.ask else None
        if not b["phrase"]:
            raise Usage("--phrase asks for it on a terminal")
    if a.cap is not None:
        b["cap"] = a.cap
    if a.no_add or getattr(a, "can_add", False):
        b["noAdd"] = bool(a.no_add)
    return {k: v for k, v in b.items() if v is not None}


def cmd_people(c, a):
    if a.action == "ls":
        if c.is_admin():
            ps = c.get("api/admin/people")
            return show(ps, "\n".join(f"{p['name']}  {plural(p['plays'], 'play')}, {p['minutes']} min" + ("  pass phrase" if p["locked"] else "")
                                      + ("  can't add songs" if p.get("noAdd") else "") + (f"  at most {p['cap']} waiting" if p.get("cap") else "")
                                      for p in ps) or "No names yet")
        groups = {s["id"]: s["name"] for s in c.get("api/seminars")}
        return show(c.people(), "\n".join(p["name"] + "".join(f"  {groups[s]}" for s in p.get("seminars", []) if s in groups)
                                          + ("  (pass phrase)" if p.get("locked") else "") for p in c.people()) or "No names yet")
    if not a.name:
        raise Usage(f"tunebox people {a.action} NAME")
    if a.action == "add":
        body = {"name": a.name, **person_body(a)}
        p = c.call("POST", "api/admin/people", body) if c.is_admin() or "cap" in body or "noAdd" in body else new_person(c, **{
            "name": a.name, "groups": a.group, "color": a.color, "emoji": a.emoji, "phrase": body.get("phrase")})
        return show(p, f"Added {p['name']}")
    p = c.person(a.name)
    if a.action == "show":
        info = next(x for x in c.get("api/admin/people") if x["id"] == p["id"])
        d = c.get(f"api/admin/people/{p['id']}/detail")
        top = "".join(f"\n     {t['title']} - {t['artist']}  x{t['plays']}" for t in info["top"])
        return show({**info, **d}, f"{info['name']}: {plural(info['plays'], 'play')}, {info['minutes']} min"
                    + (f", last on {when(info['last'])}" if info["last"] else "") + f"\n{plural(info['likes'], 'like')}, {plural(info['lists'], 'playlist')}"
                    + ("\nCan't add songs" if info.get("noAdd") else "") + (f"\nAt most {info['cap']} songs waiting" if info.get("cap") else "") + top)
    if a.action == "edit":
        body = person_body(a)
        if not body:
            raise Usage("what to change? --rename, --group, --color, --emoji, --phrase, --no-phrase, --cap, --no-add, --can-add")
        own = p["id"] == c.jar.get("tb_who") and "cap" not in body and "noAdd" not in body and not c.is_admin()
        r = c.call("PATCH", f"api/people/{p['id']}" if own else f"api/admin/people/{p['id']}", body)
        return show(r, f"Changed {r['name']}")
    if a.action == "signout":
        return show(c.call("POST", f"api/admin/people/{p['id']}/signout"), f"Every device has to type {p['name']}'s pass phrase again")
    if a.action == "merge":
        if not a.into:
            raise Usage("tunebox people merge NAME INTO-NAME")
        into = c.person(a.into)
        sure(a, f"Merge {p['name']} into {into['name']}? {p['name']} goes away; their plays, likes and playlists become {into['name']}'s.")
        r = c.call("POST", "api/admin/people/merge", {"source": p["id"], "into": into["id"]})
        return show(r, f"Merged {p['name']} into {into['name']} ({plural(r['plays'], 'play')})")
    sure(a, f"Remove {p['name']}" + (", with their plays, likes and playlists?" if a.purge else "? Their plays and likes stay, without a name."))
    show(c.call("DELETE", f"api/admin/people/{p['id']}", params={"mode": "purge" if a.purge else "keep"}), f"Removed {p['name']}")


def cmd_groups(c, a):
    gs = c.get("api/seminars")
    if a.action == "ls":
        return show(gs, "\n".join(g["name"] for g in gs) or "None yet")
    if not a.name:
        raise Usage(f"tunebox groups {a.action} NAME")
    if a.action == "add":
        g = c.call("POST", "api/admin/groups", {"name": a.name, **({"color": a.value} if a.value else {})})
        return show(g, f"Added {g['name']}")
    g = match(gs, a.name, "name", "No group is called")
    if a.action == "rm":
        return show(c.call("DELETE", f"api/admin/groups/{g['id']}"), f"Removed {g['name']}; its people stay")
    if not a.value:
        raise Usage(f"tunebox groups {a.action} NAME " + ("NEW-NAME" if a.action == "rename" else "#RRGGBB"))
    r = c.call("PATCH", f"api/admin/groups/{g['id']}", {"name" if a.action == "rename" else "color": a.value})
    show(r, f"{g['name']} is {r['name']} now" if a.action == "rename" else f"{r['name']} is {r['color']}")


# ---------- the admin ----------
def cmd_admin(c, a):
    if a.action == "status":
        st = c.get("api/admin")
        return show(st, ("No admin password is set yet" if not st["set"] else "This terminal is the admin" if st["admin"] else "Locked here")
                    + (f". Too many wrong passwords: locked for {clock(st['lockedFor'])}" if st["lockedFor"] else ""))
    if a.action == "login":
        if not c.ask and not os.environ.get("TUNEBOX_ADMIN_PASSWORD"):
            raise Usage("tunebox admin login asks for the password: run it on a terminal")
        unlock(c)
        return show({"ok": True}, "This terminal is the admin, until 15 minutes pass without admin work")
    if a.action == "logout":
        r = c.call("POST", "api/admin/logout", {})
        c.jar.pop("tb_admin", None)
        save_config(c.config)
        return show(r, "Locked")
    if a.action == "password":
        if not c.ask:
            raise Usage("tunebox admin password asks for it: run it on a terminal")
        old, new = getpass.getpass("Current admin password: "), getpass.getpass("New admin password: ")
        if new != getpass.getpass("Type it again: "):
            raise Refused(1, "That's not the same")
        return show(c.call("POST", "api/admin/password", {"old": old, "new": new}), "Admin password changed")
    if a.action == "reset":
        if not c.token:
            raise Refused(403, "Only on the server itself, as a user who can read Tunebox's files (try sudo)")
        return show(c.call("POST", "api/admin/reset", {}), "The admin password is forgotten. Whoever opens the admin panel next sets a new one.")
    log = c.get("api/admin/audit", limit=a.n)
    show(log, "\n".join(f"{when(e['t'])}  {e['msg']}" + (f"  ({e['ip']})" if e.get("ip") else "") for e in log) or "Nothing yet")


def cmd_features(c, a):
    if a.action == "ls":
        if not c.is_admin():
            off = c.get("api/house")["off"]
            return show(off, "Off: " + ", ".join(off) if off else "Everything is on")
        h = c.get("api/admin/house")
        return show(h, "\n".join(f"{'off' if k in h['off'] else 'on ':<4} {k}" for k in h["features"]))
    if a.action in ("on", "off"):
        known = c.get("api/admin/house")["features"]
        bad = [k for k in a.names if k not in known]
        if bad or not a.names:
            raise Usage((f'no feature "{bad[0]}". ' if bad else "which? ") + "They are: " + ", ".join(known))
        h = c.call("PATCH", "api/admin/features", {"features": {k: a.action == "on" for k in a.names}})
        return show(h, f"Switched {a.action}: " + ", ".join(a.names))
    if a.action == "export":
        text = json.dumps(c.get("api/admin/features/export"), indent=1)
        if a.names and not JSON:
            Path(a.names[0]).write_text(text + "\n", encoding="utf-8")
            return print(f"Saved the setup to {a.names[0]}")
        return print(text)
    if not a.names:
        raise Usage(f"tunebox features {a.action} " + ("NAME (home, office, party or solo)" if a.action == "preset" else "FILE"))
    if a.action == "preset":
        return show(c.call("POST", "api/admin/features/preset", {"name": a.names[0]}), f"Every switch is set as in the {a.names[0]} preset")
    try:
        setup = json.loads(Path(a.names[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(1, f"Can't read {a.names[0]}: {exc}")
    show(c.call("POST", "api/admin/features/import", {"setup": setup}), "Setup loaded")


def cmd_house(c, a):
    if a.action == "show":
        h = c.get("api/house")
        g, w = h["groups"], h["wall"]
        return show(h, "\n".join([
            f"name            {h['name']}", f"accent          {h['accent'] or 'each device its own'}", f"tz              {h['tz'] or 'the server own time'}",
            f"signups         {h['signups']}", f"group-one       {g['one']}", f"group-many      {g['many']}",
            f"group-required  {'on' if g['required'] else 'off'}", f"group-create    {g['create']}",
            *(f"wall-{k:<11}{'on' if w[k] else 'off'}" for k in WALL), f"off             {', '.join(h['off']) or 'nothing'}"]))
    k, v = a.key, " ".join(a.value)
    if k is None or not a.value and k != "accent" and k != "tz":
        raise Usage("tunebox house set KEY VALUE. Keys: name, accent, tz, signups, group-one, group-many, group-required, group-create, "
                    + ", ".join("wall-" + x for x in WALL))
    if k in ("name", "accent", "tz"):
        body = {k: "" if v in ("none", "own", "server") else v}
    elif k == "signups":
        body = {"signups": "open" if onoff(v) else "closed"}
    elif k in ("group-one", "group-many"):
        body = {"groups": {k[6:]: v}}
    elif k == "group-required":
        body = {"groups": {"required": onoff(v)}}
    elif k == "group-create":
        body = {"groups": {"create": "open" if onoff(v) else "admin"}}
    elif k.startswith("wall-") and k[5:] in WALL:
        body = {"wall": {k[5:]: onoff(v)}}
    else:
        raise Usage(f'no setting "{k}" (tunebox house show)')
    show(c.call("PATCH", "api/admin/house", body), f"{k}: {v or 'none'}")


def cmd_block(c, a):
    if a.action == "ls":
        b = c.get("api/admin/blocks")
        return show(b, "\n".join([f"artist  {x['name']}" for x in b["artists"]] + [f"song    {x['title']} - {x['artist']}  [{x['id']}]" for x in b["songs"]])
                    or "Nothing is blocked")
    if a.action == "add":
        if a.artist:
            body = {"kind": "artist", "name": a.artist}
        else:
            t = find_tracks(c, " ".join(a.what), 1)[0][0] if a.what else state(c)["current"]
            if not t:
                raise Refused(1, "Nothing is playing: say which song, or --artist NAME")
            body = {"kind": "song", "track": t}
        r = c.call("POST", "api/admin/blocks", body)
        return show(r, r["message"])
    if not a.what:
        raise Usage("tunebox block rm NAME (tunebox block ls)")
    b, w = c.get("api/admin/blocks"), " ".join(a.what)
    both = [{"kind": "artists", "key": x["key"], "name": x["name"], "id": x["key"]} for x in b["artists"]] + \
           [{"kind": "songs", "key": x["id"], "name": x["title"], "id": x["id"]} for x in b["songs"]]
    x = match(both, w, "name", "Nothing blocked is called")
    show(c.call("DELETE", f"api/admin/blocks/{x['kind']}/{urllib.parse.quote(x['key'], safe='')}"), f"Unblocked {x['name']}")


# ---------- sound, options, alarm, the YouTube account ----------
def cmd_eq(c, a):
    st = c.get("api/settings")
    if not a.preset:
        bands = "  ".join(f"{f if f < 1000 else str(f // 1000) + 'k'}:{g:+g}" for f, g in zip(st["freqs"], st["bands"]))
        return show(st["eq"], f"{st['eq']['preset']}\n{bands}\nPresets: " + ", ".join(list(st["presets"]) + ["custom"]))
    body = {"preset": a.preset}
    if a.gains:
        if a.preset != "custom" or len(a.gains) != len(st["freqs"]):
            raise Usage(f"tunebox eq custom and {len(st['freqs'])} numbers from -12 to 12 (" + ", ".join(str(f) for f in st["freqs"]) + " Hz)")
        body["custom"] = a.gains
    show(c.call("POST", "api/eq", body)["eq"], f"Equaliser: {a.preset}")


def cmd_options(c, a):
    st = c.get("api/settings")
    if not a.key:
        return show({k: st[k] for k in ("normalize", "autoplay", "turns", "quality")},
                    f"autoplay   {'on' if st['autoplay'] else 'off'}   the radio keeps playing when the queue ends\n"
                    f"turns      {'on' if st['turns'] else 'off'}   songs from different people take turns\n"
                    f"normalize  {'on' if st['normalize'] else 'off'}   every song at the same loudness\n"
                    f"quality    {st['quality']}   ({', '.join(st['qualities'])})")
    if a.key not in ("autoplay", "turns", "normalize", "quality") or not a.value:
        raise Usage("tunebox options autoplay|turns|normalize on|off, or options quality NAME")
    r = c.call("POST", "api/options", {a.key: a.value if a.key == "quality" else onoff(a.value)})
    show({k: r[k] for k in ("normalize", "autoplay", "turns", "quality")}, f"{a.key}: {a.value}")


def cmd_alarm(c, a):
    st = c.get("api/settings")
    al = st["alarm"]
    if a.what is None:
        name = next((p["name"] for p in st["lists"] if p["id"] == al["list"]), "the radio")
        return show(al, (f"Rings at {al['time']} on {', '.join(DAYS[d] for d in al['days']) or 'no day'}" if al["enabled"] else f"Off (set for {al['time']})")
                    + f", plays {name}, up to volume {al['level']} over {al['ramp']:g} min" + (f" ({al['tz']} time)" if al.get("tz") else ""))
    body = {"enabled": al["enabled"], "time": al["time"], "days": al["days"], "list": al["list"], "level": al["level"], "ramp": al["ramp"]}
    if a.what in ("on", "off"):
        body["enabled"] = a.what == "on"
    elif a.what == "test":
        body["test"] = True
    else:
        body.update(enabled=True, time=a.what.zfill(5))
    if a.days:
        body["days"] = list(range(7)) if a.days == "daily" else days_of(a.days)
    if a.list:
        body["list"] = match(st["lists"], a.list, "name", "No playlist is called")["id"]
    if a.level is not None:
        body["level"] = a.level
    if a.ramp is not None:
        body["ramp"] = a.ramp
    al = c.call("POST", "api/alarm", body)["alarm"]
    show(al, "Ringing now, as a test" if a.what == "test" else f"Alarm at {al['time']} on {', '.join(DAYS[d] for d in al['days'])}" if al["enabled"] else "Alarm off")


def days_of(text: str) -> list[int]:
    out = []
    for part in text.lower().split(","):
        a, _, b = part.partition("-")
        try:
            i, j = DAYS.index(a[:3]), DAYS.index((b or a)[:3])
        except ValueError:
            raise Usage("--days mon,wed or mon-fri or daily")
        out += [d % 7 for d in range(i, j + 1 if j >= i else j + 8)]
    return sorted(set(out))


def cmd_account(c, a):
    if a.action == "status":
        r = c.get("api/settings")["account"]
        return show(r, "Signed in to YouTube Music" if r["signedIn"] else "Not signed in to YouTube Music")
    if a.action == "signout":
        return show(c.call("DELETE", "api/account"), "Signed out of YouTube Music")
    if not a.file:
        raise Usage("tunebox account signin FILE: the request headers copied from music.youtube.com (- reads them from the input)")
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    show(c.call("POST", "api/account", {"headers": text}), "Signed in to YouTube Music")


# ---------- local songs ----------
class Sending:
    """A file on its way up, saying how far it is."""
    def __init__(self, path: Path, quiet: bool):
        self.f, self.size, self.sent, self.name, self.quiet = path.open("rb"), path.stat().st_size, 0, path.name, quiet

    def read(self, n=-1):
        chunk = self.f.read(n)
        self.sent += len(chunk)
        if not self.quiet and self.size:
            print(f"\r{self.name}  {self.sent * 100 // self.size}%", end="", file=sys.stderr, flush=True)
        return chunk

    def close(self):
        self.f.close()


def local_song(c, name: str) -> dict:
    songs = [{**s, "id": s["videoId"][6:]} for s in c.get("api/local")["songs"]]
    return match(songs, name[6:] if name.startswith("local:") else name, "title", "No local song is called")


def cmd_local(c, a):
    if a.action == "ls":
        r = c.get("api/local")
        return show(r, "\n".join(f"{song(s)}  {s.get('duration', '')}  {size(s['size'])}" + (f"  ({c.name_of(s['by'])})" if c.name_of(s["by"]) else "")
                                 + f"  [{s['videoId']}]" for s in r["songs"]) or "No local songs yet")
    if a.action == "space":
        d = c.get("api/admin/local/disk")
        enc = d["encoders"]
        return show(d, f"{plural(d['count'], 'local song')}, {size(d['used'])}" + (f" of {d['capGB']:g} GB" if d["capGB"] is not None else "")
                    + f"\nDisk: {size(d['free'])} free of {size(d['total'])}, {d['reserveGB']:g} GB always kept free\nRoom for {size(d['room'])} more, "
                    + f"files up to {d['maxMB']} MB\nConverts WAV and AIFF to FLAC: {'yes' if enc['mpv'] and enc['flac'] else 'no'}; the rest to Opus: "
                    + ("yes" if enc["mpv"] and enc["opus"] else "no"))
    if a.action == "limits":
        body = {"capGB": None if a.cap is None else -1 if a.cap in ("none", "off") else float(a.cap), "reserveGB": a.reserve, "maxMB": a.max}
        body = {k: v for k, v in body.items() if v is not None}
        if not body:
            raise Usage("tunebox local limits [--cap GB|none] [--reserve GB] [--max MB]")
        d = c.call("PATCH", "api/admin/local/limits", body)
        cap = "no cap" if d["capGB"] is None else f"{d['capGB']:g} GB"
        return show(d, f"Local songs: {cap}, {d['reserveGB']:g} GB kept free, files up to {d['maxMB']} MB")
    if not a.names:
        raise Usage(f"tunebox local {a.action} " + ("FILE..." if a.action == "upload" else "SONG"))
    if a.action == "upload":
        info = c.get("api/local")              # what fits is checked here first: a refused upload is sent whole for nothing
        if "people" not in c.get("api/house")["off"] and not c.me() and not (c.ask and pick_name(c)):
            raise Refused(401, "Say who you are first: tunebox iam NAME")
        done, failed, quiet = [], 0, JSON or not sys.stderr.isatty()
        for name in a.names:
            path = Path(name)
            problem = ("no such file" if not path.is_file() else f"too big: a file can be {info['maxMB']} MB at most" if path.stat().st_size > info["maxMB"] * 2**20
                       else "there is no room left for local songs" if path.stat().st_size > info["room"] else "")
            if problem:
                print(f"tunebox: {name}: {problem}", file=sys.stderr)
                failed += 1
                continue
            try:
                s = c.call("POST", "api/local/upload", params={"name": path.name}, data=lambda: Sending(path, quiet), timeout=900)
            except Refused as exc:
                print(("" if quiet else "\r") + f"tunebox: {path.name}: {exc.detail}", file=sys.stderr)
                failed += 1
                continue
            done.append(s)
            if not JSON:
                print(("" if quiet else "\r") + f'{path.name}: added as "{s["title"]}"' + (f" (now {s['ext'].upper()})" if s["was"] != s["ext"] else "")
                      + f"  [{s['videoId']}]")
        if JSON:
            show(done)
        if failed:
            raise Refused(1, f"{plural(failed, 'file')} not added")
        return
    s = local_song(c, " ".join(a.names))
    if a.action == "rm":
        return show(c.call("DELETE", f"api/local/{s['id']}"), f"Removed {song(s)}")
    body = {k: v for k, v in (("title", a.title), ("artist", a.artist), ("album", a.album)) if v is not None}
    if not body and not a.cover:
        raise Usage("what to change? --title, --artist, --album, --cover FILE")
    r = c.call("PATCH", f"api/local/{s['id']}", body) if body else s
    if a.cover:
        pic = Path(a.cover)
        kind = {"png": "image/png", "webp": "image/webp"}.get(pic.suffix.lower().lstrip("."), "image/jpeg")
        r = c.call("POST", f"api/local/{s['id']}/cover", data=pic.read_bytes(), ctype=kind)
    show(r, f"Changed {song(r)}")


# ---------- backup ----------
def cmd_backup(c, a):
    r = c.call("GET", "api/backup/full" if a.full else "api/backup", raw=True, timeout=600)
    named = re.search(r'filename="([^"]+)"', r.headers.get("Content-Disposition") or "")
    path = Path(a.file or (named.group(1) if named else "tunebox-backup.json"))
    n = 0
    with path.open("wb") as out:
        while chunk := r.read(1 << 18):
            out.write(chunk)
            n += len(chunk)
    note = ""
    if not a.full:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("stripped"):
                note = "\nWithout pass phrases and keys: only the admin's backup has those (tunebox admin login)"
        except ValueError:
            pass
    show({"file": str(path), "bytes": n}, f"Saved {path} ({size(n) if n >= 2**20 else str(n // 1024) + ' KB'})" + note)


def cmd_restore(c, a):
    path = Path(a.file)
    try:
        if path.suffix.lower() == ".zip":      # a full backup: the JSON inside it; the audio is unzipped by hand
            import zipfile
            with zipfile.ZipFile(path) as z:
                backup = json.loads(z.read("tunebox-backup.json"))
        else:
            backup = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise Refused(1, f"Can't read {path}: {exc}")
    sure(a, "Replace everything here (people, playlists, history, stats, settings) with what is in that file?")
    r = c.call("POST", "api/restore", {"backup": backup}, timeout=300)
    show(r, f"Restored. What was here before is in backups/{r['before']} on the server."
         + ("\nThe local songs' audio is not restored from here: unzip the local folder into Tunebox's data folder." if path.suffix.lower() == ".zip" else ""))


# ---------- watch: a live view with a few keys ----------
def read_keys(put):
    """Calls put(key) for every key pressed, until the program ends."""
    if os.name == "nt":
        import msvcrt
        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):         # arrows and function keys come as two
                msvcrt.getwch()
                continue
            put(ch)
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                put(sys.stdin.read(1))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def cmd_watch(c, a):
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        raise Usage("tunebox watch needs a terminal (tunebox status prints once)")
    keys: list[str] = []
    restore = None
    if os.name == "nt":
        os.system("")                          # switches on ANSI escapes in the Windows console
    else:
        import termios
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)          # as the terminal was, before the key reader changes it
        restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)   # noqa: E731
    threading.Thread(target=read_keys, args=(keys.append,), daemon=True).start()
    print("\x1b[?25l\x1b[2J", end="")
    said, s = "", {}
    try:
        while True:
            try:
                s = state(c)
            except Unreachable:
                said = "Tunebox doesn't answer..."
            for _ in range(5):                 # a key acts at once; the view refreshes each second
                while keys:
                    k = keys.pop(0)
                    if k in ("q", "\x03", "\x1b"):
                        return
                    act = {" ": ("toggle", {}), "n": ("next", {}), "p": ("prev", {}),
                           "+": ("volume", {"value": min(100, s.get("volume", 50) + 5)}), "=": ("volume", {"value": min(100, s.get("volume", 50) + 5)}),
                           "-": ("volume", {"value": max(0, s.get("volume", 50) - 5)})}.get(k)
                    if act:
                        try:
                            said = control(c, act[0], **act[1]).get("message") or ""
                            s = state(c)
                        except (Refused, Unreachable) as exc:
                            said = str(exc)
                draw_watch(c, s, said)
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if restore:
            restore()
        print("\x1b[?25h\x1b[0m")


def draw_watch(c, s, said):
    width = max(30, shutil.get_terminal_size().columns - 1)
    q, t = s.get("queue") or [], s.get("current")
    lines = ["Nothing is playing" if not t else ("Paused   " if s["paused"] else "Playing  ") + song(t)]
    if t:
        done = int((width - 14) * s["position"] / s["duration"]) if s["duration"] else 0
        lines.append(f"{clock(s['position']):>5} " + "#" * done + "-" * (width - 14 - done) + f" {clock(s['duration'])}")
    lines += [f"Volume {s.get('volume', '')}", ""]
    for i, x in enumerate(q[1:11], 1):
        if i == s["userCount"] + 1:
            lines.append("     radio:")
        lines.append(f"{i:>3}  {song(x)}")
    lines += ["", said, "space play/pause   n next   p previous   + - volume   q quit"]
    print("\x1b[H" + "".join(line[:width] + "\x1b[K\n" for line in lines) + "\x1b[J", end="", flush=True)


# ---------- the command line ----------
def build() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server", default=argparse.SUPPRESS, help="a Tunebox's address, or a saved server's name")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the server's answer as JSON")
    common.add_argument("--no-input", action="store_true", default=argparse.SUPPRESS, help="never ask anything")
    common.add_argument("--yes", "-y", action="store_true", default=argparse.SUPPRESS, help='answer "are you sure" with yes')
    ap = argparse.ArgumentParser(prog="tunebox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    def cmd(name, fn, text, *args):
        p = sub.add_parser(name, help=text, description=text, parents=[common])
        p.set_defaults(fn=fn)
        for flags, kw in args:
            p.add_argument(*flags, **kw)
        return p

    def arg(*flags, **kw):
        return flags, kw
    modes = [arg("--next", action="store_true", help="right after this song"), arg("--now", action="store_true", help="interrupt: play it now")]
    cmd("server", cmd_server, "saved Tunebox addresses: ls, add NAME URL, use NAME, rm NAME",
        arg("action", choices=["ls", "add", "use", "rm"], nargs="?", default="ls"), arg("name", nargs="?"), arg("url", nargs="?"))
    cmd("whoami", cmd_whoami, "which Tunebox this is, who you are on it, and whether you are the admin")
    cmd("iam", cmd_iam, "say who you are (the songs you add carry your name)", arg("name", nargs="?"), arg("--none", action="store_true", help="nobody"),
        arg("--new", action="store_true", help="add the name if nobody has it"), arg("--group", "-g", action="append", help="with --new: its group"))
    cmd("status", cmd_status, "what is playing")
    for name, text in (("play", "carry on"), ("pause", "pause"), ("toggle", "play or pause"), ("next", "the next song"),
                       ("prev", "the song's start, or the one before"), ("stop", "stop and empty the player")):
        cmd(name, cmd_transport, text)
    cmd("seek", cmd_seek, "jump in the song: 1:30, 90, +10, -10", arg("to"))
    cmd("vol", cmd_vol, "the volume: 60, +5, -5 (nothing: say it)", arg("level", nargs="?"))
    cmd("sleep", cmd_sleep, "the sleep timer: MINUTES, track (stop after this song), off", arg("what", nargs="?"))
    cmd("undo", cmd_undo, "undo the last change to the queue")
    cmd("add", cmd_add, "add a song (words, a YouTube link, an id), an album or a playlist to the queue", arg("what", nargs="+"), *modes,
        arg("--replace", action="store_true", help="replace the queue"), arg("--pick", type=int, default=1, metavar="N", help="the Nth search result (tunebox search)"))
    cmd("radio", cmd_radio, "refresh: new radio songs; clear: take them out", arg("action", choices=["refresh", "clear"]))
    cmd("queue", cmd_queue, "up next; rm N, mv N PLACE, top N (plays next), jump N, shuffle, clear, history, restore ID",
        arg("action", choices=["ls", "rm", "mv", "top", "jump", "shuffle", "clear", "history", "restore"], nargs="?", default="ls"),
        arg("id", nargs="?"), arg("to", nargs="?", type=int))
    cmd("search", cmd_search, "search YouTube Music (and the local songs)", arg("query", nargs="+"),
        arg("--kind", "-k", choices=["songs", "albums", "artists", "playlists"], default="songs"))
    for name in ("album", "artist", "playlist"):
        cmd(name, cmd_page, f"a YouTube Music {name}'s songs (its id is in the search results)", arg("id"), arg("--play", action="store_true", help="play it now"),
            arg("--add", action="store_true", help="add it to the queue"), arg("--next", action="store_true", help="play it next"))
    cmd("home", cmd_home, "the house's own shelves and YouTube Music's home page")
    cmd("explore", cmd_explore, "new releases and moods")
    cmd("resolve", cmd_resolve, "what a YouTube link points to", arg("url"))
    cmd("lyrics", cmd_lyrics, "the lyrics of the song playing", arg("--follow", "-f", action="store_true", help="line by line, as it is sung"))
    cmd("stats", cmd_stats, "what the house played", arg("--days", type=int, default=30, help="how far back (0: all time)"),
        arg("--who", help="one person"), arg("--group", help="one group"))
    cmd("lists", cmd_lists, "playlists: ls, show NAME, new NAME, rename NAME NEW, rm NAME, play NAME, add NAME [SONG], drop NAME NUMBER",
        arg("action", choices=["ls", "show", "new", "rename", "rm", "play", "add", "drop"], nargs="?", default="ls"), arg("name", nargs="?"),
        arg("arg", nargs="*"), arg("--from-queue", action="store_true", help="new: with the songs in the queue"),
        arg("--shuffle", action="store_true", help="play: in a random order"), arg("--next", action="store_true", help="play: right after this song"),
        arg("--add", dest="append", action="store_true", help="play: at the end of the queue"))
    cmd("like", cmd_like, "like the song playing", arg("--off", action="store_true", help="unlike it"))
    cmd("history", cmd_history, "what played: history [HOW MANY], or history clear (the admin)", arg("n", nargs="?", default="20"))
    cmd("people", cmd_people, "names: ls, show NAME, add NAME, edit NAME, rm NAME, merge NAME INTO, signout NAME (all but ls and add: the admin)",
        arg("action", choices=["ls", "show", "add", "edit", "rm", "merge", "signout"], nargs="?", default="ls"), arg("name", nargs="?"), arg("into", nargs="?"),
        arg("--rename", help="edit: the new name"), arg("--group", "-g", action="append", help="a group (repeat for more)"), arg("--color", help="#RRGGBB"),
        arg("--emoji"), arg("--phrase", action="store_true", help="set a pass phrase (asked for)"), arg("--no-phrase", action="store_true", help="take the pass phrase off"),
        arg("--cap", type=int, help="at most this many songs waiting (0: no limit)"), arg("--no-add", action="store_true", help="can't add songs"),
        arg("--can-add", action="store_true", help="can add songs again"), arg("--purge", action="store_true", help="rm: their plays, likes and playlists too"))
    cmd("groups", cmd_groups, "groups: ls, add NAME, rename NAME NEW, color NAME #RRGGBB, rm NAME (the admin)",
        arg("action", choices=["ls", "add", "rename", "color", "rm"], nargs="?", default="ls"), arg("name", nargs="?"), arg("value", nargs="?"))
    cmd("admin", cmd_admin, "the admin: status, login, logout, password, reset (on the server only), log [HOW MANY]",
        arg("action", choices=["status", "login", "logout", "password", "reset", "log"], nargs="?", default="status"), arg("n", nargs="?", type=int, default=30))
    cmd("features", cmd_features, "the feature switches: ls, on NAME..., off NAME..., preset NAME, export [FILE], import FILE",
        arg("action", choices=["ls", "on", "off", "preset", "export", "import"], nargs="?", default="ls"), arg("names", nargs="*"))
    cmd("house", cmd_house, "the house's setup: show, set KEY VALUE", arg("action", choices=["show", "set"], nargs="?", default="show"),
        arg("key", nargs="?"), arg("value", nargs="*"))
    cmd("block", cmd_block, "blocked songs and artists: ls, add [SONG] (nothing: the one playing), add --artist NAME, rm NAME",
        arg("action", choices=["ls", "add", "rm"], nargs="?", default="ls"), arg("what", nargs="*"), arg("--artist"))
    cmd("eq", cmd_eq, "the equaliser: a preset's name, or custom and ten gains", arg("preset", nargs="?"), arg("gains", nargs="*", type=float))
    cmd("options", cmd_options, "autoplay, turns, normalize (on or off) and quality", arg("key", nargs="?"), arg("value", nargs="?"))
    cmd("alarm", cmd_alarm, "the wake-up alarm: HH:MM, on, off, test", arg("what", nargs="?"), arg("--days", help="mon,wed or mon-fri or daily"),
        arg("--list", help="the playlist it plays"), arg("--level", type=int, help="the volume it reaches"), arg("--ramp", type=float, help="minutes to get there"))
    cmd("account", cmd_account, "the YouTube Music sign-in: status, signin FILE, signout", arg("action", choices=["status", "signin", "signout"], nargs="?", default="status"),
        arg("file", nargs="?"))
    cmd("local", cmd_local, "local songs: ls, upload FILE..., edit SONG, rm SONG, space, limits",
        arg("action", choices=["ls", "upload", "edit", "rm", "space", "limits"], nargs="?", default="ls"), arg("names", nargs="*"),
        arg("--title"), arg("--artist"), arg("--album"), arg("--cover", help="edit: a JPEG, PNG or WebP picture"),
        arg("--cap", help="limits: GB in all, or none"), arg("--reserve", type=float, help="limits: GB always kept free"), arg("--max", type=int, help="limits: the biggest file, MB"))
    cmd("backup", cmd_backup, "save a backup to a file", arg("file", nargs="?"), arg("--full", action="store_true", help="a zip with the local songs' audio too (the admin)"))
    cmd("restore", cmd_restore, "replace everything with a backup (the admin)", arg("file"))
    cmd("watch", cmd_watch, "a live view: space, n, p, + and -, q")
    return ap


def main(argv=None) -> int:
    global JSON
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):    # a name with an emoji must not stop a pipe or an old console
            stream.reconfigure(errors="replace", **({} if stream.isatty() else {"encoding": "utf-8"}))
    ap = build()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    JSON = getattr(a, "json", False)
    a.yes = getattr(a, "yes", False)
    a.ask = sys.stdin.isatty() and not getattr(a, "no_input", False)
    if a.cmd == "queue":                       # "queue rm 2": the number; "queue restore ab12": the id
        a.n = int(a.id) if a.id and a.id.isdigit() and a.action != "restore" else None
    config = load_config()
    c = Client(server_url(config, getattr(a, "server", None)), config, a.ask)
    try:
        a.fn(c, a)
        return 0
    except Usage as exc:
        print(f"tunebox: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"tunebox: {exc.detail}", file=sys.stderr)
        return 1
    except Unreachable as exc:
        print(f"tunebox: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print()
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())

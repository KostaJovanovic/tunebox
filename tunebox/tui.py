"""Tunebox as a full-screen terminal program: tunebox tui (cli.py starts it and lends it its HTTP
client, cookies and token). Tabs for Home, Search, Queue, Playlists, History, Local, Stats, Lyrics,
Settings and Admin; a player line at the bottom; pop-ups for choices and forms.

No library: curses is missing on Windows. The pieces, top to bottom:
  text widths      how many cells a string takes (wide and emoji characters, combining marks)
  Screen           a grid of cells, diffed against the last frame so only what changed is written
  Decoder          bytes from a terminal -> key names (arrows, PgUp, a paste...); win_keys for msvcrt
  Terminal         the real terminal: alternate screen, raw keys, restored on the way out
  Net              two worker threads for requests, one polling api/state each second
  App              the tabs, the layout, the keys, the pop-ups
  views            one class per tab or page

Nothing here imports the server's modules, and cli.py is handed in, not imported: python cli.py runs
it as __main__, and a second import would be a second copy."""
import itertools
import os
import queue
import random
import shutil
import sys
import threading
import time
import unicodedata
from pathlib import Path

# ---------- text widths ----------
ZERO = {0x200B, 0x200C, 0x200D, 0x2060, 0xFE0E, 0xFE0F, 0xFEFF}
UNI = {"play": "▶", "full": "━", "rest": "─", "heart": "♥", "v": "│", "h": "─", "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
       "dot": "·", "block": "█", "dots": "…", "levels": " ▁▂▃▄▅▆▇█", "on": "●", "off": "○", "more": "›"}
ASC = {"play": ">", "full": "=", "rest": "-", "heart": "*", "v": "|", "h": "-", "tl": "+", "tr": "+", "bl": "+", "br": "+",
       "dot": "-", "block": "#", "dots": "...", "levels": " .:-=+*#@", "on": "x", "off": " ", "more": ">"}
ASCII = False                                 # --ascii: plain characters only, for terminals that draw the others badly


def g(name: str) -> str:
    return (ASC if ASCII else UNI)[name]


def char_width(ch: str) -> int:
    o = ord(ch)
    if o < 32 or 0x7F <= o < 0xA0:
        return 0
    if o < 0x300:
        return 1
    if o in ZERO or unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf") or 0x1F3FB <= o <= 0x1F3FF:
        return 0
    if unicodedata.east_asian_width(ch) in "WF" or 0x1F000 <= o <= 0x1FAFF:
        return 2                              # CJK, and the emoji blocks terminals draw two cells wide
    return 1


def clusters(text) -> list[tuple[str, int]]:
    """The text as what a terminal draws in one go: a character with what rides on it (accents, a
    skin tone, the parts of a joined emoji), and how many cells it takes."""
    out: list[tuple[str, int]] = []
    join = False
    for ch in str(text):
        o, w = ord(ch), char_width(ch)
        if o < 32 or 0x7F <= o < 0xA0:
            ch, w = " ", 1                    # a tab or a line break in a title
        flag = 0x1F1E6 <= o <= 0x1F1FF and out and len(out[-1][0]) == 1 and 0x1F1E6 <= ord(out[-1][0]) <= 0x1F1FF
        if out and (w == 0 or join or flag):
            prev, pw = out[-1]
            out[-1] = (prev + ch, 2 if o == 0xFE0F or flag else pw)   # "show as emoji" makes it wide
        else:
            out.append((ch, w or 1))
        join = o == 0x200D
    if ASCII:
        out = [(c, 1) if w == 1 and len(c) == 1 else ("?", 1) for c, w in out]
    return out


def text_width(text) -> int:
    return sum(w for _, w in clusters(text))


def clip(text, width: int) -> str:
    """At most `width` cells of it, ending in dots when it was cut."""
    cl = clusters(text)
    if sum(w for _, w in cl) <= width:
        return "".join(c for c, _ in cl)
    dots = g("dots")
    out, used = [], 0
    for c, w in cl:
        if used + w > width - len(dots):
            break
        out.append(c)
        used += w
    return "".join(out) + dots if width >= len(dots) else ""


# ---------- the screen ----------
COLOR = {"": "0", "b": "1", "dim": "90", "sel": "7", "red": "91", "yel": "93", "blue": "94", "head": "1;94", "now": "1;91", "tab": "1;7", "ok": "92"}
PLAIN = {"": "0", "b": "1", "dim": "2", "sel": "7", "red": "1", "yel": "1", "blue": "0", "head": "1", "now": "1", "tab": "1;7", "ok": "0"}
EMPTY = (" ", "")


class Screen:
    """What should be on the terminal, cell by cell. render() writes only the runs that differ from
    what is there, which is what makes it usable over a slow connection."""
    def __init__(self, cols: int, rows: int, color: bool = True):
        self.cols, self.rows, self.sgr = cols, rows, COLOR if color else PLAIN
        self.cur = [[EMPTY] * cols for _ in range(rows)]
        self.old = None                       # None: nothing is known to be there, draw it all

    def clear(self):
        for row in self.cur:
            row[:] = [EMPTY] * self.cols

    def put(self, x: int, y: int, text, style: str = "", width: int | None = None) -> int:
        """Writes text at x, y, cut to `width` cells (or the edge). Returns the x after it."""
        if not 0 <= y < self.rows or x >= self.cols:
            return x
        end = min(self.cols, x + width) if width is not None else self.cols
        row = self.cur[y]
        for c, w in clusters(text):
            if x + w > end:
                break
            if x >= 0:
                row[x] = (c, style)
                if w == 2:
                    row[x + 1] = ("", style)  # the second half of a wide character
            x += w
        return x

    def fill(self, x: int, y: int, width: int, style: str = "", ch: str = " "):
        self.put(x, y, ch * max(0, width), style, width)

    def lines(self) -> list[str]:
        return ["".join(c for c, _ in row).rstrip() for row in self.cur]

    def render(self) -> str:
        out, style = [], None
        for y, row in enumerate(self.cur):
            old = self.old[y] if self.old else None
            x = 0
            while x < self.cols:
                if old and row[x] == old[x]:
                    x += 1
                    continue
                start = x
                while x < self.cols and not (old and row[x] == old[x] and row[min(x + 1, self.cols - 1)] == old[min(x + 1, self.cols - 1)]):
                    x += 1                    # a single unchanged cell between two changed ones isn't worth a jump
                while start > 0 and row[start][0] == "":
                    start -= 1                # never start in the middle of a wide character
                out.append(f"\x1b[{y + 1};{start + 1}H")
                for c, st in row[start:x]:
                    if st != style:
                        out.append(f"\x1b[0;{self.sgr.get(st, '0')}m")
                        style = st
                    out.append(c)
        self.old = [list(row) for row in self.cur]
        return "".join(out) + ("\x1b[0m" if out else "")


# ---------- keys ----------
CSI_LETTER = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end", "Z": "btab", "P": "f1", "Q": "f2", "R": "f3", "S": "f4"}
CSI_TILDE = {1: "home", 2: "ins", 3: "del", 4: "end", 5: "pgup", 6: "pgdn", 7: "home", 8: "end", 11: "f1", 12: "f2", 13: "f3", 14: "f4",
             15: "f5", 17: "f6", 18: "f7", 19: "f8", 20: "f9", 21: "f10", 23: "f11", 24: "f12"}
MOD = {2: "s-", 3: "a-", 4: "s-", 5: "c-", 6: "c-"}
CTRL = {"\r": "enter", "\n": "enter", "\t": "tab", "\x7f": "backspace", "\x08": "backspace", " ": "space", "\x00": "c-space"}
WIN = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end", "I": "pgup", "Q": "pgdn", "R": "ins", "S": "del",
       "s": "c-left", "t": "c-right", ";": "f1", "<": "f2", "=": "f3", ">": "f4", "?": "f5", "@": "f6", "A": "f7", "B": "f8", "C": "f9", "D": "f10",
       "\x85": "f11", "\x86": "f12", "\x8d": "c-up", "\x91": "c-down"}


def plain_key(ch: str) -> str:
    if ch in CTRL:
        return CTRL[ch]
    if ch < " ":
        return "c-" + chr(ord(ch) + 96)       # Ctrl+C is "c-c"
    return ch


class Decoder:
    """What a terminal sends, as key names. feed() takes whatever arrived and gives the keys that are
    complete; an escape sequence cut in two waits for its rest. flush() is for when nothing more came:
    a lone ESC was the Esc key. A paste comes as one key: "paste:<text>"."""
    def __init__(self):
        self.buf, self.paste = "", None
        import codecs
        self.utf8 = codecs.getincrementaldecoder("utf-8")("replace")

    def feed(self, data) -> list[str]:
        self.buf += self.utf8.decode(data) if isinstance(data, bytes) else data
        keys = []
        while self.buf:
            if self.paste is not None:
                end = self.buf.find("\x1b[201~")
                if end < 0:
                    keep = next((n for n in range(5, 0, -1) if self.buf.endswith("\x1b[201~"[:n])), 0)   # the end mark may be cut in two
                    self.paste += self.buf[:len(self.buf) - keep]
                    self.buf = self.buf[len(self.buf) - keep:]
                    break
                keys.append("paste:" + (self.paste + self.buf[:end]).replace("\r\n", "\n").replace("\r", "\n"))
                self.buf, self.paste = self.buf[end + 6:], None
                continue
            ch = self.buf[0]
            if ch != "\x1b":
                keys.append(plain_key(ch))
                self.buf = self.buf[1:]
                continue
            if len(self.buf) == 1:
                break                         # Esc, or the start of a sequence: wait
            nxt = self.buf[1]
            if nxt == "[":
                n = 2
                while n < len(self.buf) and not "@" <= self.buf[n] <= "~":
                    n += 1
                if n >= len(self.buf):
                    break                     # not all of it yet
                seq, final = self.buf[2:n], self.buf[n]
                self.buf = self.buf[n + 1:]
                nums = [int(p) if p.isdigit() else 0 for p in seq.lstrip("?<>=").split(";")] if seq else []
                mod = MOD.get(nums[1], "") if len(nums) > 1 else ""
                if final == "~" and nums and nums[0] == 200:
                    self.paste = ""
                elif final == "~" and nums and nums[0] in CSI_TILDE:
                    keys.append(mod + CSI_TILDE[nums[0]])
                elif final in CSI_LETTER:
                    keys.append(CSI_LETTER[final] if final == "Z" else mod + CSI_LETTER[final])
            elif nxt == "O":                  # application keypad mode: xterm after some programs, PuTTY
                if len(self.buf) < 3:
                    break
                keys.append(CSI_LETTER.get(self.buf[2], ""))
                self.buf = self.buf[3:]
            elif nxt == "\x1b":
                keys.append("esc")
                self.buf = self.buf[1:]
            else:                             # Alt+key: the key itself
                keys.append("a-" + plain_key(nxt))
                self.buf = self.buf[2:]
        return [k for k in keys if k]

    def flush(self) -> list[str]:
        if self.buf == "\x1b":
            self.buf = ""
            return ["esc"]
        return []


def win_keys(chars) -> list[str]:
    """msvcrt.getwch() gives arrows and function keys as two characters: a 0 or 0xE0, then a code."""
    keys, special = [], False
    for ch in chars:
        if special:
            keys.append(WIN.get(ch, ""))
            special = False
        elif ch in ("\x00", "\xe0"):
            special = True
        else:
            keys.append("esc" if ch == "\x1b" else plain_key(ch))
    return [k for k in keys if k]


# ---------- the terminal ----------
class Terminal:
    """The real one: the alternate screen (what was on the terminal comes back afterwards), keys one by
    one, and everything put back on the way out, however that happens."""
    def __init__(self):
        self.saved, self.on = None, False

    def size(self) -> tuple[int, int]:
        s = shutil.get_terminal_size()
        return s.columns, s.lines

    def write(self, text: str):
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    def start(self, put):
        """put(key) is called from a thread for every key."""
        self.on = True
        if os.name == "nt":
            os.system("")                     # switches on ANSI escapes in the Windows console
        else:
            import termios
            import tty
            self.saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())
        self.write("\x1b[?1049h\x1b[?25l\x1b[?2004h\x1b[2J")   # alternate screen, no cursor, pastes marked
        threading.Thread(target=self.read, args=(put,), daemon=True).start()

    def stop(self):
        if not self.on:
            return
        self.on = False
        self.write("\x1b[0m\x1b[?2004l\x1b[?25h\x1b[?1049l")
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved)

    def read(self, put):
        if os.name == "nt":
            import msvcrt
            while self.on:
                chars = msvcrt.getwch()
                if chars in ("\x00", "\xe0"):
                    chars += msvcrt.getwch()
                for k in win_keys(chars):
                    put(k)
            return
        import select
        fd, dec = sys.stdin.fileno(), Decoder()
        while self.on:
            ready, _, _ = select.select([fd], [], [], 0.05)
            keys = dec.feed(os.read(fd, 4096)) if ready else dec.flush()
            for k in keys:
                put(k)


class Offscreen:
    """A terminal that isn't there: a size, and what was written to it. The checks drive the app with this."""
    def __init__(self, cols=120, rows=40):
        self.cols, self.rows, self.out = cols, rows, []

    def size(self):
        return self.cols, self.rows

    def write(self, text):
        self.out.append(text)


# ---------- requests ----------
class Net:
    """Requests off the main thread: two workers, and a third that asks for api/state each second.
    Every answer comes back as an event; with threads=False (the checks) a request is made on the spot."""
    def __init__(self, client, post, threads: bool):
        self.client, self.post, self.threads = client, post, threads
        self.jobs: queue.Queue = queue.Queue()
        self.seq = itertools.count(1)          # every api/state request is numbered when it is sent
        if threads:
            for _ in range(2):
                threading.Thread(target=self.work, daemon=True).start()
            threading.Thread(target=self.poll, daemon=True).start()

    def submit(self, job: dict):
        if self.threads:
            self.jobs.put(job)
        else:
            self.post(("net", job, *self.run(job)))

    def run(self, job):
        try:
            r = self.client.once(job["method"], job["path"], job.get("body"), job.get("params"), job.get("data"), job.get("ctype"),
                                 job.get("timeout", 30), bool(job.get("save")))
            if job.get("save"):               # a download: straight to the file
                n = 0
                with open(job["save"], "wb") as out:
                    while chunk := r.read(1 << 18):
                        out.write(chunk)
                        n += len(chunk)
                r = {"file": job["save"], "bytes": n}
            return r, None
        except Exception as exc:              # the main thread says what went wrong
            return None, exc

    def work(self):
        while True:
            job = self.jobs.get()
            self.post(("net", job, *self.run(job)))

    def poll(self):
        while True:
            n = next(self.seq)
            self.post(("state", *self.run({"method": "GET", "path": "api/state", "timeout": 8}), n))
            time.sleep(1)


# ---------- rows: what every list here is made of ----------
def head(text, right=""):
    return {"head": True, "text": text, "right": right}


def item(text, right="", run=None, **more):
    return {"text": text, "right": right, "run": run, **more}


def move(rows, sel, d) -> int:
    """The row d steps from sel that can be selected (headings can't)."""
    n, i = len(rows), sel
    step = 1 if d > 0 else -1
    for _ in range(abs(d)):
        j = i + step
        while 0 <= j < n and rows[j].get("head"):
            j += step
        if not 0 <= j < n:
            break
        i = j
    if rows and rows[i].get("head"):          # the first row is a heading: the first one below it
        i = next((k for k in range(n) if not rows[k].get("head")), i)
    return i


def draw_rows(s: Screen, rows, sel, top, x, y, w, h, playing=None, focus=True):
    for k in range(h):
        i = top + k
        if i >= len(rows):
            break
        r = rows[i]
        right = clip(r.get("right") or "", max(0, w // 2))
        rw = text_width(right)
        if r.get("head"):
            s.put(x, y + k, clip(r["text"], w - rw - 1), "head", w)
            s.put(x + w - rw, y + k, right, "dim")
            continue
        chosen = i == sel and focus
        now = playing and r.get("track") and r["track"].get("videoId") == playing and r.get("mark", True)
        st = "sel" if chosen else ""
        if chosen:
            s.fill(x, y + k, w, "sel")
        s.put(x, y + k, (g("play") if now else " ") + " ", st or "now")
        room = w - 2 - (rw + 2 if rw else 0)
        after = s.put(x + 2, y + k, clip(r["text"], room), st or ("now" if now else r.get("style", "")), room)
        if r.get("sub") and after + 3 < x + 2 + room:
            s.put(after + 2, y + k, clip(r["sub"], x + 2 + room - after - 2), st or "dim")
        if rw:
            s.put(x + w - rw, y + k, right, st or "dim")


class Input:
    """A line of text being typed."""
    def __init__(self, text="", secret=False):
        self.text, self.pos, self.secret = text, len(text), secret

    def key(self, k: str) -> bool:
        t, p = self.text, self.pos
        if k.startswith("paste:"):
            add = " ".join(k[6:].split("\n")).strip()
            self.text, self.pos = t[:p] + add + t[p:], p + len(add)
        elif k == "space":
            self.text, self.pos = t[:p] + " " + t[p:], p + 1
        elif len(k) == 1:
            self.text, self.pos = t[:p] + k + t[p:], p + 1
        elif k == "backspace" and p:
            self.text, self.pos = t[:p - 1] + t[p:], p - 1
        elif k == "del":
            self.text = t[:p] + t[p + 1:]
        elif k == "left":
            self.pos = max(0, p - 1)
        elif k == "right":
            self.pos = min(len(t), p + 1)
        elif k in ("home", "c-a"):
            self.pos = 0
        elif k in ("end", "c-e"):
            self.pos = len(t)
        elif k == "c-u":
            self.text, self.pos = "", 0
        else:
            return False
        return True

    def draw(self, s: Screen, x, y, w, focus=True):
        shown = "*" * len(self.text) if self.secret else self.text
        start = max(0, self.pos - (w - 2))    # the end being typed stays in view
        s.fill(x, y, w, "")
        s.put(x, y, shown[start:], "", w - 1)
        if focus:
            cx = x + text_width(shown[start:self.pos])
            s.put(min(cx, x + w - 1), y, shown[self.pos] if self.pos < len(shown) else " ", "sel", 1)


# ---------- pop-ups ----------
class Modal:
    title, wide = "", 56

    def __init__(self, app):
        self.app = app

    def close(self):
        if self in self.app.modals:
            self.app.modals.remove(self)

    def box(self, s: Screen, lines: int) -> tuple[int, int, int, int]:
        """Draws the frame, centred; gives the inside as x, y, w, h."""
        w = max(20, min(self.wide, s.cols - 2))
        h = max(3, min(lines + 2, s.rows - 2))
        x, y = (s.cols - w) // 2, max(0, (s.rows - h) // 2)
        for k in range(h):
            s.fill(x, y + k, w, "")
            s.put(x, y + k, g("v"), "dim")
            s.put(x + w - 1, y + k, g("v"), "dim")
        s.put(x, y, g("tl") + g("h") * (w - 2) + g("tr"), "dim")
        s.put(x, y + h - 1, g("bl") + g("h") * (w - 2) + g("br"), "dim")
        s.put(x + 2, y, " " + clip(self.title, w - 6) + " ", "b")
        return x + 2, y + 1, w - 4, h - 2


class Menu(Modal):
    """A list to pick from. Enter runs the row; Esc closes."""
    def __init__(self, app, title, rows, note=""):
        super().__init__(app)
        self.title, self.rows, self.note = title, rows, note
        self.sel, self.top = move(rows, 0, 0), 0

    def key(self, k):
        page = 8
        d = {"up": -1, "k": -1, "down": 1, "j": 1, "pgup": -page, "pgdn": page, "home": -len(self.rows), "g": -len(self.rows), "end": len(self.rows),
             "G": len(self.rows)}.get(k)
        if d:
            self.sel = move(self.rows, self.sel, d)
        elif k == "enter" and self.rows:
            r = self.rows[self.sel]
            self.close()
            if r.get("run"):
                r["run"]()
        elif k in ("esc", "q"):
            self.close()

    def draw(self, s):
        extra = 2 if self.note else 0
        x, y, w, h = self.box(s, len(self.rows) + extra)
        if self.note:
            s.put(x, y, clip(self.note, w), "dim")
        h -= extra
        self.top = min(max(self.top, self.sel - h + 1), self.sel) if h > 0 else 0
        draw_rows(s, self.rows, self.sel, self.top, x, y + extra, w, h)


class Form(Modal):
    """Fields to fill in: {"key", "label", "value", "kind": text | secret | toggle | choice, "options"}.
    Up and Down move between them, Space or the arrows change a switch or a choice, Enter saves."""
    def __init__(self, app, title, fields, done, note="", button="Save"):
        super().__init__(app)
        self.title, self.fields, self.done, self.note, self.button = title, fields, done, note, button
        self.at, self.error = 0, ""
        for f in fields:
            f.setdefault("kind", "text")
            if f["kind"] in ("text", "secret"):
                f["input"] = Input(str(f.get("value") or ""), f["kind"] == "secret")

    def values(self) -> dict:
        return {f["key"]: f["input"].text if "input" in f else f["value"] for f in self.fields}

    def key(self, k):
        f = self.fields[self.at]
        if k == "esc":
            return self.close()
        if k == "enter":
            self.error = ""
            return self.done(self, self.values())
        if k in ("up", "btab"):
            self.at = (self.at - 1) % len(self.fields)
        elif k in ("down", "tab"):
            self.at = (self.at + 1) % len(self.fields)
        elif "input" in f:
            f["input"].key(k)
        elif f["kind"] == "toggle" and k in ("space", "left", "right"):
            f["value"] = not f["value"]
        elif f["kind"] == "choice" and k in ("space", "left", "right"):
            opts = [o[0] for o in f["options"]]
            i = opts.index(f["value"]) if f["value"] in opts else 0
            f["value"] = opts[(i + (-1 if k == "left" else 1)) % len(opts)]

    def fail(self, detail):
        """The server said no: the form stays open and says why."""
        self.error = str(detail)

    def draw(self, s):
        extra = (2 if self.note else 0)
        x, y, w, h = self.box(s, len(self.fields) * 2 + extra + 2)
        if self.note:
            s.put(x, y, clip(self.note, w), "dim")
        y += extra
        lw = min(w // 2, max(text_width(f["label"]) for f in self.fields) + 2)
        for i, f in enumerate(self.fields):
            yy = y + i * 2
            if yy >= s.rows - 3:
                break
            on = i == self.at
            s.put(x, yy, clip(f["label"], lw - 1), "b" if on else "dim")
            if "input" in f:
                f["input"].draw(s, x + lw, yy, w - lw, on)
            elif f["kind"] == "toggle":
                s.put(x + lw, yy, (g("on") + " on" if f["value"] else g("off") + " off"), "sel" if on else "")
            else:
                label = next((o[1] for o in f["options"] if o[0] == f["value"]), str(f["value"]))
                s.put(x + lw, yy, clip("< " + label + " >", w - lw), "sel" if on else "")
        foot = y + len(self.fields) * 2
        s.put(x, foot, clip(self.error or f"Enter: {self.button}   Esc: cancel", w), "red" if self.error else "dim")


class Text(Modal):
    """Lines to read (the keys, the recap's slides). With pages, Left and Right turn them."""
    wide = 64

    def __init__(self, app, title, pages):
        super().__init__(app)
        self.title, self.pages, self.at, self.top = title, pages, 0, 0

    def key(self, k):
        if k in ("right", "space", "enter", "l") and self.at < len(self.pages) - 1:
            self.at, self.top = self.at + 1, 0
        elif k in ("left", "h", "backspace") and self.at:
            self.at, self.top = self.at - 1, 0
        elif k in ("down", "j"):
            self.top += 1
        elif k in ("up", "k"):
            self.top = max(0, self.top - 1)
        elif k in ("esc", "q", "enter", "space", "?"):
            self.close()

    def draw(self, s):
        lines = self.pages[self.at]
        x, y, w, h = self.box(s, len(lines) + (2 if len(self.pages) > 1 else 0))
        body = h - (2 if len(self.pages) > 1 else 0)
        self.top = max(0, min(self.top, len(lines) - body))
        for k, line in enumerate(lines[self.top:self.top + body]):
            style, text = line if isinstance(line, tuple) else ("", line)
            s.put(x, y + k, clip(text, w), style)
        if len(self.pages) > 1:
            s.put(x, y + h - 1, clip(f"{self.at + 1} / {len(self.pages)}   Left, Right: turn   Esc: close", w), "dim")


# ---------- the views ----------
class View:
    """A tab's content, or a page opened from it: rows, one of them selected."""
    hints = "Enter add   N play next   P play now   L like   A to a playlist"

    def __init__(self, app):
        self.app, self.rows, self.sel, self.top, self.note = app, [], 0, 0, "Loading..."
        self.input, self.typing = None, False
        self.title = ""

    def shown(self):
        """The tab was picked, or the page came back on top: fetch what it shows."""

    def build(self):
        """Rows from what was fetched; called when the data or the player's state changed."""

    def set_rows(self, rows, note=""):
        self.rows, self.note = rows, note
        self.sel = move(rows, min(self.sel, max(0, len(rows) - 1)), 0) if rows else 0

    def row(self):
        return self.rows[self.sel] if self.rows and not self.rows[self.sel].get("head") else None

    def head_lines(self) -> int:
        return 0

    def draw_head(self, s, x, y, w):
        pass

    def key(self, k) -> bool:
        a, r = self.app, self.row()
        d = {"up": -1, "k": -1, "down": 1, "j": 1, "pgup": -(a.body_h - 1), "pgdn": a.body_h - 1, "home": -len(self.rows), "g": -len(self.rows),
             "end": len(self.rows), "G": len(self.rows)}.get(k)
        if d:
            self.sel = move(self.rows, self.sel, d)
        elif k == "r":
            self.shown()
        elif not r:
            return False
        elif k == "enter" and r.get("run"):
            r["run"]()
        elif r.get("track") and k in ("enter", "N", "P"):
            a.add([r["track"]], {"enter": "add", "N": "next", "P": "now"}[k])
        elif r.get("track") and k == "L":
            a.like(r["track"])
        elif r.get("track") and k == "A":
            a.to_playlist(r["track"])
        else:
            return False
        return True

    def draw(self, s, x, y, w, h):
        n = self.head_lines()
        self.draw_head(s, x, y, w)
        y, h = y + n, h - n
        if not self.rows:
            s.put(x + 2, y + 1, clip(self.note, w - 4), "dim")
            return
        self.top = max(0, min(max(self.top, self.sel - h + 1), self.sel, len(self.rows) - 1))
        if self.top and self.rows[self.top - 1].get("head") and self.sel - self.top < h - 1:
            self.top -= 1                     # the heading of the first row shown comes along
        if self.sel <= 1:
            self.top = 0
        cur = self.app.state.get("current") or {}
        draw_rows(s, self.rows, self.sel, self.top, x, y, w, h, cur.get("videoId"), focus=not self.typing)

    # ----- helpers the views share
    def track(self, t, right=None, **more):
        title = t["title"] + (" " + g("heart") if t["videoId"] in self.app.liked else "")
        return item(title, t.get("duration", "") if right is None else right, track=t, sub=t.get("artist", ""), **more)

    def card(self, it):
        """A thing from YouTube: a song is added, an album, playlist or artist opens."""
        if it.get("videoId"):
            return self.track(it)
        a = self.app
        return item(it.get("title") or "", it["type"], sub=it.get("subtitle", ""), run=lambda: a.push(Page(a, it["type"], it["id"])))

    def play_all(self, tracks, label):
        a = self.app
        return item(f"Play all {len(tracks)}{g('dots')}", run=lambda: a.menu(label, [
            item("Play now", run=lambda: a.add(tracks, "replace", label)), item("Play next", run=lambda: a.add(tracks, "next", label)),
            item("Add to the end of the queue", run=lambda: a.add(tracks, "add", label)),
            item("Shuffle and play", run=lambda: a.add(random.sample(tracks, len(tracks)), "replace", label))])) if tracks else None


class Home(View):
    hints = "Enter add or open   e Home/Explore   N next   P now   L like   A to a playlist"

    def __init__(self, app):
        super().__init__(app)
        self.mode, self.mine, self.shelves, self.ex = "home", None, None, None

    def shown(self):
        a = self.app
        if self.mode == "home":
            a.get("api/forme", self.got("mine"), key="forme")
            a.get("api/home", self.got("shelves"), key="home", fail=lambda d: self.got("shelves")([]))
        else:
            a.get("api/explore", self.got("ex"), key="explore")

    def got(self, name):
        def put(r):
            setattr(self, name, r)
            self.build()
        return put

    def build(self):
        rows = []
        if self.mode == "home":
            for sh in (self.mine or []) + (self.shelves or []):
                rows.append(head(sh["title"], sh.get("subtitle", "")))
                rows += [self.card(it) for it in sh["items"]]
            done = self.mine is not None and self.shelves is not None
        else:
            ex, a = self.ex or {}, self.app
            if ex.get("releases"):
                rows.append(head("New releases"))
                rows += [self.card(it) for it in ex["releases"]]
            for grp in ex.get("moods", []):
                rows.append(head(grp["title"]))
                rows += [item(m["title"], "mood", run=lambda m=m: a.push(Mood(a, m))) for m in grp["items"]]
            done = self.ex is not None
        self.set_rows(rows, "Nothing here yet. Press / to search." if done else "Loading...")

    def key(self, k):
        if k in ("e", "tab"):
            self.mode = "explore" if self.mode == "home" else "home"
            self.sel = self.top = 0
            self.build()
            self.shown()
            return True
        return super().key(k)


class Mood(View):
    def __init__(self, app, mood):
        super().__init__(app)
        self.mood, self.items = mood, None

    def shown(self):
        self.app.get("api/mood", self.got, params={"params": self.mood["params"]})

    def got(self, r):
        self.items = r
        self.set_rows([head(self.mood["title"])] + [self.card(it) for it in r], "Nothing in there")


class Page(View):
    """An album, a playlist or an artist from YouTube Music."""
    def __init__(self, app, kind, ident):
        super().__init__(app)
        self.kind, self.id, self.page = kind, ident, None

    def shown(self):
        if self.page is None:
            self.app.get(f"api/{self.kind}/{self.app.cli.urllib.parse.quote(self.id, safe='')}", self.got)

    def got(self, p):
        self.page = p
        self.build()

    def build(self):
        p = self.page
        if not p:
            return
        rows = [head(p.get("title") or "", p.get("subtitle") or self.kind), self.play_all(p["tracks"], p.get("title") or "")]
        rows += [self.track(t) for t in p["tracks"]]
        if p.get("albums"):
            rows += [head("Albums")] + [self.card(x) for x in p["albums"]]
        self.set_rows([r for r in rows if r], "Nothing in there")


class Search(View):
    hints = "Enter search / add   Tab songs, albums...   / type again   N next   P now"
    KINDS = ["songs", "albums", "artists", "playlists"]

    def __init__(self, app):
        super().__init__(app)
        self.input, self.typing, self.kind, self.note, self.asked = Input(), True, "songs", "Type what you want to hear, then Enter.", ""

    def head_lines(self):
        return 2

    def draw_head(self, s, x, y, w):
        s.put(x, y, "Search", "head")
        self.input.draw(s, x + 8, y, max(10, w - 8), self.typing)
        kx = x
        for kind in self.KINDS:
            kx = s.put(kx, y + 1, f" {kind} ", "tab" if kind == self.kind else "dim") + 1

    def go(self):
        q, a = self.input.text.strip(), self.app
        if not q:
            return
        self.asked, self.typing = q, False
        self.set_rows([], "Searching...")
        if a.cli.LINK.match(q) and a.on("links"):
            return a.get("api/resolve", self.resolved, params={"url": q}, key="search")
        a.get("api/search", self.found, params={"q": q, "kind": self.kind}, key="search", fail=self.failed)

    def failed(self, detail):
        self.set_rows([], str(detail))

    def found(self, r):
        self.sel = self.top = 0
        self.set_rows([self.card(it) for it in r], f'Nothing found for "{self.asked}"')

    def resolved(self, r):
        if r["type"] == "song":
            return self.set_rows([self.track(r["track"])])
        self.set_rows([], "")
        self.app.push(Page(self.app, r["type"], r["id"]))

    def key(self, k):
        if self.typing:
            if k == "enter":
                self.go()
            elif k == "esc" or k == "down" and self.rows:
                self.typing = False           # out of the box: the keys are the app's again
            elif k == "tab":
                self.kind = self.KINDS[(self.KINDS.index(self.kind) + 1) % 4]
            else:
                self.input.key(k)
            return True
        if k in ("/", "i") or (k == "up" and self.sel == move(self.rows, 0, 0)):
            self.typing = True
        elif k == "tab":
            self.kind = self.KINDS[(self.KINDS.index(self.kind) + 1) % 4]
            self.go()
        else:
            return super().key(k)
        return True


class Queue(View):
    hints = "Enter play   d remove   t play next   J K move   S shuffle   C clear   r new radio   R clear radio   s save"

    def shown(self):
        self.build()

    def build(self):
        st, a = self.app.state, self.app
        q, nu = st.get("queue") or [], st.get("userCount", 0)
        if not q:
            return self.set_rows([], "The queue is empty. Press / to search for something to play.")
        rows = [head("Now playing"), self.track(q[0], self.who(q[0]), at=0)]
        rows.append(head("Next in queue", a.cli.plural(nu, "song") if nu else "nothing: songs you add come here"))
        rows += [self.track(t, self.who(t), at=i) for i, t in enumerate(q[1:nu + 1], 1)]
        if len(q) > nu + 1:
            seed = st.get("seed")
            rows.append(head("Radio" + (f" of {seed['title']}" if seed else "")))
            rows += [self.track(t, t.get("duration", ""), at=i, mark=False) for i, t in enumerate(q[nu + 1:], nu + 1)]
        self.set_rows(rows)

    def who(self, t):
        name = self.app.name_of(t.get("by")) if t.get("src") == "user" else ""
        return (name + "  " if name else "") + t.get("duration", "")

    def key(self, k):
        a, r = self.app, self.row()
        if k in ("S", "C", "R"):
            a.control({"S": "shuffle", "C": "clear", "R": "clear_auto"}[k])
        elif k == "r":
            a.control("refresh")
        elif k == "s" and a.on("playlists"):
            a.ask("Save the queue as a playlist", [{"key": "name", "label": "Name", "value": ""}],
                  lambda f, v: a.send("POST", "api/lists", {"name": v["name"], "fromQueue": True}, lambda p: (f.close(), a.say(f'Saved "{p["name"]}"')), fail=f.fail))
        elif not r or not r.get("at") and k in ("enter", "d", "del", "t", "J", "K"):
            return k in ("enter", "d", "del", "t", "J", "K") or super().key(k)
        elif k in ("enter", "d", "del", "t", "J", "K"):
            at, off, vid = r["at"], a.state.get("offset", 0), r["track"]["videoId"]
            if k in ("J", "K"):
                to = at + (1 if k == "J" else -1)
                if 1 <= to < len(a.state["queue"]):
                    a.control("move", value=off + at, videoId=vid, to=off + to)
                    self.sel = move(self.rows, self.sel, 1 if k == "J" else -1)
            else:
                a.control({"enter": "jump", "d": "remove", "del": "remove", "t": "promote"}[k], value=off + at, videoId=vid)
        else:
            return super().key(k)
        return True


class Lists(View):
    hints = "Enter open"

    def shown(self):
        self.app.get("api/lists", self.got, key="lists")

    def got(self, ls):
        a = self.app
        rows = [item(f"New playlist{g('dots')}", run=self.new)] if a.on("playlists") else []
        for p in ls:
            owner = a.name_of(p.get("owner"))
            rows.append(item(p["name"], a.cli.plural(p["count"], "song") + (f" {g('dot')} {owner}'s" if owner else ""), run=lambda p=p: a.push(ListPage(a, p["id"]))))
        self.set_rows(rows, "No playlists yet")

    def new(self):
        a = self.app
        a.ask("New playlist", [{"key": "name", "label": "Name", "value": ""}],
              lambda f, v: a.send("POST", "api/lists", {"name": v["name"]}, lambda p: (f.close(), self.shown()), fail=f.fail), button="Create")


class ListPage(View):
    """One of the house's playlists, or Liked songs."""
    hints = "Enter add   d take out   J K move   e rename   D delete the playlist   N next   P now"

    def __init__(self, app, ident):
        super().__init__(app)
        self.id, self.list = ident, None

    def shown(self):
        self.app.get(f"api/lists/{self.id}", self.got, key="list")

    def got(self, p):
        self.list = p
        self.build()

    def build(self):
        p, a = self.list, self.app
        if not p:
            return
        owner = a.name_of(p.get("owner"))
        rows = [head(p["name"], a.cli.plural(len(p["tracks"]), "song") + (f" {g('dot')} {owner}'s" if owner else "")), self.play_all(p["tracks"], p["name"])]
        for i, t in enumerate(p["tracks"]):
            by = ", ".join(filter(None, (a.name_of(x) for x in t.get("likedBy") or [])))
            rows.append(self.track(t, (by + "  " if by else "") + t.get("duration", ""), at=i))
        self.set_rows([r for r in rows if r], "Empty. Press A on any song to add it here.")

    def key(self, k):
        a, r, p = self.app, self.row(), self.list
        if not p:
            return super().key(k)
        if k == "e" and self.id != "liked":
            a.ask("Rename the playlist", [{"key": "name", "label": "Name", "value": p["name"]}],
                  lambda f, v: a.send("PATCH", f"api/lists/{self.id}", {"name": v["name"]}, lambda q: (f.close(), self.got(q)), fail=f.fail))
        elif k == "D" and self.id != "liked":
            a.confirm(f'Delete "{p["name"]}"?', lambda: a.send("DELETE", f"api/lists/{self.id}", None, lambda _: (a.say("Deleted"), a.pop())))
        elif r and "at" in r and k in ("d", "del", "J", "K"):
            body = {"videoId": r["track"]["videoId"], "at": r["at"], "op": "remove" if k in ("d", "del") else "move"}
            if body["op"] == "move":
                body["to"] = r["at"] + (1 if k == "J" else -1)
                if not 0 <= body["to"] < len(p["tracks"]):
                    return True
                self.sel = move(self.rows, self.sel, 1 if k == "J" else -1)
            a.send("PATCH", f"api/lists/{self.id}/tracks", body, self.got)
        else:
            return super().key(k)
        return True


class History(View):
    hints = "Enter add   N next   P now   L like   A to a playlist   C clear (the admin)"

    def shown(self):
        self.app.get("api/history", self.got, params={"limit": 200}, key="history")

    def got(self, h):
        a = self.app
        self.set_rows([self.track(t, " ".join(filter(None, [a.name_of(t.get("by")), time.strftime("%d %b %H:%M", time.localtime(t["playedAt"])) if t.get("playedAt") else ""])))
                       for t in h], "Nothing played yet")

    def key(self, k):
        a = self.app
        if k == "C":
            a.confirm("Clear the history for everyone?", lambda: a.send("DELETE", "api/history", None, lambda _: (a.say("History cleared"), self.shown())))
            return True
        return super().key(k)


class Local(View):
    hints = "Enter add   u upload a file   e edit   d remove   N next   P now   L like   A to a playlist"

    def __init__(self, app):
        super().__init__(app)
        self.info = None

    def shown(self):
        self.app.get("api/local", self.got, key="local")

    def got(self, r):
        a, self.info = self.app, r
        rows = [head("Local songs", f"{a.cli.plural(len(r['songs']), 'song')} {g('dot')} {a.cli.size(r['used'])} {g('dot')} room for {a.cli.size(r['room'])}"),
                item(f"Upload a file{g('dots')}", run=self.upload)]
        rows += [self.track(t, " ".join(filter(None, [a.name_of(t.get("by")), t.get("duration", "")])), mine=t.get("mine")) for t in r["songs"]]
        self.set_rows(rows)

    def upload(self):
        a = self.app
        a.ask("Upload a song", [{"key": "path", "label": "File", "value": ""}], self.send_file, button="Upload",
              note=f"The file's path on this computer. Up to {self.info['maxMB']} MB.")

    def send_file(self, form, v):
        a, path = self.app, Path(v["path"].strip().strip('"')).expanduser()
        if not path.is_file():
            return form.fail("No such file")
        n = path.stat().st_size
        if n > self.info["maxMB"] * 2**20 or n > self.info["room"]:
            return form.fail(f"Too big: a file can be {self.info['maxMB']} MB at most" if n > self.info["maxMB"] * 2**20 else "There is no room left for local songs")
        form.close()
        a.say(f"Uploading {path.name}{g('dots')}", 600)
        a.send("POST", "api/local/upload", None, lambda s: (a.say(f'Added "{s["title"]}"'), self.shown()), params={"name": path.name},
               data=lambda: a.cli.Sending(path, True), timeout=900)

    def key(self, k):
        a, r = self.app, self.row()
        if k == "u":
            self.upload()
        elif k in ("e", "d", "del") and r and r.get("track"):
            t = r["track"]
            sid = t["videoId"][6:]
            if not r.get("mine"):
                a.say("Only whoever uploaded it, or the admin, can change it")
            elif k == "e":
                a.ask("Edit the song", [{"key": k2, "label": k2.capitalize(), "value": t.get(k2, "")} for k2 in ("title", "artist", "album")],
                      lambda f, v: a.send("PATCH", f"api/local/{sid}", v, lambda _: (f.close(), a.say("Saved"), self.shown()), fail=f.fail))
            else:
                a.confirm(f'Remove "{t["title"]}"? The file is deleted, and the song leaves every playlist.',
                          lambda: a.send("DELETE", f"api/local/{sid}", None, lambda _: (a.say("Removed"), self.shown())))
        else:
            return super().key(k)
        return True


class Stats(View):
    hints = "Tab period   o whose   c recap   Enter add the song"
    SPANS = [(7, "7 days"), (30, "30 days"), (365, "A year"), (0, "All time")]

    def __init__(self, app):
        super().__init__(app)
        self.span, self.who, self.whose, self.st = 1, "", "The house", None

    def shown(self):
        days = self.SPANS[self.span][0]
        self.app.get("api/stats", self.got, params={"since": time.time() - days * 86400 if days else 0, "who": self.who}, key="stats")

    def got(self, st):
        self.st = st
        self.build()

    def bar(self, n, most, width=24):
        return g("block") * max(1 if n else 0, round(width * n / most)) if most else ""

    def build(self):
        st, a = self.st, self.app
        if not st:
            return
        P = a.cli.plural
        rows = [head(f"{self.SPANS[self.span][1]} {g('dot')} {self.whose}", f"{P(st['plays'], 'play')} {g('dot')} {st['minutes']} min"),
                item(f"{P(st['songs'], 'song')} by {P(st['artists'], 'artist')}, {st['newSongs']} new, {st['radioShare']}% from the radio, best streak {P(st['streak'], 'day')}")]
        if st["topSongs"]:
            rows += [head("Top songs")] + [self.track(t, f"x{t['plays']}  {t['minutes']} min") for t in st["topSongs"]]
        if st["topArtists"]:
            most = st["topArtists"][0]["plays"]
            rows += [head("Top artists")] + [item(x["name"], f"{self.bar(x['plays'], most, 16)} x{x['plays']}") for x in st["topArtists"]]
        if any(st["hours"]):
            lv, most = g("levels"), max(st["hours"])
            rows += [head("Hours of the day", "0h to 23h"), item("".join(lv[round((len(lv) - 1) * h / most)] if h else lv[0] for h in st["hours"]) + f"   busiest at {st['hours'].index(most)}h")]
            most = max(st["weekdays"])
            rows += [head("Days of the week")] + [item(d, f"{self.bar(m, most)} {m} min") for d, m in zip(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), st["weekdays"])]
        if st.get("people"):
            most = st["people"][0]["minutes"]
            rows += [head("Who played the most")] + [item(a.name_of(p["id"]), f"{self.bar(p['minutes'], most)} {p['minutes']} min") for p in st["people"]]
        self.set_rows(rows, "Nothing was played in this time.")

    def pick_who(self):
        a = self.app

        def use(who, name):
            self.who, self.whose = who, name
            self.shown()
        rows = [item("The house", run=lambda: use("", "The house"))]
        if a.on("people"):
            rows += [item(p["name"], run=lambda p=p: use(p["id"], p["name"])) for p in a.people]
        if a.on("groups"):
            rows += [item(s["name"], a.house["groups"]["one"], run=lambda s=s: use("sem:" + s["id"], s["name"])) for s in a.groups]
        a.menu("Whose stats?", rows)

    def recap(self):
        st, a = self.st, self.app
        if not st or not st["plays"]:
            return a.say("Nothing to tell yet")
        pages = [[("head", f"{self.whose}, {self.SPANS[self.span][1].lower()}"), "", ("b", f"{st['minutes']} minutes of music"), f"{st['plays']} plays on {a.cli.plural(st['days'], 'day')}"]]
        if st["topSongs"]:
            t = st["topSongs"][0]
            pages.append([("head", "The song"), "", ("b", t["title"]), t["artist"], "", f"played {a.cli.plural(t['plays'], 'time')}"]
                         + [""] + [f"{i}. {x['title']} - {x['artist']}" for i, x in enumerate(st["topSongs"][1:5], 2)])
        if st["topArtists"]:
            x = st["topArtists"][0]
            pages.append([("head", "The artist"), "", ("b", x["name"]), f"{x['minutes']} minutes", ""] + [f"{i}. {y['name']}" for i, y in enumerate(st["topArtists"][1:5], 2)])
        if st["busiestDay"]:
            pages.append([("head", "The day"), "", ("b", st["busiestDay"]["date"]), f"{st['busiestDay']['minutes']} minutes in one day", "",
                          f"Longest streak: {a.cli.plural(st['streak'], 'day')} in a row", f"{st['newSongs']} songs heard for the first time"])
        if st.get("people"):
            pages.append([("head", "Who played the most"), ""] + [f"{i}. {a.name_of(p['id'])}  {p['minutes']} min" for i, p in enumerate(st["people"][:8], 1)])
        a.modals.append(Text(a, "Recap", pages))

    def key(self, k):
        if k == "tab":
            self.span = (self.span + 1) % len(self.SPANS)
            self.shown()
        elif k == "o":
            self.pick_who()
        elif k == "c" and self.app.on("recap"):
            self.recap()
        else:
            return super().key(k)
        return True


class Lyrics(View):
    hints = "j k scroll (lyrics without times)   r fetch again"

    def __init__(self, app):
        super().__init__(app)
        self.vid, self.ly = None, None

    def shown(self):
        self.vid = None
        self.build()

    def build(self):
        t = self.app.state.get("current")
        if not t:
            self.vid, self.ly = None, None
        elif t["videoId"] != self.vid:
            self.vid, self.ly, self.top = t["videoId"], None, 0
            self.app.get("api/lyrics", self.got, key="lyrics", fail=lambda d: self.got({"none": True}),
                         params={"videoId": t["videoId"], "title": t["title"], "artist": t["artist"], "album": t.get("album", ""), "duration": t.get("duration", "")})

    def got(self, ly):
        self.ly = ly

    def key(self, k):
        if k in ("j", "down"):
            self.top += 1
        elif k in ("k", "up"):
            self.top = max(0, self.top - 1)
        elif k == "r":
            self.shown()
        else:
            return False
        return True

    def draw(self, s, x, y, w, h):
        t, ly = self.app.state.get("current"), self.ly
        if not t:
            return s.put(x + 2, y + 1, "Nothing is playing", "dim")
        s.put(x, y, clip(f"{t['title']} - {t['artist']}", w), "head")
        y, h = y + 2, h - 2
        if ly is None:
            return s.put(x + 2, y, "Looking for the lyrics...", "dim")
        if ly.get("synced"):
            lines, pos = ly["synced"], self.app.position() + 0.3
            now = max((i for i, ln in enumerate(lines) if ln[0] <= pos), default=-1)
            first = max(0, min(now - h // 2, len(lines) - h))
            for k, ln in enumerate(lines[first:first + h]):
                i = first + k
                s.put(x + 2, y + k, clip(ln[1], w - 4), "b" if i == now else "dim" if i < now else "")
            return
        text = "(instrumental)" if ly.get("instrumental") else ly.get("plain") or "No lyrics for this song."
        lines = text.split("\n")
        self.top = max(0, min(self.top, len(lines) - h))
        for k, ln in enumerate(lines[self.top:self.top + h]):
            s.put(x + 2, y + k, clip(ln, w - 4))


class Settings(View):
    hints = "Enter change"

    def __init__(self, app):
        super().__init__(app)
        self.st, self.net = None, {}

    def shown(self):
        self.app.get("api/settings", self.got, key="settings")
        self.app.get("api/network", self.got_net, key="network", fail=lambda _: None)   # a Tunebox from before api/network

    def got(self, st):
        self.st = st
        self.build()

    def got_net(self, net):
        self.net = net
        self.build()

    def build(self):
        st, a = self.st, self.app
        if not st:
            return
        onoff = lambda v: "on" if v else "off"   # noqa: E731
        opt = lambda key: lambda: a.send("POST", "api/options", {key: not st[key]}, self.got)   # noqa: E731
        rows = [head("Sound"), item("Volume", f"{a.state.get('volume', st['volume'])}   (+ and - anywhere)")]
        if a.on("eq"):
            lv = g("levels")
            bars = "".join(lv[round((b + 12) / 24 * (len(lv) - 1))] for b in st["bands"])
            rows += [item("Equaliser", f"{bars}  {st['eq']['preset']}", run=self.eq)]
        rows += [item("Same loudness for every song", onoff(st["normalize"]), run=opt("normalize")), item("Quality", st["quality"], run=self.quality),
                 head("Playing"), item("Radio when the queue ends", onoff(st["autoplay"]), run=opt("autoplay")),
                 item("Songs from different people take turns", onoff(st["turns"]), run=opt("turns"))]
        if a.on("sleep"):
            sl = a.state.get("sleep")
            rows.append(item("Sleep timer", "off" if not sl else "after this song" if sl["mode"] == "track" else a.cli.clock(sl["left"]) + " left", run=self.sleep))
        if a.on("alarm"):
            al = st["alarm"]
            rows.append(item("Wake-up alarm", f"{al['time']} on {', '.join(a.cli.DAYS[d] for d in al['days'])}" if al["enabled"] else "off", run=self.alarm))
        me = a.me()
        if a.on("people") and a.on("namelist"):
            rows += [head("You"), item("Who's listening", me["name"] if me else "nobody yet", run=a.pick_name)]
        net = self.net
        rows += [head("The house"), item("YouTube Music account", "signed in" if st["account"]["signedIn"] else "not signed in", run=self.account),
                 item(f"Save a backup{g('dots')}", run=lambda: self.backup(False)), item(f"Restore a backup{g('dots')}", run=self.restore),
                 item("Server address", net.get("ip") or "unknown"), item("Wi-Fi", net["wifi"]) if net.get("wifi") else None]
        self.set_rows([r for r in rows if r])

    def eq(self):
        a, st = self.app, self.st
        rows = [item(name, "now" if name == st["eq"]["preset"] else "", run=lambda n=name: a.send("POST", "api/eq", {"preset": n}, self.got)) for name in st["presets"]]
        rows.append(item(f"Custom{g('dots')}", "now" if st["eq"]["preset"] == "custom" else "", run=lambda: a.modals.append(EqEdit(a, st, self.got))))
        a.menu("Equaliser", rows)

    def quality(self):
        a = self.app
        a.menu("Quality", [item(q, "now" if q == self.st["quality"] else "", run=lambda q=q: a.send("POST", "api/options", {"quality": q}, self.got)) for q in self.st["qualities"]])

    def sleep(self):
        a = self.app
        done = lambda _: (a.poll(), self.build())   # noqa: E731
        rows = [item("Off", run=lambda: a.send("POST", "api/sleep", {"minutes": 0}, done))]
        rows += [item(f"{m} minutes", run=lambda m=m: a.send("POST", "api/sleep", {"minutes": m}, done)) for m in (15, 30, 45, 60, 90)]
        rows.append(item("After this song", run=lambda: a.send("POST", "api/sleep", {"track": True}, done)))
        a.menu("Sleep timer", rows)

    def alarm(self):
        a, al = self.app, self.st["alarm"]
        lists = [(None, "The radio")] + [(p["id"], p["name"]) for p in self.st["lists"]]
        fields = [{"key": "enabled", "label": "On", "kind": "toggle", "value": al["enabled"]}, {"key": "time", "label": "Time (HH:MM)", "value": al["time"]},
                  {"key": "days", "label": "Days", "value": ",".join(a.cli.DAYS[d] for d in al["days"])},
                  {"key": "list", "label": "Plays", "kind": "choice", "options": lists, "value": al["list"]},
                  {"key": "level", "label": "Volume it reaches", "value": al["level"]}, {"key": "ramp", "label": "Minutes to get there", "value": al["ramp"]}]

        def save(f, v):
            try:
                body = {**v, "time": v["time"].strip().zfill(5), "days": a.cli.days_of(v["days"]) if v["days"].strip() else [], "level": int(v["level"]), "ramp": float(v["ramp"])}
            except (ValueError, a.cli.Usage) as exc:
                return f.fail(exc if isinstance(exc, a.cli.Usage) else "Volume and minutes are numbers")
            a.send("POST", "api/alarm", body, lambda r: (f.close(), self.got(r)), fail=f.fail)
        a.ask("Wake-up alarm", fields, save, note=f"Days: mon,wed or mon-fri. It rings in {al.get('tz') or 'the server own'} time.")

    def account(self):
        a = self.app
        if self.st["account"]["signedIn"]:
            return a.confirm("Sign out of YouTube Music?", lambda: a.send("DELETE", "api/account", None, lambda _: self.shown()))

        def send(f, v):
            try:
                text = Path(v["path"].strip().strip('"')).expanduser().read_text(encoding="utf-8")
            except OSError:
                return f.fail("No such file")
            a.send("POST", "api/account", {"headers": text}, lambda _: (f.close(), a.say("Signed in"), self.shown()), fail=f.fail)
        a.ask("Sign in to YouTube Music", [{"key": "path", "label": "File", "value": ""}], send, button="Sign in",
              note="A file with the request headers copied from music.youtube.com.")

    def backup(self, full):
        a = self.app
        name = time.strftime("tunebox-full-%Y-%m-%d.zip" if full else "tunebox-backup-%Y-%m-%d.json")
        a.ask("Save a full backup" if full else "Save a backup", [{"key": "path", "label": "File", "value": name}],
              lambda f, v: (f.close(), a.send("GET", "api/backup/full" if full else "api/backup", None,
                                              lambda r: a.say(f"Saved {r['file']} ({a.cli.size(r['bytes']) if r['bytes'] >= 2**20 else str(r['bytes'] // 1024) + ' KB'})"),
                                              save=str(Path(v["path"].strip().strip('"')).expanduser()), timeout=600)),
              note="With the local songs' audio, as a zip." if full else "Pass phrases are in it only while the admin is unlocked.")

    def restore(self):
        a = self.app

        def go(f, v):
            import json
            try:
                backup = json.loads(Path(v["path"].strip().strip('"')).expanduser().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return f.fail("That isn't a backup file")
            f.close()
            a.confirm("Replace everything here with what is in that file?", lambda: a.send(
                "POST", "api/restore", {"backup": backup}, lambda r: (a.say("Restored"), a.reload()), timeout=300))
        a.ask("Restore a backup", [{"key": "path", "label": "File", "value": ""}], go, button="Restore", note="Needs the admin password.")


class EqEdit(Modal):
    """The custom curve: Left and Right pick a band, Up and Down change it."""
    title = "Custom equaliser"

    def __init__(self, app, st, done):
        super().__init__(app)
        self.freqs, self.done, self.at = st["freqs"], done, 0
        self.gains = list(st["eq"].get("custom") or st["bands"])

    def key(self, k):
        if k in ("left", "h"):
            self.at = (self.at - 1) % len(self.gains)
        elif k in ("right", "l"):
            self.at = (self.at + 1) % len(self.gains)
        elif k in ("up", "k", "down", "j"):
            self.gains[self.at] = max(-12, min(12, self.gains[self.at] + (1 if k in ("up", "k") else -1)))
        elif k == "0":
            self.gains[self.at] = 0
        elif k == "enter":
            self.close()
            self.app.send("POST", "api/eq", {"preset": "custom", "custom": self.gains}, self.done)
        elif k == "esc":
            self.close()

    def draw(self, s):
        x, y, w, h = self.box(s, 12)
        lv = g("levels")
        step = max(3, min(5, w // max(1, len(self.gains))))         # a narrow window squeezes the bands together
        for i, (f, gain) in enumerate(zip(self.freqs, self.gains)):
            cx = x + i * step
            on = i == self.at
            for row in range(7):              # seven rows of bar: +12 at the top, -12 at the bottom
                level = (gain + 12) / 24 * 7 - (6 - row)
                s.put(cx + (step > 4), y + row, (g("block") if level >= 1 else lv[max(0, round(level * (len(lv) - 1)))] if level > 0 else g("dot")) * 2, "yel" if on else "")
            s.put(cx, y + 7, f"{gain:+g}".center(step - 1), "sel" if on else "")
            s.put(cx, y + 8, (str(f) if f < 1000 else f"{f // 1000}k").center(step - 1), "dim")
        s.put(x, y + 10, clip("Left, Right: band   Up, Down: gain   0: flat   Enter: save", w), "dim")


# ----- the admin's tabs
FEATURES = {"people": "Names", "groups": "Groups", "playlists": "Playlists", "likes": "Likes", "browse": "Home and Explore", "links": "Pasting links",
            "local": "Local songs", "radio": "Radio", "lyrics": "Lyrics", "stats": "Stats", "recap": "Recap", "wall": "Wall screen", "alarm": "Wake-up alarm",
            "sleep": "Sleep timer", "eq": "Equaliser", "namelist": "Names in Settings", "look": "Theme and accent"}


class Admin(View):
    hints = "Tab next part   Enter change"
    PARTS = ["People", "Features", "House", "Local songs", "Security"]

    def __init__(self, app):
        super().__init__(app)
        self.part, self.d = 0, {}

    def head_lines(self):
        return 2

    def draw_head(self, s, x, y, w):
        kx = x
        for i, name in enumerate(self.PARTS):
            kx = s.put(kx, y, f" {name} ", "tab" if i == self.part else "dim") + 1

    def shown(self):
        a, part = self.app, self.PARTS[self.part]
        want = {"People": ["api/admin/people"], "Features": ["api/admin/house"], "House": ["api/admin/house", "api/seminars", "api/admin/blocks"],
                "Local songs": ["api/admin/local/disk"], "Security": ["api/admin/audit"]}[part]
        for path in want:
            a.get(path, lambda r, path=path: (self.d.__setitem__(path, r), self.build()), key="admin:" + path, fail=self.denied)

    def denied(self, detail):
        self.set_rows([], str(detail))

    def save(self, method, path, body, say="Saved", form=None):
        a = self.app

        def done(r):
            if form:
                form.close()
            if isinstance(r, dict) and r.get("rev"):
                a.house = r
            a.say(r.get("message") or say if isinstance(r, dict) else say)
            a.reload()
            self.shown()
        a.send(method, path, body, done, fail=form.fail if form else None)

    def build(self):
        part = self.PARTS[self.part]
        rows = getattr(self, "rows_" + part.split()[0].lower())()
        if rows is not None:
            self.set_rows(rows, "Nothing here")

    # --- People
    def rows_people(self):
        ps, a = self.d.get("api/admin/people"), self.app
        if ps is None:
            return None
        rows = [item(f"Add a name{g('dots')}", run=lambda: self.person(None))]
        for p in ps:
            bits = [a.cli.plural(p["plays"], "play"), f"{p['minutes']} min"] + (["pass phrase"] if p["locked"] else []) + (["can't add"] if p.get("noAdd") else []) \
                + ([f"at most {p['cap']} waiting"] if p.get("cap") else [])
            rows.append(item(p["name"], f" {g('dot')} ".join(bits), run=lambda p=p: self.person_menu(p)))
        return rows

    def person_menu(self, p):
        a = self.app
        pid, others = p["id"], [q for q in self.d["api/admin/people"] if q["id"] != p["id"]]
        gone = lambda mode: lambda: a.confirm(   # noqa: E731
            f"Remove {p['name']}" + (", with their plays, likes and playlists?" if mode == "purge" else "? Their plays and likes stay, without a name."),
            lambda: self.save("DELETE", f"api/admin/people/{pid}?mode={mode}", None, f"Removed {p['name']}"))
        rows = [item(f"Edit{g('dots')}", run=lambda: self.person(p)),
                item("Sign every device out of it", run=lambda: self.save("POST", f"api/admin/people/{pid}/signout", {}, "Signed out")) if p["locked"] else None,
                item(f"Merge into{g('dots')}", run=lambda: a.menu(f"Merge {p['name']} into", [item(q["name"], run=lambda q=q: a.confirm(
                    f"Merge {p['name']} into {q['name']}? {p['name']} goes away.",
                    lambda: self.save("POST", "api/admin/people/merge", {"source": pid, "into": q["id"]}, "Merged"))) for q in others])) if others else None,
                item("Remove (their plays stay)", run=gone("keep")), item("Remove with everything of theirs", run=gone("purge"))]
        a.menu(p["name"], [r for r in rows if r], note=f"{p['plays']} plays, {p['likes']} likes, {p['lists']} playlists")

    def person(self, p):
        a = self.app
        names = {s["id"]: s["name"] for s in a.groups}
        fields = [{"key": "name", "label": "Name", "value": p["name"] if p else ""},
                  {"key": "seminars", "label": a.house["groups"]["many"], "value": ", ".join(names.get(s, s) for s in (p or {}).get("seminars", []))},
                  {"key": "cap", "label": "Songs waiting at most", "value": (p or {}).get("cap", 0)},
                  {"key": "noAdd", "label": "Can't add songs", "kind": "toggle", "value": bool((p or {}).get("noAdd"))},
                  {"key": "phrase", "label": "New pass phrase", "kind": "secret", "value": ""}]

        def save(f, v):
            try:
                body = {"name": v["name"], "seminars": [x.strip() for x in v["seminars"].split(",") if x.strip()], "cap": int(v["cap"] or 0), "noAdd": v["noAdd"]}
            except ValueError:
                return f.fail("The limit is a number (0: none)")
            if v["phrase"]:
                body["phrase"] = "" if v["phrase"] == "-" else v["phrase"]
            self.save("PATCH" if p else "POST", f"api/admin/people/{p['id']}" if p else "api/admin/people", body, "Saved", f)
        a.ask(p["name"] if p else "Add a name", fields, save, note="0 waiting: no limit. Pass phrase: empty leaves it, - takes it off.")

    # --- Features
    def rows_features(self):
        h, a = self.d.get("api/admin/house"), self.app
        if h is None:
            return None
        off = set(a.house["off"])
        rows = [item(f"Set them all from a preset{g('dots')}", run=lambda: a.menu("Preset", [
            item(n.capitalize(), ", ".join(x) and "without " + ", ".join(x) or "everything", run=lambda n=n: self.save("POST", "api/admin/features/preset", {"name": n}, f"{n.capitalize()} preset"))
            for n, x in h["presets"].items()])), head("Features", f"{len(off)} off" if off else "all on")]
        for k in h["features"]:
            label = a.house["groups"]["many"] if k == "groups" else FEATURES.get(k, k)
            rows.append(item(label, "off" if k in off else "on", style="dim" if k in off else "",
                             run=lambda k=k: self.save("PATCH", "api/admin/features", {"features": {k: k in off}}, f"{FEATURES.get(k, k)} {'on' if k in off else 'off'}")))
        return rows

    # --- House
    def rows_house(self):
        d, a = self.d, self.app
        h, groups, blocks = d.get("api/admin/house"), d.get("api/seminars"), d.get("api/admin/blocks")
        if h is None or groups is None or blocks is None:
            return None
        h, gr = a.house, a.house["groups"]
        onoff = lambda v: "on" if v else "off"   # noqa: E731
        patch = lambda body: lambda: self.save("PATCH", "api/admin/house", body)   # noqa: E731

        def text(title, key, value, wrap=lambda v: v):
            return lambda: a.ask(title, [{"key": "v", "label": title, "value": value}], lambda f, v: self.save("PATCH", "api/admin/house", wrap(v["v"]) if callable(wrap) else wrap, "Saved", f))
        rows = [head("Name and look"), item("The house's name", h["name"], run=text("Name", "name", h["name"], lambda v: {"name": v})),
                item("Accent", h["accent"] or "each device's own", run=lambda: a.menu("Accent", [
                    item(x or "Each device's own", run=patch({"accent": x})) for x in d["api/admin/house"]["accents"]])),
                item("Time zone", h["tz"] or "the server's own", run=text("Time zone", "tz", h["tz"], lambda v: {"tz": v.strip()})),
                item("Wi-Fi name in Settings", h.get("network") or "detected", run=text("Wi-Fi name (empty: detected)", "network", h.get("network", ""), lambda v: {"network": v})),
                head("Names"), item("Anyone can add a name", onoff(h["signups"] == "open"), run=patch({"signups": "closed" if h["signups"] == "open" else "open"})),
                head(gr["many"]), item("What one is called", gr["one"], run=text("One of them", "one", gr["one"], lambda v: {"groups": {"one": v}})),
                item("What many are called", gr["many"], run=text("Many of them", "many", gr["many"], lambda v: {"groups": {"many": v}})),
                item("Everyone is in one", onoff(gr["required"]), run=patch({"groups": {"required": not gr["required"]}})),
                item("Anyone can add a new one", onoff(gr["create"] == "open"), run=patch({"groups": {"create": "admin" if gr["create"] == "open" else "open"}}))]
        for x in groups:
            rows.append(item("  " + x["name"], "rename or remove", run=lambda x=x: a.menu(x["name"], [
                item(f"Rename{g('dots')}", run=lambda: a.ask("Rename", [{"key": "v", "label": "Name", "value": x["name"]}],
                                                              lambda f, v: self.save("PATCH", f"api/admin/groups/{x['id']}", {"name": v["v"]}, "Renamed", f))),
                item("Remove (its people stay)", run=lambda: self.save("DELETE", f"api/admin/groups/{x['id']}", None, f"Removed {x['name']}"))])))
        rows.append(item(f"  Add one{g('dots')}", run=lambda: a.ask("Add", [{"key": "v", "label": "Name", "value": ""}],
                                                                   lambda f, v: self.save("POST", "api/admin/groups", {"name": v["v"]}, "Added", f), button="Add")))
        rows.append(head("Wall screen"))
        for k, label in (("lyrics", "Lyrics"), ("queue", "Up next"), ("who", "Who added it"), ("clock", "Clock"), ("controls", "Buttons")):
            rows.append(item(label, onoff(h["wall"][k]), run=patch({"wall": {k: not h["wall"][k]}})))
        rows.append(head("Blocked", str(len(blocks["songs"]) + len(blocks["artists"]))))
        rows.append(item(f"Block an artist{g('dots')}", run=lambda: a.ask("Block an artist", [{"key": "v", "label": "Name", "value": ""}],
                                                                        lambda f, v: self.save("POST", "api/admin/blocks", {"kind": "artist", "name": v["v"]}, "Blocked", f), button="Block")))
        unblock = lambda kind, key, name: lambda: a.confirm(f"Unblock {name}?", lambda: self.save(   # noqa: E731
            "DELETE", f"api/admin/blocks/{kind}/{a.cli.urllib.parse.quote(key, safe='')}", None, f"Unblocked {name}"))
        rows += [item(x["name"], "artist", run=unblock("artists", x["key"], x["name"])) for x in blocks["artists"]]
        rows += [item(x["title"], x["artist"], run=unblock("songs", x["id"], x["title"])) for x in blocks["songs"]]
        return rows

    # --- Local songs
    def rows_local(self):
        d, a = self.d.get("api/admin/local/disk"), self.app
        if d is None:
            return None
        size, enc = a.cli.size, d["encoders"]
        other = d["total"] - d["free"] - d["used"]
        bar = (g("block") * round(20 * (other + d["used"]) / d["total"])).ljust(20, g("dot")) if d["total"] else ""
        limits = [{"key": "capGB", "label": "Cap in GB (empty: none)", "value": "" if d["capGB"] is None else d["capGB"]},
                  {"key": "reserveGB", "label": "GB always kept free", "value": d["reserveGB"]}, {"key": "maxMB", "label": "Biggest file in MB", "value": d["maxMB"]}]

        def save(f, v):
            try:
                body = {"capGB": -1 if str(v["capGB"]).strip() == "" else float(v["capGB"]), "reserveGB": float(v["reserveGB"]), "maxMB": int(float(v["maxMB"]))}
            except ValueError:
                return f.fail("Numbers only")
            self.save("PATCH", "api/admin/local/limits", body, "Saved", f)
        yes = lambda ok: "yes" if ok else "no: kept as uploaded"   # noqa: E731
        return [head("Room", f"{a.cli.plural(d['count'], 'song')} {g('dot')} {size(d['used'])}"),
                item("The disk  " + bar, f"{size(d['free'])} free of {size(d['total'])}"),
                item("Local songs take", size(d["used"]) + (f" of {d['capGB']:g} GB" if d["capGB"] is not None else "")),
                item("Room for more", size(d["room"]) if d["room"] else "none: uploads are refused"),
                item(f"Limits{g('dots')}", f"cap {'none' if d['capGB'] is None else str(d['capGB']) + ' GB'} {g('dot')} {d['reserveGB']:g} GB kept free {g('dot')} files up to {d['maxMB']} MB",
                     run=lambda: a.ask("Limits", limits, save)),
                head("Converting"), item("WAV and AIFF to FLAC", yes(enc["mpv"] and enc["flac"])), item("Anything else to Opus", yes(enc["mpv"] and enc["opus"])),
                head("Backup"), item(f"Save a full backup, with the audio{g('dots')}", run=lambda: a.stacks["settings"][0].backup(True))]

    # --- Security
    def rows_security(self):
        log, a = self.d.get("api/admin/audit"), self.app
        if log is None:
            return None

        def change(f, v):
            if v["new"] != v["again"]:
                return f.fail("That's not the same")
            a.send("POST", "api/admin/password", {"old": v["old"], "new": v["new"]}, lambda _: (f.close(), a.say("Admin password changed")), fail=f.fail)
        rows = [item(f"Change the password{g('dots')}", run=lambda: a.ask("Admin password", [
            {"key": "old", "label": "Current", "kind": "secret"}, {"key": "new", "label": "New", "kind": "secret"}, {"key": "again", "label": "New, again", "kind": "secret"}], change)),
            item("Lock now", run=lambda: a.send("POST", "api/admin/logout", {}, lambda _: (a.say("Admin locked"), a.poll(), a.go("queue")))),
            head("Audit log", f"the last {len(log)}")]
        rows += [item(e["msg"], time.strftime("%d %b %H:%M", time.localtime(e["t"])) + (f"  {e['ip']}" if e.get("ip") else ""),
                      style="red" if e["ev"] in ("fail", "lockout") else "") for e in log]
        return rows

    def key(self, k):
        if k in ("tab", "btab"):
            self.part = (self.part + (1 if k == "tab" else -1)) % len(self.PARTS)
            self.sel = self.top = 0
            self.set_rows([], "Loading...")
            self.build()
            self.shown()
            return True
        return super().key(k)


# ---------- the app ----------
TABS = [("home", "Home", ("browse",), Home), ("search", "Search", (), Search), ("queue", "Queue", (), Queue), ("lists", "Playlists", ("playlists", "likes"), Lists),
        ("history", "History", (), History), ("local", "Local", ("local",), Local), ("stats", "Stats", ("stats",), Stats), ("lyrics", "Lyrics", ("lyrics",), Lyrics),
        ("settings", "Settings", (), Settings), ("admin", "Admin", (), Admin)]
KEYS = [("head", "Anywhere"), "1 to 9, 0    the tabs", "Space        play or pause", "Left Right   back or ahead 10 seconds", "n p          next song, previous",
        "+ -          volume;  m  mute", "f            like the song playing", "z            undo the last queue change", "/            search",
        "w            who is listening", "Esc          back, close", "?            these keys", "q            quit", "",
        ("head", "In a list"), "Up Down j k  move;  PgUp PgDn, g G", "Enter        add the song to the queue, or open", "N            play it next",
        "P            play it now", "L            like it", "A            add it to a playlist", "r            load again", "",
        ("head", "In the queue"), "Enter        play that song now", "d            remove it", "t            play it next", "J K          move it down, up",
        "S C          shuffle, clear", "r R          new radio songs, clear the radio", "s            save the queue as a playlist"]
HOUSE = {"name": "Tunebox", "off": [], "signups": "open", "groups": {"one": "Group", "many": "Groups", "required": False, "create": "open"},
         "wall": {}, "local": {"maxMB": 200}, "tz": "", "accent": ""}


class App:
    def __init__(self, cli, client, term, threads=True, ascii=False, color=True):
        global ASCII
        ASCII = ascii
        self.cli, self.client, self.term, self.color = cli, client, term, color
        self.events: queue.Queue = queue.Queue()
        self.net = Net(client, self.post, threads)
        self.threads, self.running = threads, True
        self.cols, self.rows_n = term.size()
        self.screen = Screen(self.cols, self.rows_n, color)
        self.state, self.state_at, self.down, self.state_n = {}, time.monotonic(), "", 0
        self.house, self.people, self.groups, self.liked = dict(HOUSE), [], [], set()
        self.revs = {"house": None, "people": None, "lists": None}
        self.latest, self.waiting = {}, {"pick": [], "admin": []}
        self.modals, self.toast, self.muted = [], ("", 0.0), None
        self.stacks = {key: [cls(self)] for key, _, _, cls in TABS}
        self.tab = "queue"
        self.body_h = max(1, self.rows_n - 3)

    # ----- events
    def post(self, ev):
        if self.threads:
            self.events.put(ev)
        else:
            self.handle(ev)

    def handle(self, ev):
        if ev[0] == "net":
            self.on_net(*ev[1:])
        elif ev[0] == "state":
            self.on_state(*ev[1:])
        else:
            self.key(ev if isinstance(ev, str) else ev[1])

    def begin(self):
        self.reload()
        self.poll()
        self.go("home" if self.on("browse") else "queue")

    def loop(self):
        self.begin()
        while self.running:
            try:
                ev = self.events.get(timeout=0.25)
            except queue.Empty:
                ev = None
            while ev is not None:
                self.handle(ev)
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    ev = None
            self.draw()

    # ----- requests
    def call(self, job):
        if job.get("key"):
            self.latest[job["key"]] = job
        self.net.submit(job)

    def get(self, path, then, params=None, key=None, fail=None):
        self.call({"method": "GET", "path": path, "params": params, "then": then, "key": key, "fail": fail})

    def send(self, method, path, body, then=None, fail=None, **more):
        self.call({"method": method, "path": path, "body": {} if body is None and method == "POST" and "data" not in more else body, "then": then, "fail": fail, **more})

    def on_net(self, job, result, err):
        if job.get("key") and self.latest.get(job["key"]) is not job:
            return                            # a newer request for the same thing is out: this answer is old
        if err is None:
            if job.get("then"):
                job["then"](result)
            return
        if isinstance(err, self.cli.Refused):
            again = not job.get("retried")
            if err.status == 401 and err.detail == "pick" and again:
                return self.need("pick", job)
            if err.status == 403 and err.detail == "admin" and again:
                return self.need("admin", job)
            if err.status == 409:
                self.poll()                   # the queue changed under us: look again
            return (job.get("fail") or self.say)(err.detail)
        (job.get("fail") or self.say)("Tunebox doesn't answer" if isinstance(err, self.cli.Unreachable) else f"{type(err).__name__}: {err}")

    def need(self, what, job):
        """A request needs a name or the admin: ask once, then send everything that waited for it."""
        self.waiting[what].append(job)
        if len(self.waiting[what]) == 1:
            self.pick_name() if what == "pick" else self.ask_admin()

    def resume(self, what, ok=True):
        jobs, self.waiting[what] = self.waiting[what], []
        for job in jobs:
            if ok:
                self.call({**job, "retried": True})
            elif job.get("fail"):
                job["fail"]("Say who you are first (w)" if what == "pick" else "That needs the admin password")

    def poll(self):
        if self.threads:
            n = next(self.net.seq)
            self.net.jobs.put({"method": "GET", "path": "api/state", "then": lambda s: self.on_state(s, None, n), "timeout": 8})
        else:
            n = next(self.net.seq)
            self.on_state(*self.net.run({"method": "GET", "path": "api/state"}), n)

    def on_state(self, st, err, n=0):
        if n and n < self.state_n:
            return                            # sent before an answer already shown (the poller and a worker raced)
        self.state_n = max(self.state_n, n)
        if err is not None:
            self.down = "Tunebox doesn't answer" if isinstance(err, self.cli.Unreachable) else str(err)
            return
        self.down, self.state, self.state_at = "", st, time.monotonic()
        if st.get("houseRev") != self.revs["house"]:
            self.revs["house"] = st.get("houseRev")
            self.get("api/house", self.got_house)
        if st.get("peopleRev") != self.revs["people"]:
            self.revs["people"] = st.get("peopleRev")
            self.get("api/people", lambda r: (setattr(self, "people", r), self.view().build()))
            self.get("api/seminars", lambda r: setattr(self, "groups", r))
        if st.get("listsRev") != self.revs["lists"]:
            self.revs["lists"] = st.get("listsRev")
            self.get("api/lists/liked", lambda p: (setattr(self, "liked", {t["videoId"] for t in p["tracks"]}), self.view().build()), fail=lambda d: None)
        self.view().build()

    def got_house(self, h):
        self.house = h
        if not self.tab_on(self.tab):
            self.go("queue")
        self.view().build()

    def reload(self):
        """Everything that depends on the house and its people, afresh."""
        self.revs = {"house": None, "people": None, "lists": None}
        self.poll()

    # ----- what is there
    def admin(self) -> bool:
        return bool(self.state.get("admin"))

    def on(self, feature: str) -> bool:
        """Is this part of Tunebox there for us? What is switched off is the admin's alone."""
        return feature not in self.house["off"] or self.admin()

    def tab_on(self, key) -> bool:
        needs = next(t[2] for t in TABS if t[0] == key)
        return not needs or any(self.on(f) for f in needs)

    def me(self):
        return next((p for p in self.people if p["id"] == self.client.jar.get("tb_who")), None)

    def name_of(self, pid) -> str:
        if not pid or not self.on("people"):
            return ""
        return next((p["name"] for p in self.people if p["id"] == pid), "")

    def position(self) -> float:
        st = self.state
        if not st.get("current"):
            return 0.0
        moving = not st.get("paused") and not st.get("loading")
        return min(st.get("position", 0) + (time.monotonic() - self.state_at if moving else 0), st.get("duration") or 1e9)

    # ----- moving about
    def view(self) -> View:
        return self.stacks[self.tab][-1]

    def go(self, key):
        if not self.tab_on(key):
            return self.say("The admin switched that off")
        if key == self.tab and len(self.stacks[key]) > 1:
            del self.stacks[key][1:]          # the tab's key again: back to its first page
        self.tab = key
        self.view().shown()
        self.view().build()

    def push(self, view):
        self.stacks[self.tab].append(view)
        view.shown()

    def pop(self):
        if len(self.stacks[self.tab]) > 1:
            self.stacks[self.tab].pop()
            self.view().shown()
            return True
        return False

    # ----- pop-ups and messages
    def say(self, text, secs=3.0):
        self.toast = (str(text), time.monotonic() + secs)

    def menu(self, title, rows, note=""):
        self.modals.append(Menu(self, title, rows, note))

    def ask(self, title, fields, done, note="", button="Save"):
        self.modals.append(Form(self, title, fields, done, note, button))

    def confirm(self, question, yes):
        self.menu("Are you sure?", [item("No"), item("Yes", run=yes)], note=question)

    def pick_name(self):
        if not self.on("people"):
            return self.resume("pick", False)

        def use(p):
            def done(_=None):
                self.client.set_who(p["id"])
                self.say(f"You are {p['name']}")
                self.resume("pick")
                self.view().build()
            if p.get("locked") and not p.get("mine"):
                return self.ask(f"{p['name']}'s pass phrase", [{"key": "phrase", "label": "Pass phrase", "kind": "secret"}],
                                lambda f, v: self.send("POST", f"api/people/{p['id']}/unlock", {"phrase": v["phrase"]}, lambda r: (f.close(), done()), fail=f.fail), button="Unlock")
            done()

        def new():
            gr = self.house["groups"]
            fields = [{"key": "name", "label": "Name", "value": ""}]
            if self.on("groups"):
                fields.append({"key": "group", "label": gr["one"], "value": ""})
            note = ("Its " + gr["one"].lower() + ": " + ", ".join(s["name"] for s in self.groups)) if self.on("groups") and self.groups else ""
            self.ask("Add a name", fields, lambda f, v: self.send("POST", "api/people", {"name": v["name"], **({"seminars": [v["group"]]} if v.get("group", "").strip() else {})},
                                                                  lambda p: (f.close(), self.people.append(p), use(p)), fail=f.fail), note=note, button="Add")
        rows = [item(p["name"], "pass phrase" if p.get("locked") and not p.get("mine") else "", run=lambda p=p: use(p)) for p in self.people]
        if self.house["signups"] == "open" or self.admin():
            rows.append(item(f"Add a name{g('dots')}", run=new))
        if self.me():
            rows.append(item("Nobody", run=lambda: (self.client.set_who(None), self.say("You are nobody here now"))))
        self.menu("Who's listening?", rows)

    def ask_admin(self):
        def got(st):
            if st["admin"]:
                return self.resume("admin")
            if st["lockedFor"]:
                self.say(f"Too many wrong passwords. Try again in {-(-st['lockedFor'] // 60)} min")
                return self.resume("admin", False)
            fields = [{"key": "pw", "label": "Password", "kind": "secret"}] + ([] if st["set"] else [{"key": "again", "label": "Again", "kind": "secret"}])

            def login(f, v):
                if not st["set"] and v["pw"] != v["again"]:
                    return f.fail("That's not the same")
                self.send("POST", "api/admin/login", {"password": v["pw"], "create": not st["set"]}, lambda r: (self.poll(), self.resume("admin"), f.close()), fail=f.fail)
            form = Form(self, "Admin password" if st["set"] else "Choose an admin password", fields, login, button="Unlock" if st["set"] else "Set it",
                        note="" if st["set"] else "Nobody has set one yet. At least 4 characters.")
            closing = form.close

            def close():                      # closed without unlocking: what waited for it is told so
                closing()
                if self.waiting["admin"]:
                    self.resume("admin", False)
            form.close = close
            self.modals.append(form)
        self.get("api/admin", got)

    # ----- doing things
    def control(self, action, **more):
        self.send("POST", "api/control", {"action": action, **more}, lambda r: (r.get("message") and self.say(r["message"]), self.poll()))

    def add(self, tracks, mode, label=""):
        self.send("POST", "api/play", {"tracks": tracks, "mode": mode, "label": label or None}, lambda r: (self.say(
            (f'"{label}": ' if label else tracks[0]["title"] + ": ") + r["message"]), self.poll()))

    def like(self, t):
        if not self.on("likes"):
            return
        liked = t["videoId"] in self.liked
        self.send("POST", "api/like", {"track": t, "liked": not liked}, lambda r: (self.say(("Unliked " if liked else "Liked ") + t["title"]), self.poll()))

    def to_playlist(self, t):
        if not self.on("playlists"):
            return

        def put(p):
            self.send("POST", f"api/lists/{p['id']}/tracks", {"track": t}, lambda r: self.say(f'Already in "{p["name"]}"' if r["duplicate"] else f'Added to "{p["name"]}"'))

        def new():
            self.ask("New playlist", [{"key": "name", "label": "Name", "value": ""}],
                     lambda f, v: self.send("POST", "api/lists", {"name": v["name"], "tracks": [t]}, lambda p: (f.close(), self.say(f'Added to "{p["name"]}"')), fail=f.fail), button="Create")
        self.get("api/lists", lambda ls: self.menu("Add to a playlist", [item(f"New playlist{g('dots')}", run=new)] + [
            item(p["name"], self.cli.plural(p["count"], "song"), run=lambda p=p: put(p)) for p in ls if not p["liked"]], note=t["title"]))

    def volume(self, d):
        v = max(0, min(100, self.state.get("volume", 50) + d))
        self.state["volume"] = v
        self.control("volume", value=v)

    # ----- keys
    def key(self, k):
        if k == "c-c":
            self.running = False
        elif k == "c-l":
            self.screen.old = None
        elif self.modals:
            self.modals[-1].key(k)
        elif self.view().typing:
            if not self.view().key(k) and k == "esc":
                self.view().typing = False
        elif not self.view().key(k):
            self.global_key(k)

    def global_key(self, k):
        st = self.state
        tabs = {str((i + 1) % 10): t[0] for i, t in enumerate(TABS)}
        if k in tabs:
            self.go(tabs[k])
        elif k == "space":
            self.control("toggle")
        elif k in ("left", "right") and st.get("current"):
            self.control("seek", value=max(0, min(self.position() + (10 if k == "right" else -10), max(0, (st.get("duration") or 1) - 1))))
        elif k in ("n", "s-right", ".", ">"):
            self.control("next")
        elif k in ("p", "s-left", ",", "<"):
            self.control("prev")
        elif k in ("+", "=", "-", "_"):
            self.volume(5 if k in "+=" else -5)
        elif k == "m":
            if st.get("volume"):
                self.muted = st["volume"]
                self.volume(-100)
            else:
                self.volume(self.muted or 50)
        elif k == "f" and st.get("current"):
            self.like(st["current"])
        elif k == "z":
            self.control("undo")
        elif k == "/":
            self.go("search")
            self.view().typing = True
        elif k == "w":
            self.pick_name()
        elif k == "?":
            self.modals.append(Text(self, "Keys", [KEYS]))
        elif k in ("esc", "backspace"):
            self.pop()
        elif k == "q":
            self.running = False

    # ----- drawing
    def draw(self):
        size = self.term.size()
        if size != (self.cols, self.rows_n):  # the window was resized: start over
            self.cols, self.rows_n = size
            self.screen = Screen(self.cols, self.rows_n, self.color)
            self.term.write("\x1b[2J")
        s, cols, rows = self.screen, self.cols, self.rows_n
        s.clear()
        if cols < 20 or rows < 6:
            s.put(0, 0, "Too small")
            return self.term.write(s.render())
        self.body_h = rows - 3
        self.draw_tabs(s)
        side = min(44, cols // 3) if cols >= 100 and self.tab != "queue" else 0
        self.view().draw(s, 0, 1, cols - side - (1 if side else 0), self.body_h)
        if side:
            for k in range(self.body_h):
                s.put(cols - side - 1, 1 + k, g("v"), "dim")
            self.draw_next(s, cols - side, 1, side, self.body_h)
        self.draw_player(s, rows - 2)
        now = time.monotonic()
        note = self.down or (self.toast[0] if now < self.toast[1] else "") or self.state.get("error") or ""
        hints = (self.modals and " ") or (self.view().hints + "   ? keys   q quit")
        s.put(0, rows - 1, clip(note or hints, cols), ("red" if self.down or self.state.get("error") and not self.toast[0] else "yel") if note else "dim")
        for m in self.modals:
            m.draw(s)
        self.term.write(s.render())

    def draw_tabs(self, s):
        shown = [(i, t) for i, t in enumerate(TABS) if self.tab_on(t[0])]
        me = self.me()
        who = ([me["name"]] if me and self.on("people") else []) + (["admin"] if self.admin() else [])
        full = sum(len(t[1]) + 4 for _, t in shown) <= self.cols
        x = 0
        for i, t in shown:
            off = any(f in self.house["off"] for f in t[2]) and not any(f not in self.house["off"] for f in t[2])
            label = f" {(i + 1) % 10} {t[1]} " if full or t[0] == self.tab else f" {(i + 1) % 10} "
            x = s.put(x, 0, label, "tab" if t[0] == self.tab else "dim" if off else "")
        for parts in ([self.house["name"]] + who, who, who[-1:]):     # as much of "house, you, admin" as there is room for
            right = f" {g('dot')} ".join(parts)
            if right and x + text_width(right) + 1 <= self.cols:
                s.put(self.cols - text_width(right), 0, right, "dim")
                break

    def draw_next(self, s, x, y, w, h):
        q, nu = self.state.get("queue") or [], self.state.get("userCount", 0)
        s.put(x, y, clip("Up next", w), "head")
        if len(q) < 2:
            return s.put(x, y + 2, clip("Nothing yet", w), "dim")
        line = y + 1
        for i, t in enumerate(q[1:], 1):
            if line >= y + h:
                break
            if i == nu + 1:
                s.put(x, line, "Radio", "dim")
                line += 1
                if line >= y + h:
                    break
            by = self.name_of(t.get("by")) if t.get("src") == "user" else ""
            bw = text_width(by) + 1 if by else 0
            end = s.put(x, line, clip(t["title"], w - bw), "" if i <= nu else "dim", w - bw)
            if t.get("artist") and end + 3 < x + w - bw:
                s.put(end + 1, line, clip(t["artist"], x + w - bw - end - 1), "dim")
            if by:
                s.put(x + w - bw + 1, line, by, "blue")
            line += 1

    def draw_player(self, s, y):
        st, cols = self.state, self.cols
        t = st.get("current")
        if not t:
            return s.put(0, y, clip("Nothing is playing. Press / to search.", cols), "dim")
        pos, dur = self.position(), st.get("duration") or 0
        mark = g("dots") if st.get("loading") else "||" if st.get("paused") else g("play")
        right = f" {self.cli.clock(pos)} / {self.cli.clock(dur)}  vol {st.get('volume', '')}" + (f"  {g('heart')}" if t["videoId"] in self.liked else "")
        sl = st.get("sleep")
        if sl:
            right += "  sleep " + ("after this" if sl["mode"] == "track" else self.cli.clock(sl["left"]))
        rw = text_width(right)
        barw = max(0, min(30, cols - rw - 24))
        x = s.put(0, y, mark + " ", "now")
        room = cols - x - rw - (barw + 1 if barw else 0)
        end = s.put(x, y, clip(t["title"], room), "b", room)
        if t.get("artist") and end + 4 < x + room:
            s.put(end + 1, y, clip(g("dot") + " " + t["artist"], x + room - end - 1), "dim")
        if barw:
            done = round(barw * pos / dur) if dur else 0
            bx = cols - rw - barw
            s.put(bx, y, g("full") * done, "red")
            s.put(bx + done, y, g("rest") * (barw - done), "dim")
        s.put(cols - rw, y, right, "")

    # ----- for the checks
    def press(self, *keys):
        for k in keys:
            self.handle(k)
        return self

    def type(self, text):
        return self.press(*("space" if ch == " " else ch for ch in text))

    def text(self) -> list[str]:
        self.draw()
        return self.screen.lines()


def run(cli, client, a) -> int:
    """tunebox tui"""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise cli.Usage("tunebox tui needs a terminal (tunebox status prints once)")
    term = Terminal()
    app = App(cli, client, term, ascii=bool(a.ascii or os.environ.get("TUNEBOX_ASCII")), color=not os.environ.get("NO_COLOR"))
    try:
        term.start(app.events.put)
        app.loop()
    finally:
        term.stop()
    return 0

"""tunebox tray: Tunebox in the Windows notification area, and the keyboard's media keys for the house.

  The icon        the Tunebox mark, drawn here (no file); hovering it shows the song playing
  A click         play or pause; a right-click: the menu (play/pause, next, previous, open Tunebox, quit)
  Media keys      play/pause, next and previous control the house's speakers while this runs;
                  with --volume, the volume keys too (else they stay the PC's own)

Standard library only (ctypes), like cli.py, which starts it and hands itself in (run(cli, client,
args)): it must not import cli, which runs as __main__. One thread runs the window's messages; requests
go out on a worker thread, and a third asks for api/state every two seconds (six while nothing plays),
so the icon never stalls on the network."""
import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes as w

if sys.platform != "win32":
    raise ImportError("tunebox tray is for Windows")

user32, shell32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.gdi32, ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.CreateIconIndirect.restype = w.HICON
gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.CreateBitmap.restype = w.HBITMAP
kernel32.GetModuleHandleW.restype = w.HMODULE

WM_DESTROY, WM_COMMAND, WM_HOTKEY, WM_APP = 0x0002, 0x0111, 0x0312, 0x8000
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
WM_TRAY, WM_STATE = WM_APP + 1, WM_APP + 2      # the icon's own messages; a new answer from api/state
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_SEPARATOR, MF_GRAYED = 0, 0x800, 1
TPM_RIGHTBUTTON, TPM_RETURNCMD = 2, 0x100
VK = {"toggle": 0xB3, "next": 0xB0, "prev": 0xB1, "up": 0xAF, "down": 0xAE}
MENU = [(1, "toggle"), (2, "next"), (3, "prev"), (0, None), (4, "open"), (0, None), (5, "quit")]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT), ("uCallbackMessage", w.UINT),
                ("hIcon", w.HICON), ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
                ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD), ("biBitCount", w.WORD),
                ("biCompression", w.DWORD), ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
                ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD), ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP)]


def mark_icon(n: int = 32) -> int:
    """The Tunebox mark (a red circle, a yellow triangle, a blue square) as an n x n icon, drawn pixel by pixel."""
    hdr = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), n, -n, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    color = gdi32.CreateDIBSection(None, ctypes.byref(hdr), 0, ctypes.byref(bits), None, 0)
    px = (ctypes.c_uint32 * (n * n)).from_address(bits.value)
    red, yellow, blue = 0xFFE63B2E, 0xFFF2C230, 0xFF1F5FBF    # ARGB
    s = n / 26                                                 # the page's mark is 26 px
    for y in range(n):
        for x in range(n):
            fx, fy, c = (x + .5) / s, (y + .5) / s, 0
            if (fx - 8) ** 2 + (fy - 13) ** 2 <= 64:
                c = red
            if 0 <= fy <= 13 and abs(fx - 19) <= 7 * fy / 13:
                c = yellow
            if 16 <= fx <= 25 and 17 <= fy <= 26:
                c = blue
            px[y * n + x] = c
    mask = gdi32.CreateBitmap(n, n, 1, 1, None)
    return user32.CreateIconIndirect(ctypes.byref(ICONINFO(True, 0, 0, mask, color)))


class Tray:
    def __init__(self, cli, client, volume: bool):
        self.cli, self.client, self.volume = cli, client, volume
        self.jobs: queue.Queue = queue.Queue()
        self.state, self.down = None, False
        self.proc = WNDPROC(self.wndproc)      # kept, or ctypes frees the callback under Windows' feet
        inst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(0, self.proc, 0, 0, inst, None, None, None, None, "TuneboxTray")
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "TuneboxTray", "Tunebox", 0, 0, 0, 0, 0, None, None, inst, None)
        self.nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1, uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP,
                                   uCallbackMessage=WM_TRAY, hIcon=mark_icon(), szTip="Tunebox")
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))
        self.keys = [k for k in ("toggle", "next", "prev") + (("up", "down") if volume else ())
                     if user32.RegisterHotKey(self.hwnd, list(VK).index(k) + 1, 0x4000, VK[k])]   # 0x4000: no repeat
        threading.Thread(target=self.work, daemon=True).start()
        threading.Thread(target=self.poll, daemon=True).start()

    # ---- the network, off the window's thread
    def work(self):
        while True:
            fn = self.jobs.get()
            try:
                fn()
            except Exception:
                pass
            self.ask_state()                   # show what the action did at once

    def ask_state(self):
        try:
            self.state, self.down = self.client.get("api/state"), False
        except Exception:
            self.down = True
        user32.PostMessageW(self.hwnd, WM_STATE, 0, 0)

    def poll(self):
        while True:
            self.ask_state()
            s = self.state or {}
            time.sleep(2 if s.get("current") and not s.get("paused") else 6)   # nothing plays: less often

    def act(self, what: str):
        c = self.client
        if what in ("toggle", "next", "prev"):
            self.jobs.put(lambda: self.cli.control(c, what))
        elif what in ("up", "down"):
            self.jobs.put(lambda: self.cli.control(c, "volume", value=max(0, min(100, (self.state or {}).get("volume", 50) + (5 if what == "up" else -5)))))
        elif what == "open":
            os.startfile(c.base)
        elif what == "quit":
            user32.DestroyWindow(self.hwnd)

    # ---- the window's thread
    def tip(self) -> str:
        s = self.state
        if self.down:
            return "Tunebox doesn't answer"
        t = (s or {}).get("current")
        if not t:
            return "Tunebox: nothing playing"
        return f"{'Paused: ' if s.get('paused') else ''}{t['title']}" + (f" - {t['artist']}" if t.get("artist") else "")

    def menu(self):
        m = user32.CreatePopupMenu()
        paused = not (self.state or {}).get("current") or (self.state or {}).get("paused")
        names = {"toggle": "Play" if paused else "Pause", "next": "Next", "prev": "Previous", "open": "Open Tunebox", "quit": "Quit"}
        user32.AppendMenuW(m, MF_GRAYED, 0, self.tip()[:60])
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        for i, k in MENU:
            user32.AppendMenuW(m, MF_SEPARATOR if not k else MF_STRING, i, names.get(k))
        pt = w.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)      # else the menu stays open after a click elsewhere
        cmd = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(m)
        k = dict(MENU).get(cmd)
        if k:
            self.act(k)

    def wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_TRAY and lp == WM_LBUTTONUP:
            self.act("toggle")
        elif msg == WM_TRAY and lp == WM_RBUTTONUP:
            self.menu()
        elif msg == WM_HOTKEY:
            self.act(list(VK)[wp - 1])
        elif msg == WM_STATE:
            tip = self.tip()[:127]
            if tip != self.nid.szTip:
                self.nid.szTip = tip
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))
        elif msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def loop(self):
        m = w.MSG()
        while user32.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(m))
            user32.DispatchMessageW(ctypes.byref(m))


def run(cli, client, args) -> int:
    t = Tray(cli, client, getattr(args, "volume", False))
    missing = [k for k in ("toggle", "next", "prev") if k not in t.keys]
    print("Tunebox is in the notification area." + (" Media keys: " + ", ".join(t.keys) + "." if t.keys else "")
          + (f" Another program holds these keys: {', '.join(missing)}." if missing else "") + " Quit from its menu.", flush=True)
    try:
        t.loop()
    except KeyboardInterrupt:
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(t.nid))
    return 0

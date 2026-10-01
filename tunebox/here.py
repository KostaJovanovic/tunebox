"""Who's here: every device that asked for /api/state in the last minute (an open page asks once a
second, the terminal interface too), for the admin's People tab. Kept in memory only."""
import hashlib
import time

seen: dict[str, dict] = {}                     # a device (its address and browser) -> what it was last seen as


def device_of(ua: str) -> str:
    """ "iPhone · Safari", "Windows · Firefox", "Command line"... from a User-Agent, roughly."""
    if ua.startswith("Python-urllib"):
        return "Command line"
    system = next((name for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "ChromeOS"),
                                          ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")) if key in ua), "")
    browser = next((name for key, name in (("Firefox/", "Firefox"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), "")
    return " · ".join(filter(None, (system, browser))) or "Something"


def saw(request, who: str):
    ua = request.headers.get("user-agent", "")
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    key = hashlib.sha1(f"{ip}|{ua}".encode()).hexdigest()[:12]
    seen[key] = {"ip": ip, "device": device_of(ua), "who": who, "wall": "/wall" in request.headers.get("referer", ""), "at": time.time()}
    if len(seen) > 300:                       # forget the ones gone longest
        for k in sorted(seen, key=lambda k: seen[k]["at"])[:100]:
            del seen[k]


def now(window: float = 60) -> list[dict]:
    """The devices seen in the last `window` seconds, the most recent first."""
    cut = time.time() - window
    return sorted((v for v in seen.values() if v["at"] >= cut), key=lambda v: -v["at"])

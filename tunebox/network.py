"""Where the server is on the network, for the bottom of Settings: its LAN address and, when it is on
Wi-Fi, the network's name. Both are found afresh at most once a minute (the Wi-Fi name runs a program).

A machine can have several addresses (a cable and Wi-Fi, a VPN that takes every route), so the one
shown is the one on the same network as the device asking; see best()."""
import ipaddress
import re
import shutil
import socket
import subprocess
import sys
import time

TTL = 60
_cache: dict = {"at": 0.0, "info": None}


def usable(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_link_local or a.is_unspecified)


def run(*cmd) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=flags, errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def addresses() -> list[str]:
    """This machine's IPv4 addresses, the one its default route leaves from first. Connecting a UDP
    socket sends nothing; it only picks the route."""
    out = []
    for target in ("192.168.255.255", "10.255.255.255", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 1))
                out.append(s.getsockname()[0])
            break
        except OSError:
            pass
    try:
        out += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    if sys.platform.startswith("linux"):         # the name often resolves to 127.0.1.1 only there
        out += run("hostname", "-I").split()
    return list(dict.fromkeys(ip for ip in out if usable(ip)))


def wifi_name() -> str | None:
    """The Wi-Fi network this machine is connected to, or None (wired, or no tool to ask)."""
    if sys.platform == "win32":
        m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", run("netsh", "wlan", "show", "interfaces"), re.M)
        return m.group(1) if m else None
    if sys.platform == "darwin":
        m = re.search(r"Current Wi-Fi Network:\s*(.+)", run("networksetup", "-getairportnetwork", "en0"))
        return m.group(1).strip() if m else None
    for line in run("nmcli", "-t", "-f", "active,ssid", "dev", "wifi", "list", "--rescan", "no").splitlines():   # no scan: that takes seconds
        if line.startswith("yes:") and line[4:]:
            return line[4:].replace("\\:", ":")
    if name := run("iwgetid", "-r").strip():
        return name
    m = re.search(r"^\s*ssid (.+)$", run("iw", "dev"), re.M)
    return m.group(1).strip() if m else None


def best(ips: list[str], client: str | None) -> str | None:
    """The address that shares the most leading bits with the device asking: the one it can reach.
    A device on this machine itself (or an unknown one) gets the default route's."""
    if not ips:
        return None
    try:
        a = ipaddress.ip_address(client or "")
        client = str(getattr(a, "ipv4_mapped", None) or a)   # "::ffff:10.0.0.5" is an IPv4 client
    except ValueError:
        pass
    if not client or not usable(client):
        return ips[0]
    c = int(ipaddress.IPv4Address(client))
    return max(ips, key=lambda ip: 32 - (int(ipaddress.IPv4Address(ip)) ^ c).bit_length())


def info(client: str | None = None, wifi: bool = True) -> dict:
    """{"ip", "ips", "wifi", "host"} for the device at `client`; blocking (it may run a program), so
    call it in a thread. wifi=False: the Wi-Fi's name isn't wanted (the admin typed it), so no program runs for it."""
    if _cache["info"] is None or time.monotonic() - _cache["at"] > TTL or (wifi and _cache["info"]["wifi"] is False):
        _cache["info"] = {"ips": addresses(), "wifi": wifi_name() if wifi else False, "host": socket.gethostname()}
        _cache["at"] = time.monotonic()
    found = _cache["info"]
    return {**found, "ip": best(found["ips"], client)}

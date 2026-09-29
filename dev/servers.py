"""The servers save.bat / save.sh deploy to, and the SSH connection to one of them.

Each device keeps its own list in dev/servers.json (git-ignored):

  {"default": "ele",
   "servers": {"ele": {"hosts": ["ele.local", "10.100.0.105"], "user": "dietpi"}}}

hosts are tried in order (the first that answers on SSH wins). A server can also carry
settings that deploy.py would otherwise work out for itself (see deploy.py). Without the
file, deploy.py's built-in server is used, and the first deploy asks for the address and
user and writes the file.

The same file is in the homeapps and tunebox repositories: change both.
"""
import getpass
import json
import re
import shlex
import socket
from pathlib import Path

FILE = Path(__file__).resolve().parent / "servers.json"
# `sudo` where it starts a command: at the start, after ; & | ( or after xargs and its flags
SUDO = re.compile(r"(^|[;&|(]\s*|\bxargs(?:\s+-\w+)*\s+)sudo\s+")


def say(tag, msg=""):
    print(f"[{tag}]".ljust(8) + msg, flush=True)


def load(builtin: dict) -> dict:
    """{"default": name, "servers": {name: {...}}}; the built-in list when there is no file."""
    try:
        cfg = json.loads(FILE.read_text(encoding="utf-8"))
        if cfg.get("servers"):
            cfg.setdefault("default", next(iter(cfg["servers"])))
            return cfg
    except FileNotFoundError:
        pass
    except ValueError as e:
        say("err", f"{FILE.name} is not valid JSON ({e}) - using the built-in server")
    return {"default": builtin["name"], "servers": {builtin["name"]: {k: v for k, v in builtin.items() if k != "name"}}}


def save(cfg: dict):
    FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    say("cfg", f"saved {FILE}")


def ask(prompt: str, default: str = "") -> str:
    got = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return got or default


def first_run(builtin: dict) -> dict:
    """No servers.json yet: ask where to deploy, with the built-in server as the answer to Enter."""
    print(f"\nNo server list on this device yet ({FILE.name}). Press Enter to keep a value.")
    hosts = ask("server address(es), comma separated", ", ".join(builtin["hosts"]))
    server = {"hosts": [h.strip() for h in hosts.split(",") if h.strip()],
              "user": ask("SSH user", builtin["user"])}
    name = ask("a short name for it", builtin["name"] if server["hosts"] == builtin["hosts"] else server["hosts"][0].split(".")[0])
    cfg = {"default": name, "servers": {name: server}}
    save(cfg)
    return cfg


def pick(builtin: dict, name: str = "", choose: bool = False, interactive: bool = True) -> dict | None:
    """The server to use: the one named, else (with choose and several servers) the one picked from a
    list, else the default. Returns its settings with "name" added, or None."""
    if interactive and not FILE.exists():
        cfg = first_run(builtin)
    else:
        cfg = load(builtin)
    servers = cfg["servers"]
    if name:
        if name not in servers:
            say("err", f"no server called {name!r} (have: {', '.join(servers)})")
            return None
    elif choose and len(servers) > 1:
        names = list(servers)
        for i, n in enumerate(names, 1):
            print(f"  {i}  {n:<12} {', '.join(servers[n]['hosts'])}" + ("   (default)" if n == cfg["default"] else ""))
        got = ask("which server", str(names.index(cfg["default"]) + 1))
        if not got.isdigit() or not 1 <= int(got) <= len(names):
            say("err", "no such server")
            return None
        name = names[int(got) - 1]
    else:
        name = cfg["default"]
    return {**servers[name], "name": name}


def manage(builtin: dict) -> int:
    """save.bat's "servers" option: list them, add, remove, pick the default."""
    cfg = load(builtin)
    while True:
        print()
        for n, s in cfg["servers"].items():
            print(f"  {n:<12} {s.get('user', '?')}@{', '.join(s['hosts'])}" + ("   (default)" if n == cfg["default"] else ""))
        print("\n  a  add a server    r  remove one    d  set the default    Enter  done")
        c = input("choice: ").strip().lower()
        if c == "a":
            name = ask("name (e.g. ele, office)")
            hosts = ask("address(es), comma separated")
            if not name or not hosts:
                continue
            cfg["servers"][name] = {"hosts": [h.strip() for h in hosts.split(",") if h.strip()],
                                    "user": ask("SSH user", "dietpi")}
            if len(cfg["servers"]) == 1:
                cfg["default"] = name
            save(cfg)
        elif c == "r":
            name = ask("remove which")
            if name in cfg["servers"] and len(cfg["servers"]) > 1:
                del cfg["servers"][name]
                if cfg["default"] == name:
                    cfg["default"] = next(iter(cfg["servers"]))
                save(cfg)
            else:
                say("err", "no such server (or it's the last one)")
        elif c == "d":
            name = ask("default server")
            if name in cfg["servers"]:
                cfg["default"] = name
                save(cfg)
            else:
                say("err", "no such server")
        elif not c:
            return 0


def reachable(server: dict, timeout=3.0) -> str | None:
    """The first of the server's addresses that answers on SSH, or None."""
    for host in server["hosts"]:
        try:
            with socket.create_connection((host, 22), timeout=timeout):
                return host
        except OSError:
            continue
    return None


class Server:
    """An SSH session. run() takes shell commands that use plain `sudo`: they work with passwordless
    sudo, as root, or with a sudo password asked once per run (then the whole command runs as root)."""

    def __init__(self, client, host, user):
        self.c, self.host, self.user = client, host, user
        self.sftp = client.open_sftp()
        self.sudo = None                  # "root", "nopass" or the sudo password, found on first use

    @classmethod
    def connect(cls, server: dict, host: str):
        import paramiko
        user = server.get("user") or "root"

        def client():
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            return c
        try:                              # this device's SSH key first, no prompts
            c = client()
            c.connect(host, username=user, look_for_keys=True, allow_agent=True, timeout=10)
            say("ssh", f"key login as {user}@{host}")
            return cls(c, host, user)
        except (paramiko.SSHException, OSError):
            pass
        for _ in range(3):                # then a password, asked every run and never stored
            pw = getpass.getpass(f"password for {user}@{host}: ")
            c = client()
            try:
                c.connect(host, username=user, password=pw, look_for_keys=False, allow_agent=False, timeout=10)
                return cls(c, host, user)
            except paramiko.AuthenticationException:
                say("err", "wrong password")
            except OSError as e:
                say("err", f"can't connect: {e}")
                return None
        return None

    def close(self):
        self.c.close()

    def _exec(self, cmd, stdin_text=None):
        i, out, err = self.c.exec_command(cmd)
        if stdin_text is not None:
            i.write(stdin_text)
            i.flush()
            i.channel.shutdown_write()
        rc = out.channel.recv_exit_status()
        return rc, out.read().decode(errors="replace"), err.read().decode(errors="replace")

    def _sudo_mode(self):
        if self.sudo is None:
            if self.user == "root":
                self.sudo = "root"
            elif self._exec("sudo -n true")[0] == 0:
                self.sudo = "nopass"
            else:
                for _ in range(3):
                    pw = getpass.getpass(f"sudo password for {self.user}@{self.host}: ")
                    if self._exec("sudo -S -p '' true", pw + "\n")[0] == 0:
                        self.sudo = pw
                        break
                    say("err", "wrong sudo password")
                else:
                    raise RuntimeError("sudo refused")
        return self.sudo

    def run(self, cmd, check=True):
        stdin_text = None
        if SUDO.search(cmd):
            mode = self._sudo_mode()
            if mode == "root":
                cmd = SUDO.sub(r"\1", cmd)
            elif mode != "nopass":        # one password, so the whole command runs as root
                cmd = "sudo -S -p '' sh -c " + shlex.quote(SUDO.sub(r"\1", cmd))
                stdin_text = mode + "\n"
        rc, o, e = self._exec(cmd, stdin_text)
        if check and rc != 0:
            raise RuntimeError(f"`{cmd[:200]}` failed ({rc}): {(e or o).strip()[:400]}")
        return rc, o, e

    def read(self, path) -> bytes | None:
        try:
            with self.sftp.open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def hashes(self, paths) -> dict:
        _, o, _ = self.run("sha256sum " + " ".join(shlex.quote(p) for p in paths) + " 2>/dev/null", check=False)
        return {line[66:]: line[:64] for line in o.splitlines() if len(line) > 66}

    def unit(self, service: str) -> dict:
        """What a systemd unit says: WorkingDirectory, ExecStart and its Environment= values."""
        rc, o, _ = self.run(f"systemctl cat {shlex.quote(service)}.service 2>/dev/null", check=False)
        info = {"env": {}}
        if rc != 0:
            return info
        for line in o.splitlines():
            key, _, val = line.strip().partition("=")
            if key in ("WorkingDirectory", "ExecStart"):
                info[key] = val.strip()
            elif key == "Environment":
                for pair in shlex.split(val):
                    k, _, v = pair.partition("=")
                    info["env"][k] = v
        return info

    def service_for(self, remote_dir) -> str | None:
        """The systemd unit that runs from this folder, found rather than hard-coded."""
        _, o, _ = self.run(f"grep -l '^WorkingDirectory={remote_dir}$' /etc/systemd/system/*.service 2>/dev/null",
                           check=False)
        units = [u.rsplit("/", 1)[-1].removesuffix(".service") for u in o.split()]
        return units[0] if units else None

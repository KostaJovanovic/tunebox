"""pip-installs dev/requirements.txt into the running venv when any requirement file changed."""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parent
STAMP = Path(sys.prefix) / "requirements.sha"


def files(req: Path, seen=None):
    """The requirement file and every file it pulls in with -r."""
    seen = seen or []
    seen.append(req)
    for line in req.read_text().splitlines():
        m = re.match(r"\s*-r\s+(\S+)", line)
        if m:
            files((req.parent / m.group(1)).resolve(), seen)
    return seen


def main():
    req = DEV / "requirements.txt"
    digest = hashlib.sha256(b"".join(f.read_bytes() for f in files(req))).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        return 0
    print("[env]   installing Python packages (only when the requirements change)", flush=True)
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(req)])
    if rc == 0:
        STAMP.write_text(digest)
    return rc


if __name__ == "__main__":
    sys.exit(main())

"""Reading and writing the JSON files, safely: a power cut never leaves half a file."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def write_json(path: Path, data) -> None:
    """Atomic and durable: a unique temp file next to the target, fsynced, then renamed over it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default):
    """A missing file gives the default; a corrupt one is moved aside (so nothing overwrites it) and reported."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except ValueError:                        # bad JSON or bad UTF-8
        bad = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(bad)
        except OSError:
            pass
        print(f"tunebox: {path.name} was corrupt, moved to {bad.name}", file=sys.stderr)
    except OSError as exc:
        print(f"tunebox: cannot read {path.name}: {exc}", file=sys.stderr)
    return default

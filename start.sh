#!/bin/sh
# Starts Tunebox on this computer (Linux): it plays through this computer's speakers, and the browser
# is the remote. Run ./install.sh --desktop once first. Options as for run.py: --local, --port N.
HERE=$(cd "$(dirname "$0")" && pwd)
[ -x "$HERE/.venv/bin/python" ] || { echo "[tunebox] run ./install.sh --desktop first"; exit 1; }
exec "$HERE/.venv/bin/python" "$HERE/run.py" "$@"

#!/bin/sh
# Tunebox setup for Linux. Run it from the Tunebox folder; run it again to update.
#
#   ./install.sh              a server: a systemd service that starts at boot and is open to the
#                             network (http://<this machine>:8888/)
#   ./install.sh --desktop    this computer only: start it with ./start.sh or from the app menu
#
#   --port N      another port (default 8888)
#
# It installs mpv and Python's venv with apt (asks for sudo), puts the Python packages in .venv and
# Node 22 in tools/node, and for a server writes /etc/systemd/system/tunebox.service.
set -eu

cd "$(dirname "$0")"
APP=$(pwd)
MODE=server
PORT=8888
while [ $# -gt 0 ]; do
  case "$1" in
    --desktop) MODE=desktop ;;
    --port) PORT=$2; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see ./install.sh --help)"; exit 1 ;;
  esac
  shift
done
say() { echo "[tunebox] $*"; }
SUDO=
[ "$(id -u)" -ne 0 ] && SUDO=sudo
ME=${SUDO_USER:-$(id -un)}

# ---------- system packages ----------
if command -v apt-get >/dev/null 2>&1; then
  say "installing mpv and Python's venv (apt)"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq mpv python3-venv python3-pip curl xz-utils >/dev/null
else
  command -v mpv >/dev/null 2>&1 || { say "install mpv and Python 3.11+ (with venv) with your package manager, then run this again"; exit 1; }
fi

# ---------- Python packages and Node ----------
[ -x .venv/bin/python ] || python3 -m venv .venv
say "installing the Python packages"
.venv/bin/pip install --quiet --disable-pip-version-check -U pip
.venv/bin/pip install --quiet --disable-pip-version-check -U -r requirements.txt
.venv/bin/python run.py --setup-only

if [ "$MODE" = desktop ]; then
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/tunebox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tunebox
Comment=YouTube Music on this computer's speakers
Exec=$APP/start.sh --port $PORT
Icon=$APP/web/icons/icon-512.png
Terminal=true
Categories=AudioVideo;Audio;Player;
EOF
  say "done. Start it with $APP/start.sh (it's in your app menu too, as Tunebox)"
  exit 0
fi

# ---------- server: the audio group and the service ----------
$SUDO usermod -aG audio "$ME"

say "writing /etc/systemd/system/tunebox.service"
$SUDO tee /etc/systemd/system/tunebox.service >/dev/null <<EOF
[Unit]
Description=Tunebox - YouTube Music player for the local speakers
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=$ME
Group=audio
WorkingDirectory=$APP
RuntimeDirectory=tunebox
Environment=TUNEBOX_RUN=/run/tunebox
ExecStart=$APP/.venv/bin/python $APP/run.py --lan --no-browser --port $PORT
Restart=always
RestartSec=5
Nice=-5

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
$SUDO systemctl enable tunebox >/dev/null 2>&1
$SUDO systemctl restart tunebox

say "done. Open http://$(hostname):$PORT/ from any device on the network"
for ip in $(hostname -I 2>/dev/null); do
  case "$ip" in *:*) ;; *) say "      or http://$ip:$PORT/" ;; esac
done
say "logs: sudo journalctl -u tunebox -f"

#!/bin/sh
# Git + deploy helper for Tunebox on macOS and Linux: the same menu as save.bat.
#
#   ./save.sh                     menu
#   ./save.sh save                commit + push to GitHub, then deploy to the default server if it is reachable
#   ./save.sh commit              commit only
#   ./save.sh deploy [server]     upload what changed in Tunebox to a server (no git)
#   ./save.sh status [server]     show what differs on the server, change nothing
#   ./save.sh pull                git pull
#   ./save.sh pull-data [server]  copy the server's live data into dev/data
#   ./save.sh servers             list, add or remove the servers this device deploys to
#   ./save.sh logout              forget the server address + SSH user, so the next deploy asks again
#   ./save.sh quick "msg"         commit + push to GitHub, no menu, prompts or deploy
#   ./save.sh quick-commit "msg"  commit only, no menu or prompts
#
# The servers are in dev/servers.json on each device (git-ignored; without it, ele).
# Deploying logs in with this device's SSH key, or asks for the password each time.
cd "$(dirname "$0")" || exit 1

QUICK=0
COMMIT_ONLY=0
ERR=0
ARG=${2:-}

env_ok() {
  # .venv with dev/requirements.txt (the same .venv start.sh uses); sets PY
  PY=.venv/bin/python
  if [ ! -x "$PY" ]; then
    echo "[env]   creating .venv (first run)"
    python3 -m venv .venv || { echo "[err]   could not create .venv - install Python 3.11+ with venv"; return 1; }
  fi
  "$PY" dev/ensure_deps.py || { echo "[err]   installing the Python packages failed - see above"; return 1; }
}

branch() { git rev-parse --abbrev-ref HEAD 2>/dev/null | grep -v '^HEAD$'; }
remote() {
  b=$(branch)
  r=$( [ -n "$b" ] && git config "branch.$b.remote" 2>/dev/null )
  [ -n "$r" ] && { echo "$r"; return; }
  git remote get-url origin >/dev/null 2>&1 && { echo origin; return; }
  git remote 2>/dev/null | head -n 1
}

save() {
  if [ ! -d .git ]; then
    echo "[warn]  no git repository here yet"
    [ "$QUICK" = 1 ] && return 1
    printf 'run "git init" now? (y/n): '; read -r a
    [ "$a" = y ] || { echo "[git]   skipped - nothing to commit into"; return 1; }
    git init -b main || return 1
  fi
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    echo "[err]   unresolved merge conflicts - resolve these first:"
    git diff --name-only --diff-filter=U
    return 1
  fi
  echo "[git]   stage"
  git add .
  if git diff --cached --quiet; then
    echo "[git]   nothing new to commit"
  else
    # the version (commit N is 0.NN, in web/shared/version.js) and web/patch.html, rebuilt from
    # patch-notes.md with it; only now, so a save with nothing to commit doesn't raise the count
    env_ok || return 1
    "$PY" dev/patch.py bump || { echo "[err]   could not stamp the version or build the patch notes - not saving"; return 1; }
    git add web/shared/version.js web/patch.html web/patch.json
    git status --short
    def="update $(date '+%Y-%m-%d %H:%M')"
    if [ "$QUICK" = 1 ]; then
      msg=$ARG
    else
      printf 'commit message [%s]: ' "$def"; read -r msg
    fi
    git commit -m "${msg:-$def}" || { "$PY" dev/patch.py unbump >/dev/null; echo "[err]   git commit failed"; return 1; }
  fi
  if [ "$COMMIT_ONLY" = 1 ]; then
    echo "[git]   committed locally, not pushed"
    return 0
  fi
  r=$(remote); b=$(branch)
  if [ -z "$r" ]; then
    echo "[git]   no GitHub remote yet - nothing pushed"
  elif [ -z "$b" ]; then
    echo "[err]   no branch checked out (detached HEAD?) - not pushing"; ERR=1
  elif git push -u "$r" "$b"; then
    echo "[git]   pushed $r/$b"
  elif git ls-remote "$r" >/dev/null 2>&1; then
    echo "[warn]  push rejected - $r/$b has commits you don't. Pull, then save again."; ERR=1
  else
    echo "[err]   push failed - cannot reach or authenticate to $r. The commit is saved locally."; ERR=1
  fi
  [ "$QUICK" = 1 ] && return $ERR          # quick never deploys: that can ask for passwords
  env_ok || return 1
  if "$PY" dev/deploy.py check; then
    "$PY" dev/deploy.py deploy || ERR=1
  else
    echo "[srv]   not deployed (run ./save.sh deploy when the server is reachable)"
  fi
  return $ERR
}

tool() { env_ok && "$PY" dev/deploy.py "$@"; }

pull() {
  r=$(remote); b=$(branch)
  [ -n "$b" ] || { echo "[err]   no branch checked out"; return 1; }
  [ -n "$r" ] || { echo "[err]   no remote configured yet"; return 1; }
  git pull "$r" "$b"
}

logout() {
  # without dev/servers.json the next deploy asks for the address and SSH user again
  if [ -f dev/servers.json ]; then
    mv -f dev/servers.json dev/servers.json.old || return 1
    echo "[srv]   forgot the server address and SSH user (moved to dev/servers.json.old) - the next deploy asks for them again"
  else
    echo "[srv]   no saved server - the next deploy asks for the address and SSH user"
  fi
  echo "[srv]   the SSH password is never saved: deploy asks for it each time the SSH key does not log in"
}

run() {
  case "$1" in
    save)         save ;;
    commit)       COMMIT_ONLY=1; save ;;
    deploy)       tool deploy $ARG --ask ;;
    status)       tool status $ARG --ask ;;
    pull)         pull ;;
    pull-data)    tool pull-data $ARG --ask ;;
    servers)      tool servers ;;
    logout)       logout ;;
    quick)        QUICK=1; save ;;
    quick-commit) QUICK=1; COMMIT_ONLY=1; save ;;
    *)            return 2 ;;
  esac
}

if [ -n "${1:-}" ]; then
  run "$1"; rc=$?
  [ $rc = 2 ] && sed -n '2,17p' "$0"
  exit $rc
fi

while :; do
  cat <<'EOF'

=== tunebox ===

  1  commit      add + commit, no push
  2  save        add + commit + push to GitHub, then deploy to the default server if it is reachable
  3  deploy      upload what changed to a server (no git)
  4  status      what differs on a server (changes nothing)
  5  pull        git pull
  6  pull data   copy a server's live data into dev/data
  7  servers     list, add or remove servers
  8  logout      forget the server address + SSH user
  9  quit

EOF
  printf 'select [1-9]: '; read -r c || exit 0
  case "$c" in
    1) run commit; exit $? ;;
    2) run save; exit $? ;;
    3) run deploy; exit $? ;;
    4) run status; exit $? ;;
    5) run pull; exit $? ;;
    6) run pull-data; exit $? ;;
    7) run servers; exit $? ;;
    8) run logout; exit $? ;;
    9) exit 0 ;;
    *) echo "[err]   invalid choice" ;;
  esac
done

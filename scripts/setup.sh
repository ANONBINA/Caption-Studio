#!/bin/bash
# setup.sh — one-shot environment setup for Caption Studio.
# Idempotent: safe to re-run; it only performs the steps that are still missing.
#
# Usage:  bash scripts/setup.sh
#         bash scripts/setup.sh --dev       (also install pytest/ruff/httpx)
#         bash scripts/setup.sh --qrcode    (also install qrcode — QR for phone access)

set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n\033[1;36m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[0;32m  ✔\033[0m %s\n' "$1"; }
warn() { printf '\033[0;33m  ⚠\033[0m %s\n' "$1"; }
die()  { printf '\033[0;31m  ✖ %s\033[0m\n' "$1" >&2; exit 1; }

WITH_DEV=0
WITH_QR=0
for arg in "$@"; do
  case "$arg" in
    --dev)    WITH_DEV=1 ;;
    --qrcode) WITH_QR=1 ;;
  esac
done

# ---------------------------------------------------------------- prerequisites
step "Checking prerequisites"
PY=""
# Windows ships a fake `python` Store stub; prefer the real launcher when present.
if command -v py >/dev/null 2>&1 && py -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  PY="py"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  PY="python3"
elif command -v python >/dev/null 2>&1 && python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  PY="python"
else
  die "Python 3.10+ not found. Install it from https://python.org (tick 'Add to PATH')"
fi
ok "$("$PY" --version)"

# ---------------------------------------------------------------- virtualenv
step "Virtual environment (.venv)"
if [ ! -f .venv/bin/python ] && [ ! -f .venv/Scripts/python.exe ]; then
  "$PY" -m venv .venv
  ok "created .venv"
else
  ok "already exists"
fi
if [ -f .venv/bin/python ]; then
  VPY=".venv/bin/python"
else
  VPY=".venv/Scripts/python.exe"
fi

# ---------------------------------------------------------------- dependencies
step "Installing the app (editable, with web deps)"
"$VPY" -m pip install --quiet --upgrade pip
if [ "$WITH_DEV" = "1" ]; then
  "$VPY" -m pip install --quiet -e ".[web,dev]"
  ok "installed .[web,dev] (pytest + ruff included)"
else
  "$VPY" -m pip install --quiet -e ".[web]"
  ok "installed .[web]"
  warn "pass --dev to also install pytest/ruff"
fi

step "QR code support (for phone access)"
if [ "$WITH_QR" = "1" ]; then
  "$VPY" -m pip install --quiet qrcode
  ok "installed qrcode"
else
  if "$VPY" -c "import qrcode" 2>/dev/null; then
    ok "qrcode already installed"
  else
    warn "not installed — run with --qrcode to get a scannable QR for your phone"
  fi
fi

# ---------------------------------------------------------------- config
step "Config file (config.json)"
if [ -f config.json ]; then
  ok "already exists — left untouched (it holds your TMDB key / merge rules)"
else
  cp config.example.json config.json
  ok "created from config.example.json"
fi

# ---------------------------------------------------------------- data dir
step "Data directory"
mkdir -p data
if compgen -G "data/*.csv" > /dev/null; then
  ok "catalog present: $(ls data/*.csv | wc -l) file(s)"
else
  warn "no catalog CSV in data/ yet — drop a scanner catalog there or use Import CSV in the UI"
fi

# ---------------------------------------------------------------- verify
step "Verifying"
"$VPY" -c "import caption_studio; print('caption-studio import OK')"
"$VPY" -m caption_studio.cli stats | head -n 5 || true

echo
step "Done"
echo "  Start the web app:  bash scripts/serve.sh      (http://127.0.0.1:8000)"
echo "  Mobile/phone mode:  bash scripts/serve.sh --lan  (QR + LAN URL)"
echo "  Run the tests:      bash scripts/test.sh"
echo "  Set a TMDB key:     Settings → TMDB in the UI, or export TMDB_API_KEY=..."

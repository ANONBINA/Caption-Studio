#!/bin/bash
# serve.sh — launch the Caption Studio web app.
# Re-runs setup automatically if .venv is missing.
#
# Usage:
#   bash scripts/serve.sh            Desktop mode — http://127.0.0.1:8000 (loopback only)
#   bash scripts/serve.sh --lan      Mobile mode  — binds LAN + prints a QR code for your phone
#   bash scripts/serve.sh 0.0.0.0    Same as --lan (explicit host also enables mobile mode)
#
# Mobile mode:
#   • Detects this PC's LAN IP automatically (scripts/lan_ip.py)
#   • Adds it to CAPTION_STUDIO_ALLOWED_HOSTS so the app accepts the Host header
#   • Reminds you about the Windows Firewall prompt (must click Allow)

set -euo pipefail
cd "$(dirname "$0")/.."

# Ensure .venv exists (runs the same setup the README describes)
if [ ! -f .venv/bin/python ] && [ ! -f .venv/Scripts/python.exe ]; then
  echo "No .venv found — running setup first..."
  bash scripts/setup.sh
fi
if [ -f .venv/bin/python ]; then
  VPY=".venv/bin/python"
else
  VPY=".venv/Scripts/python.exe"
fi

HOST="127.0.0.1"
MODE="desktop"
if [ "${1:-}" = "--lan" ]; then
  HOST="0.0.0.0"
  MODE="lan"
elif [ -n "${1:-}" ]; then
  HOST="$1"
  MODE="lan"
fi
PORT="${2:-8000}"

# ---------------------------------------------------------------- mobile mode
if [ "$MODE" = "lan" ]; then
  LAN_IP="$("$VPY" scripts/lan_ip.py 2>/dev/null || true)"
  if [ -z "$LAN_IP" ]; then
    echo "⚠ Could not auto-detect your LAN IP. Find it with 'ipconfig' and add it to"
    echo "  CAPTION_STUDIO_ALLOWED_HOSTS, e.g.:  export CAPTION_STUDIO_ALLOWED_HOSTS=192.168.1.50"
  else
    export CAPTION_STUDIO_ALLOWED_HOSTS="${CAPTION_STUDIO_ALLOWED_HOSTS:+$CAPTION_STUDIO_ALLOWED_HOSTS,}$LAN_IP"
    echo ""
    echo "  📱 MOBILE MODE — open this on your phone (same Wi-Fi):"
    echo "     http://$LAN_IP:$PORT"
    # Cosmetic only — a QR display problem must never stop the server.
    "$VPY" scripts/print_qr.py "http://$LAN_IP:$PORT" \
      || echo "     (QR not available — type the URL above instead)"
    echo ""
    echo "  ⚠ Every device on this network can read/change the library — no login."
    echo "  ⚠ If Windows Firewall asks, click ALLOW for Python/private networks."
    echo "  ⚠ Phone must be on the same Wi-Fi (not guest/mobile hotspot)."
    echo ""
  fi
fi

if [ "$HOST" = "127.0.0.1" ]; then
  echo "Caption Studio → http://$HOST:$PORT  (Ctrl+C to stop)"
else
  echo "Caption Studio listening on $HOST:$PORT  (Ctrl+C to stop)"
fi
exec "$VPY" -m uvicorn caption_studio.app:create_app --factory \
  --host "$HOST" --port "$PORT"

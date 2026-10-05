#!/bin/bash
# test.sh — lint + test the project inside the project's venv.
#
# Usage:  bash scripts/test.sh          (pytest + ruff, as documented in the README)
#         bash scripts/test.sh quick    (pytest only)

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .venv/bin/python ] && [ ! -f .venv/Scripts/python.exe ]; then
  echo "No .venv found — running setup --dev first..."
  bash scripts/setup.sh --dev
fi
if [ -f .venv/bin/python ]; then
  VPY=".venv/bin/python"
else
  VPY=".venv/Scripts/python.exe"
fi

if [ "${1:-}" = "quick" ]; then
  exec "$VPY" -m pytest
fi
exec "$VPY" -m pytest && exec "$VPY" -m ruff check caption_studio tests

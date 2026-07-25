#!/bin/bash
# Rau launcher
#   bash launch.sh              # hub + face (voice)
#   bash launch.sh --hub        # hub + UI only
#   bash launch.sh --text       # hub only (dashboard / API)
#   bash launch.sh --no-audio   # hub + face control loop without mic

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

MODE="all"
NO_AUDIO=""
for arg in "$@"; do
  case "$arg" in
    --hub|--eyes-only) MODE="hub" ;;
    --text|--text-only) MODE="text" ;;
    --face) MODE="face" ;;
    --no-audio) NO_AUDIO="--no-audio" ;;
  esac
done

if [ ! -d "$ROOT/venv" ]; then
  echo "Creating venv..."
  PY=python3
  if command -v python3.11 >/dev/null 2>&1; then PY=python3.11; fi
  "$PY" -m venv "$ROOT/venv"
fi
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
pip install -q -r "$ROOT/requirements.txt"

WEB_INDEX="$ROOT/web/dist/index.html"
if [ ! -f "$WEB_INDEX" ] || find "$ROOT/web/src" "$ROOT/web/package.json" "$ROOT/web/vite.config.ts" -newer "$WEB_INDEX" -print -quit | grep -q .; then
  echo "Building web UI..."
  (cd "$ROOT/web" && npm ci && npm run build)
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting Rau ($MODE)..."
exec python -m rau "$MODE" $NO_AUDIO

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

if [ ! -x "$ROOT/venv/bin/python" ]; then
  echo "Rau is not installed. Run: bash scripts/setup.sh --all" >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"

WEB_INDEX="$ROOT/web/dist/index.html"
if [ ! -f "$WEB_INDEX" ]; then
  echo "Web UI is not built. Run: bash scripts/setup.sh --web" >&2
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting Rau ($MODE)..."
exec python -m rau "$MODE" $NO_AUDIO

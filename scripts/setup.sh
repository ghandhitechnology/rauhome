#!/bin/bash
# Explicit dependency/setup entrypoint. Normal Rau startup never installs.
set -euo pipefail

RAU_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAU_EXTRA=""
INSTALL_WEB=0
INSTALL_PI=0
INSTALL_CHESS=0
for arg in "$@"; do
  case "$arg" in
    --voice) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}local-voice" ;;
    --computer-use) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}computer-use" ;;
    --pi) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}pi"; INSTALL_PI=1 ;;
    --chess) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}chess"; INSTALL_CHESS=1 ;;
    --web) INSTALL_WEB=1 ;;
    --all) RAU_EXTRA="local-voice,computer-use,pi,chess"; INSTALL_WEB=1; INSTALL_PI=1; INSTALL_CHESS=1 ;;
  esac
done

if [ ! -d "$RAU_ROOT/venv" ]; then
  python3 -m venv "$RAU_ROOT/venv"
fi
RAU_PY="$RAU_ROOT/venv/bin/python"
if [ -n "$RAU_EXTRA" ]; then
  "$RAU_PY" -m pip install -e "$RAU_ROOT[$RAU_EXTRA]"
else
  "$RAU_PY" -m pip install -e "$RAU_ROOT"
fi

if [ "$INSTALL_WEB" -eq 1 ]; then
  (cd "$RAU_ROOT/web" && npm ci && npm run build)
fi
if [ "$INSTALL_PI" -eq 1 ]; then
  (cd "$RAU_ROOT/pi-sidecar" && npm ci)
fi
# The engine is a binary, not a wheel. Missing it is survivable — he declines a
# game rather than crashing — so a machine without brew gets told what to do
# instead of having the whole setup fail underneath it.
if [ "$INSTALL_CHESS" -eq 1 ]; then
  if command -v stockfish >/dev/null 2>&1; then
    echo "Stockfish already present: $(command -v stockfish)"
  elif command -v brew >/dev/null 2>&1; then
    brew install stockfish
  else
    echo "No Homebrew here. Install Stockfish yourself and either put it on PATH"
    echo "or point \$STOCKFISH_PATH at it. Until then Rau will decline a game."
  fi
fi
echo "Rau setup complete."

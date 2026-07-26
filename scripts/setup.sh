#!/bin/bash
# Explicit dependency/setup entrypoint. Normal Rau startup never installs.
set -euo pipefail

RAU_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAU_EXTRA=""
INSTALL_WEB=0
INSTALL_PI=0
for arg in "$@"; do
  case "$arg" in
    --voice) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}local-voice" ;;
    --computer-use) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}computer-use" ;;
    --pi) RAU_EXTRA="${RAU_EXTRA:+$RAU_EXTRA,}pi"; INSTALL_PI=1 ;;
    --web) INSTALL_WEB=1 ;;
    --all) RAU_EXTRA="local-voice,computer-use,pi"; INSTALL_WEB=1; INSTALL_PI=1 ;;
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
echo "Rau setup complete."

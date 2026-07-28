"""
Where Stockfish is, if it is anywhere.

Every other module in this layer is written as though the engine exists. This one
is the only place allowed to find out that it does not, and it answers with
`None` rather than an exception, because a machine without Stockfish installed is
not a broken machine — it is a machine where Rau declines the game. If a missing
binary raised, the traceback would surface wherever the question happened to be
asked first: a websocket handler, the doctor, a tool call from the face brain.
Three places would each need their own guard and one of them would forget.

So the contract here is narrow and dull on purpose. `found()` is cheap, cached,
and never spawns anything — it is safe to call on a hot path. `probe()` is the
expensive one that actually runs the binary to confirm it speaks UCI, and it is
what the doctor calls; it is cached too, because starting a chess engine to
answer a health check is not free and the answer does not change while the
process lives.

Resolution order is deliberate: an explicit `$STOCKFISH_PATH` beats whatever is
on `PATH`, and the Homebrew location is only a last resort, so somebody who
installed a particular build somewhere particular always gets that build.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Optional

#: Set this to pin a specific build. Checked before PATH so a deliberate choice
#: always wins over whatever happens to be installed.
ENV_VAR = "STOCKFISH_PATH"

#: Where Homebrew puts it on this machine. Tried last, never first — finding it
#: here is a fallback, not a preference.
FALLBACK = "/opt/homebrew/bin/stockfish"

#: The probe runs the binary and waits for it to say hello. Generous, because a
#: cold start off a sleeping disk is slow, but bounded, because a hung engine
#: must not hang the doctor.
PROBE_TIMEOUT_SEC = 5.0

_lock = threading.RLock()
_path: Optional[str] = None
_path_resolved = False
_probe: Optional[Dict[str, Any]] = None


def _usable(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def found(*, refresh: bool = False) -> Optional[str]:
    """
    Absolute path to a Stockfish that exists and is executable, or None.

    Never raises and never runs the binary. `None` is a normal answer.
    """
    global _path, _path_resolved
    with _lock:
        if _path_resolved and not refresh:
            return _path
        candidates = (
            os.environ.get(ENV_VAR),
            shutil.which("stockfish"),
            FALLBACK,
        )
        _path = next((p for p in (_usable(c) for c in candidates) if p), None)
        _path_resolved = True
        return _path


def probe(*, refresh: bool = False) -> Dict[str, Any]:
    """
    Confirm the binary actually starts and speaks UCI. For the doctor.

    Returns `{"ok", "path", "detail"}`. A failure is reported, not raised — this
    is a diagnostic, and a diagnostic that throws is worse than useless.
    """
    global _probe
    with _lock:
        if _probe is not None and not refresh:
            return dict(_probe)

    path = found(refresh=refresh)
    if not path:
        result = {
            "ok": False,
            "path": None,
            "detail": f"no stockfish on PATH, in ${ENV_VAR}, or at {FALLBACK}",
        }
    else:
        try:
            proc = subprocess.run(
                [path],
                input="uci\nquit\n",
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_SEC,
            )
            line = next(
                (ln.strip() for ln in proc.stdout.splitlines() if ln.startswith("id name")),
                "",
            )
            result = {
                "ok": bool(line),
                "path": path,
                "detail": line[len("id name ") :] if line else "started but never identified itself",
            }
        except Exception as exc:
            # Deliberately broad: a binary that is the wrong architecture, is
            # quarantined by Gatekeeper, or hangs on start all fail differently
            # and all mean the same thing to the caller — no engine today.
            result = {"ok": False, "path": path, "detail": f"{type(exc).__name__}: {exc}"}

    with _lock:
        _probe = result
    return dict(result)


def forget() -> None:
    """Drop both caches. For tests, and for anyone who just installed it."""
    global _path, _path_resolved, _probe
    with _lock:
        _path = None
        _path_resolved = False
        _probe = None

"""Desktop pet companion process helpers."""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rau.paths import ROOT

_pet_proc: Optional[subprocess.Popen] = None
_atexit_registered = False


def pet_binary() -> Optional[Path]:
    """Return the built Tauri pet binary if present."""
    env = os.environ.get("RAU_PET_BIN", "").strip()
    if env:
        try:
            path = Path(env).expanduser()
        except RuntimeError:
            # An unresolvable "~someone" in the override must not take down
            # whatever is asking whether a pet exists.
            return None
        if path.is_file() and os.access(path, os.X_OK):
            return path
        return None
    candidates = [
        ROOT / "pet" / "src-tauri" / "target" / "release" / "rau-pet",
        ROOT / "pet" / "src-tauri" / "target" / "debug" / "rau-pet",
        ROOT / "dist" / "rau-pet",
    ]
    # macOS .app bundle
    app = ROOT / "pet" / "src-tauri" / "target" / "release" / "bundle" / "macos" / "Rau Pet.app"
    if app.is_dir():
        mac_bin = app / "Contents" / "MacOS" / "rau-pet"
        if mac_bin.is_file():
            return mac_bin
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def pet_enabled() -> bool:
    flag = os.environ.get("RAU_PET", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def start_pet(hub_url: str = "http://127.0.0.1:8765") -> Optional[subprocess.Popen]:
    """Spawn the desktop pet if built and enabled. No-op otherwise."""
    global _pet_proc
    if not pet_enabled():
        return None
    if _pet_proc is not None and _pet_proc.poll() is None:
        return _pet_proc
    binary = pet_binary()
    if binary is None:
        return None
    env = os.environ.copy()
    env["RAU_HUB_URL"] = hub_url
    try:
        _pet_proc = subprocess.Popen(
            [str(binary)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        _pet_proc = None
        return None
    global _atexit_registered
    if not _atexit_registered:
        # Once, not once per start: a pet restarted a dozen times would
        # otherwise queue a dozen identical shutdown hooks.
        atexit.register(stop_pet)
        _atexit_registered = True
    return _pet_proc


def stop_pet() -> None:
    global _pet_proc
    proc = _pet_proc
    _pet_proc = None
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "darwin":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    deadline = time.time() + 2.0
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            if sys.platform == "darwin":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        # Reap it. Without this the killed pet lingers as a zombie for as long
        # as the hub keeps running.
        proc.wait(timeout=1.0)
    except (subprocess.TimeoutExpired, OSError):
        pass

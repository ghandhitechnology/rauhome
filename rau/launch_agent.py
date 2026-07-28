"""Install and inspect Rau's single macOS LaunchAgent."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from rau.paths import MEMORIES_DIR, ROOT

LABEL = "com.rau.harness"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SERVICE_MODES = {"all", "hub", "text"}


def definition(mode: str = "all", no_audio: bool = False) -> Dict[str, Any]:
    if mode not in SERVICE_MODES:
        raise ValueError(f"unsupported LaunchAgent mode: {mode}")
    argv = [sys.executable, "-m", "rau", mode]
    if mode == "all" and no_audio:
        argv.append("--no-audio")
    return {
        "Label": LABEL,
        "ProgramArguments": argv,
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(MEMORIES_DIR / "launchagent.out.log"),
        "StandardErrorPath": str(MEMORIES_DIR / "launchagent.err.log"),
        "EnvironmentVariables": {
            "PYTHONPATH": str(ROOT),
            "RAU_RUNTIME": "1",
        },
    }


def status() -> Dict[str, Any]:
    installed = PLIST_PATH.is_file()
    loaded = False
    detail = ""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        loaded = result.returncode == 0
        detail = (result.stderr or result.stdout)[-500:]
    return {
        "ok": installed and (loaded if sys.platform == "darwin" else True),
        "installed": installed,
        "loaded": loaded,
        "path": str(PLIST_PATH),
        "label": LABEL,
        "detail": detail.strip(),
    }


def install(mode: str = "all", no_audio: bool = False) -> Dict[str, Any]:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent installation is available only on macOS")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{LABEL}.", suffix=".plist", dir=PLIST_PATH.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(definition(mode=mode, no_audio=no_audio), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, PLIST_PATH)
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(PLIST_PATH)],
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(PLIST_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "bootstrap failed").strip())
    subprocess.run(
        ["launchctl", "enable", f"{domain}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    return status()


def remove() -> Dict[str, Any]:
    if sys.platform == "darwin":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST_PATH)],
            capture_output=True,
            check=False,
        )
    existed = PLIST_PATH.exists()
    PLIST_PATH.unlink(missing_ok=True)
    return {"ok": True, "removed": existed, "path": str(PLIST_PATH)}

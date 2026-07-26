"""Lazy lifecycle supervision for the optional Pi sidecar."""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rau.paths import ROOT
from rau.pi.client import PiSidecar
from rau.providers.registry import load_settings


class PiSupervisor:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._last_used = 0.0
        self._registered = False

    def enabled(self) -> bool:
        env = os.environ.get("PI_EXECUTOR_ENABLED")
        if env is not None:
            return env.strip().lower() in {"1", "true", "yes", "on"}
        return bool(load_settings().get("pi_executor_enabled", False))

    def health(self) -> Dict[str, Any]:
        client = PiSidecar()
        try:
            health = client.health()
            return {"ok": bool(health.get("ok")), **health}
        except Exception as exc:
            return {
                "ok": False,
                "enabled": self.enabled(),
                "error": str(exc)[:500],
            }

    def ensure_running(self, *, timeout: float = 8.0) -> PiSidecar:
        if not self.enabled():
            raise RuntimeError("Pi executor is disabled")
        client = PiSidecar()
        if client.available():
            self._last_used = time.time()
            return client
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                node = shutil.which("node")
                entry = ROOT / "pi-sidecar" / "src" / "server.mjs"
                modules = ROOT / "pi-sidecar" / "node_modules"
                if not node or not entry.is_file() or not modules.is_dir():
                    raise RuntimeError(
                        "Pi sidecar is not installed; run setup for the optional Pi worker"
                    )
                self._process = subprocess.Popen(
                    [node, str(entry)],
                    cwd=str(ROOT / "pi-sidecar"),
                    env=os.environ.copy(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                if not self._registered:
                    atexit.register(self.stop)
                    self._registered = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if client.available():
                self._last_used = time.time()
                return client
            proc = self._process
            if proc is not None and proc.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError("Pi sidecar did not become healthy")

    def touch(self) -> None:
        self._last_used = time.time()

    def stop_if_idle(self, idle_sec: float = 300.0) -> bool:
        with self._lock:
            if not self._process or self._process.poll() is not None:
                return False
            if time.time() - self._last_used < idle_sec:
                return False
        self.stop()
        return True

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


PI_SUPERVISOR = PiSupervisor()

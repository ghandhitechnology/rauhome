"""Read-only operational diagnostics for the durable Rau runtime."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from typing import Any, Dict, List


def _check(name: str, ok: bool, detail: str, *, required: bool = True) -> Dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "required": required,
        "detail": str(detail)[:1000],
    }


def run_doctor() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    try:
        from rau.control import control_store
        from rau.control.store import SCHEMA_VERSION

        schema = control_store.schema_status()
        checks.append(
            _check(
                "database migrations",
                schema.get("schema_version") == SCHEMA_VERSION,
                f"schema v{schema.get('schema_version')} at {schema.get('path')}",
            )
        )
    except Exception as exc:
        checks.append(_check("database migrations", False, str(exc)))

    try:
        from rau.scheduler import SCHEDULER

        status = SCHEDULER.status()
        checks.append(
            _check(
                "scheduler",
                bool(status.get("running")) or not _runtime_expected(),
                f"running={status.get('running')} next={status.get('next_run_at')}",
            )
        )
    except Exception as exc:
        checks.append(_check("scheduler", False, str(exc)))

    try:
        from rau.pi.supervisor import PI_SUPERVISOR

        pi = PI_SUPERVISOR.health()
        enabled = PI_SUPERVISOR.enabled()
        checks.append(
            _check(
                "Pi sidecar",
                bool(pi.get("ok")) if enabled else True,
                "disabled (starts on demand)" if not enabled else str(pi),
                required=False,
            )
        )
    except Exception as exc:
        checks.append(_check("Pi sidecar", False, str(exc), required=False))

    accessibility = False
    screen_recording = False
    displays = 0
    try:
        from rau.computer.cua import cua_status

        computer = cua_status()
        accessibility = bool(computer.get("accessibility"))
        screen_recording = bool(computer.get("screen_recording"))
        displays = len(computer.get("displays") or [])
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            import ApplicationServices as AS  # type: ignore

            accessibility = bool(AS.AXIsProcessTrusted()) or accessibility
        except Exception:
            pass
        try:
            import Quartz  # type: ignore

            screen_recording = bool(Quartz.CGPreflightScreenCaptureAccess()) or screen_recording
            raw = Quartz.CGGetActiveDisplayList(32, None, None)
            if isinstance(raw, tuple):
                for value in raw:
                    if isinstance(value, (list, tuple)):
                        displays = max(displays, len(value))
                        break
                    if isinstance(value, int) and value > displays:
                        displays = max(displays, value)
        except Exception:
            pass
    checks.extend(
        [
            _check("Accessibility", accessibility, "trusted" if accessibility else "permission missing"),
            _check("Screen Recording", screen_recording, "allowed" if screen_recording else "permission missing"),
            _check("displays", displays > 0, f"{displays} active display(s)"),
            _check(
                "computer sandbox",
                bool(shutil.which("sandbox-exec")) if sys.platform == "darwin" else True,
                shutil.which("sandbox-exec") or "not available",
            ),
        ]
    )

    microphone_detail = "sounddevice extra is not installed"
    microphone_ok = False
    try:
        import sounddevice as sd  # type: ignore

        device = sd.query_devices(kind="input")
        microphone_detail = str(device.get("name") or "input available")
        microphone_ok = True
    except Exception as exc:
        microphone_detail = str(exc)
    checks.append(_check("microphone", microphone_ok, microphone_detail, required=False))

    from rau.providers.registry import provider_status

    providers = provider_status()
    configured = sorted(name for name, meta in providers.items() if meta.get("configured"))
    checks.append(
        _check(
            "model credentials",
            bool(configured),
            f"configured: {', '.join(configured)}" if configured else "no provider key configured",
        )
    )
    from rau.launch_agent import status as launch_status

    launch = launch_status()
    checks.append(
        _check(
            "LaunchAgent",
            bool(launch.get("ok")),
            f"installed={launch.get('installed')} loaded={launch.get('loaded')} path={launch.get('path')}",
            required=False,
        )
    )
    # Not required: without it he simply declines a game of chess, which is a
    # sentence rather than a fault. Reported so that "he won't play me" has an
    # answer that is not guesswork.
    try:
        from rau.games.chess import binary as chess_binary

        engine = chess_binary.probe()
        detail = str(engine.get("detail") or "stockfish not found")
        if engine.get("ok") and engine.get("path"):
            detail = f"{detail} at {engine['path']}"
        checks.append(_check("chess engine", bool(engine.get("ok")), detail, required=False))
    except Exception as exc:
        checks.append(_check("chess engine", False, str(exc), required=False))

    missing_extras = [
        name
        for name in ("faster_whisper", "silero_vad", "Quartz", "ApplicationServices")
        if importlib.util.find_spec(name) is None
    ]
    if importlib.util.find_spec("chess") is None:
        missing_extras.append("chess")
    return {
        "ok": all(check["ok"] for check in checks if check["required"]),
        "checks": checks,
        "missing_optional_modules": missing_extras,
    }


def _runtime_expected() -> bool:
    import os

    return os.environ.get("RAU_RUNTIME") == "1"


def format_report(report: Dict[str, Any]) -> str:
    lines = ["Rau doctor"]
    for check in report["checks"]:
        mark = "OK" if check["ok"] else ("WARN" if not check["required"] else "FAIL")
        lines.append(f"[{mark:4}] {check['name']}: {check['detail']}")
    lines.append("healthy" if report["ok"] else "required checks failed")
    return "\n".join(lines)

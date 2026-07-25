"""Anthropic-style computer-use actions (macOS)."""
from __future__ import annotations

import base64
import math
import os
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple

from rau.memory.store import append_trace

AUTOMATION_TIMEOUT_SEC = 15
MAX_WAIT_SEC = 30.0
MAX_TEXT_CHARS = 20_000
MAX_COORDINATE = 100_000

def capture_screenshot_b64() -> str:
    """Capture main display to PNG base64 via screencapture."""
    try:
        fd, path = tempfile.mkstemp(prefix="rau-cua-", suffix=".png")
        os.close(fd)
    except OSError:
        return ""
    try:
        result = subprocess.run(
            ["screencapture", "-x", "-C", path],
            check=False,
            capture_output=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            return ""
        with open(path, "rb") as image:
            data = image.read()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return base64.b64encode(data).decode("ascii")


def _osascript(script: str) -> Tuple[int, str]:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "osascript is unavailable"
    except subprocess.TimeoutExpired:
        return 124, "osascript timed out"


def _click(x: int, y: int, double: bool = False) -> Tuple[bool, str]:
    # cliclick if available; else AppleScript System Events is limited —
    # use Python Quartz when possible.
    try:
        import Quartz  # type: ignore

        point = Quartz.CGPointMake(float(x), float(y))
        events = [
            Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseDown, point, Quartz.kCGMouseButtonLeft
            ),
            Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseUp, point, Quartz.kCGMouseButtonLeft
            ),
        ]
        for ev in events:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.01)
        if double:
            for ev in events:
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
                time.sleep(0.01)
        return True, ""
    except Exception:
        pass
    kind = "dc" if double else "c"
    try:
        result = subprocess.run(
            ["cliclick", f"{kind}:{x},{y}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return False, "neither Quartz nor cliclick is available"
    except subprocess.TimeoutExpired:
        return False, "cliclick timed out"
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def _apple_string(text: str) -> str:
    """Quote untrusted text as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _type_text(text: str) -> Tuple[bool, str]:
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    code, output = _osascript(f'tell application "System Events" to keystroke "{safe}"')
    return code == 0, output


def _key(key: str) -> Tuple[bool, str]:
    mapping = {
        "return": "return",
        "enter": "return",
        "tab": "tab",
        "escape": "escape",
        "delete": "delete",
        "space": "space",
    }
    normalized = key.lower().strip()
    code = mapping.get(normalized)
    if code is None:
        # Arbitrary strings used to be interpolated directly into AppleScript,
        # which made the key action a script-injection surface.
        if len(key) != 1 or ord(key) < 32:
            return False, f"unsupported key: {key[:40]}"
        script = f'tell application "System Events" to keystroke {_apple_string(key)}'
    elif code == "return":
        script = 'tell application "System Events" to key code 36'
    else:
        script = f'tell application "System Events" to keystroke {_apple_string(code)}'
    status, output = _osascript(script)
    return status == 0, output


def _int_field(action: Dict[str, Any], name: str, default: int = 0) -> int:
    value = action.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if abs(parsed) > MAX_COORDINATE:
        raise ValueError(f"{name} is outside the supported range")
    return parsed


def _seconds(value: Any, default: float = 0.5) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        raise ValueError("seconds must be a number") from None
    if not math.isfinite(parsed) or not 0 <= parsed <= MAX_WAIT_SEC:
        raise ValueError(f"seconds must be between 0 and {MAX_WAIT_SEC:g}")
    return parsed


def execute_action(
    action: Dict[str, Any],
    cancel: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    action schema:
      { "action": "screenshot"|"click"|"double_click"|"type"|"key"|"scroll"|"wait",
        "x": int, "y": int, "text": str, "key": str, "dy": int, "seconds": float }
    """
    if not isinstance(action, dict):
        return {"action": "unknown", "ok": False, "error": "action must be an object"}
    raw_kind = action.get("action") or action.get("type") or "screenshot"
    if not isinstance(raw_kind, str):
        return {"action": "unknown", "ok": False, "error": "action name must be a string"}
    kind = raw_kind.lower()
    result: Dict[str, Any] = {"action": kind, "ok": True}

    try:
        if cancel is not None and cancel.is_set():
            result["ok"] = False
            result["cancelled"] = True
            result["error"] = "action cancelled"
        elif kind == "screenshot":
            image = capture_screenshot_b64()
            if image:
                result["image_b64"] = image
            else:
                result.update(ok=False, error="screenshot capture failed")
        elif kind in ("click", "double_click"):
            ok, detail = _click(
                _int_field(action, "x"),
                _int_field(action, "y"),
                double=kind == "double_click",
            )
            if not ok:
                result.update(ok=False, error=detail or "click failed")
        elif kind == "type":
            text = action.get("text") or ""
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            if len(text) > MAX_TEXT_CHARS:
                raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")
            ok, detail = _type_text(text)
            if not ok:
                result.update(ok=False, error=detail or "typing failed")
        elif kind == "key":
            key = action.get("key") or "return"
            if not isinstance(key, str):
                raise ValueError("key must be a string")
            ok, detail = _key(key)
            if not ok:
                result.update(ok=False, error=detail or "key action failed")
        elif kind == "scroll":
            dy = _int_field(action, "dy", int(action.get("amount") or -3))
            try:
                import Quartz  # type: ignore

                ev = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 1, dy
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            except Exception as e:
                result.update(ok=False, error=str(e))
        elif kind == "wait":
            seconds = _seconds(action.get("seconds"), 0.5)
            if cancel is not None and cancel.wait(timeout=seconds):
                result.update(ok=False, cancelled=True, error="action cancelled")
            elif cancel is None:
                time.sleep(seconds)
        elif kind == "drag":
            # The fallback remains two clicks when Quartz is absent, but now
            # reports either failed endpoint rather than claiming success.
            first, detail = _click(_int_field(action, "x"), _int_field(action, "y"))
            if first and not (cancel and cancel.wait(timeout=0.05)):
                second, second_detail = _click(
                    _int_field(action, "x2"), _int_field(action, "y2")
                )
                if not second:
                    result.update(ok=False, error=second_detail or "drag endpoint failed")
            elif not first:
                result.update(ok=False, error=detail or "drag start failed")
            else:
                result.update(ok=False, cancelled=True, error="action cancelled")
        else:
            result.update(ok=False, error=f"unknown action {kind}")
    except (TypeError, ValueError, OverflowError) as exc:
        result.update(ok=False, error=str(exc))

    append_trace("cua", {"action": kind, "ok": result.get("ok")})
    # Don't persist huge screenshots in return to LLM beyond a flag
    if "image_b64" in result and len(result["image_b64"]) > 200:
        result["image_b64_len"] = len(result["image_b64"])
        # keep truncated marker for logs; full image returned to caller if needed
    return result

"""Anthropic-style computer-use actions (macOS)."""
from __future__ import annotations

import base64
import io
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from rau.memory.store import append_trace


def capture_screenshot_b64() -> str:
    """Capture main display to PNG base64 via screencapture."""
    path = "/tmp/rau-cua.png"
    subprocess.run(
        ["screencapture", "-x", "-C", path],
        check=False,
        capture_output=True,
    )
    try:
        data = open(path, "rb").read()
    except OSError:
        data = b""
    return base64.b64encode(data).decode("ascii")


def _osascript(script: str) -> Tuple[int, str]:
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout or r.stderr or "").strip()


def _click(x: int, y: int, double: bool = False) -> None:
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
        return
    except Exception:
        pass
    kind = "dc" if double else "c"
    subprocess.run(["cliclick", f"{kind}:{x},{y}"], check=False, capture_output=True)


def _type_text(text: str) -> None:
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(f'tell application "System Events" to keystroke "{safe}"')


def _key(key: str) -> None:
    mapping = {
        "return": "return",
        "enter": "return",
        "tab": "tab",
        "escape": "escape",
        "delete": "delete",
        "space": "space",
    }
    code = mapping.get(key.lower(), key)
    _osascript(f'tell application "System Events" to key code 36' if code == "return"
               else f'tell application "System Events" to keystroke "{code}"')


def execute_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    action schema:
      { "action": "screenshot"|"click"|"double_click"|"type"|"key"|"scroll"|"wait",
        "x": int, "y": int, "text": str, "key": str, "dy": int, "seconds": float }
    """
    kind = (action.get("action") or action.get("type") or "screenshot").lower()
    result: Dict[str, Any] = {"action": kind, "ok": True}

    if kind == "screenshot":
        result["image_b64"] = capture_screenshot_b64()
    elif kind == "click":
        _click(int(action.get("x", 0)), int(action.get("y", 0)), double=False)
    elif kind == "double_click":
        _click(int(action.get("x", 0)), int(action.get("y", 0)), double=True)
    elif kind == "type":
        _type_text(str(action.get("text") or ""))
    elif kind == "key":
        _key(str(action.get("key") or "return"))
    elif kind == "scroll":
        dy = int(action.get("dy") or action.get("amount") or -3)
        try:
            import Quartz  # type: ignore

            ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, dy)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)
    elif kind == "wait":
        time.sleep(float(action.get("seconds") or 0.5))
    elif kind == "drag":
        # simplified: click start then click end
        _click(int(action.get("x", 0)), int(action.get("y", 0)))
        time.sleep(0.05)
        _click(int(action.get("x2", 0)), int(action.get("y2", 0)))
    else:
        result["ok"] = False
        result["error"] = f"unknown action {kind}"

    append_trace("cua", {"action": kind, "ok": result.get("ok")})
    # Don't persist huge screenshots in return to LLM beyond a flag
    if "image_b64" in result and len(result["image_b64"]) > 200:
        result["image_b64_len"] = len(result["image_b64"])
        # keep truncated marker for logs; full image returned to caller if needed
    return result

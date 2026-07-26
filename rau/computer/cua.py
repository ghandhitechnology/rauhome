"""macOS computer-use actions for the hard-task subagent.

Coordinates are always **logical points** (Quartz global space). Screenshots
are resized to logical size when Retina scale > 1 so one image pixel ≈ one
point the model should click.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rau.memory.store import append_trace

log = logging.getLogger("rau.computer.cua")

AUTOMATION_TIMEOUT_SEC = 15
#: Probes used only to *report* capability, never to act.
#:
#: An `osascript` that needs Accessibility blocks until it times out when the
#: permission has not been granted — which is exactly the state `cua_status`
#: exists to detect. At the automation timeout that made status, the call the
#: model is told to make first, stall for half a minute before answering the
#: question "am I allowed to do anything?". A probe that has not answered in
#: this long has answered: no.
STATUS_PROBE_TIMEOUT_SEC = 2.0
MAX_WAIT_SEC = 30.0
MAX_TEXT_CHARS = 8_000
TYPE_CHUNK_CHARS = 80
MAX_COORDINATE = 100_000
DRAG_STEPS = 24

#: Actions that get an automatic follow-up screenshot after success.
VERIFY_ACTIONS = frozenset(
    {"click", "double_click", "type", "key", "drag", "move"}
)


# ── geometry / displays ───────────────────────────────────────────────


def _png_pixel_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def _quartz_available() -> bool:
    try:
        import Quartz  # noqa: F401

        return True
    except Exception:
        return False


def _screen_size_via_jxa() -> Tuple[int, int, float]:
    """Best-effort main display logical size without Quartz."""
    script = (
        "ObjC.import('AppKit');"
        "var f=$.NSScreen.mainScreen.frame;"
        "var s=$.NSScreen.mainScreen.backingScaleFactor;"
        "JSON.stringify({w:f.size.width,h:f.size.height,s:s});"
    )
    try:
        r = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
        if r.returncode != 0:
            return 0, 0, 1.0
        import json as _json

        data = _json.loads((r.stdout or "").strip() or "{}")
        return int(data.get("w") or 0), int(data.get("h") or 0), float(data.get("s") or 1.0)
    except Exception:
        return 0, 0, 1.0


def list_displays() -> List[Dict[str, Any]]:
    """Return connected displays with logical bounds and scale."""
    displays: List[Dict[str, Any]] = []
    try:
        import Quartz  # type: ignore

        main_id = int(Quartz.CGMainDisplayID())
        max_displays = 16
        # PyObjC signatures vary; try the common (max, None, None) form.
        result = Quartz.CGGetActiveDisplayList(max_displays, None, None)
        ids: List[int] = []
        if isinstance(result, tuple):
            if len(result) == 3:
                err, raw_ids, count = result
                if int(err) == 0 and raw_ids is not None:
                    ids = [int(raw_ids[i]) for i in range(int(count))]
            elif len(result) == 2:
                raw_ids, count = result
                if raw_ids is not None:
                    ids = [int(raw_ids[i]) for i in range(int(count))]
        if not ids:
            ids = [main_id]
        for did in ids:
            bounds = Quartz.CGDisplayBounds(did)
            logical_w = int(bounds.size.width)
            logical_h = int(bounds.size.height)
            origin_x = int(bounds.origin.x)
            origin_y = int(bounds.origin.y)
            scale = 1.0
            try:
                mode = Quartz.CGDisplayCopyDisplayMode(did)
                if mode is not None:
                    pix_w = float(Quartz.CGDisplayModeGetPixelWidth(mode))
                    if logical_w > 0 and pix_w > 0:
                        scale = round(pix_w / logical_w, 3)
            except Exception:
                pass
            displays.append(
                {
                    "display_id": did,
                    "is_main": did == main_id,
                    "x": origin_x,
                    "y": origin_y,
                    "width": logical_w,
                    "height": logical_h,
                    "scale": scale,
                }
            )
    except Exception as exc:
        log.debug("list_displays Quartz unavailable: %s", exc)

    if not displays:
        w, h, scale = _screen_size_via_jxa()
        displays.append(
            {
                "display_id": 1,
                "is_main": True,
                "x": 0,
                "y": 0,
                "width": w,
                "height": h,
                "scale": scale,
            }
        )
    return displays


def _main_display() -> Dict[str, Any]:
    for d in list_displays():
        if d.get("is_main"):
            return d
    displays = list_displays()
    return displays[0] if displays else {
        "display_id": 0,
        "is_main": True,
        "x": 0,
        "y": 0,
        "width": 1440,
        "height": 900,
        "scale": 1.0,
    }


def _resolve_display(display_id: Optional[int]) -> Dict[str, Any]:
    displays = list_displays()
    if display_id is None:
        return _main_display()
    for d in displays:
        if int(d["display_id"]) == int(display_id):
            return d
    raise ValueError(
        f"unknown display_id {display_id}; known: "
        + ", ".join(str(d["display_id"]) for d in displays)
    )


def _display_index_for_screencapture(display: Dict[str, Any]) -> int:
    """screencapture -D uses 1-based index in the active display list."""
    displays = list_displays()
    for i, d in enumerate(displays, start=1):
        if int(d["display_id"]) == int(display["display_id"]):
            return i
    return 1


def to_global(x: int, y: int, display: Dict[str, Any]) -> Tuple[int, int]:
    """Map display-local logical coords to Quartz global points."""
    return int(x) + int(display.get("x") or 0), int(y) + int(display.get("y") or 0)


# ── window targeting ──────────────────────────────────────────────────


def _frontmost_app_name(timeout: float = AUTOMATION_TIMEOUT_SEC) -> str:
    code, out = _osascript(
        'tell application "System Events" to get name of first application process '
        "whose frontmost is true",
        timeout=timeout,
    )
    return out if code == 0 else ""


def _bundle_id(app: str) -> str:
    if not app:
        return ""
    code, out = _osascript(
        f"id of application {_apple_string(app)}",
        timeout=AUTOMATION_TIMEOUT_SEC,
    )
    return out.strip() if code == 0 else ""


def _window_info(
    *,
    app: Optional[str] = None,
    frontmost: bool = False,
) -> Dict[str, Any]:
    """
    Resolve a window via CGWindowList. Returns bounds in global logical points
    plus a CGWindowID for screencapture -l.
    """
    try:
        import Quartz  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Quartz unavailable for window targeting: {exc}") from exc

    options = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    wanted = (app or "").strip().lower()
    front_name = _frontmost_app_name().strip().lower() if frontmost or not wanted else ""

    candidates: List[Dict[str, Any]] = []
    for win in windows:
        if not isinstance(win, dict):
            continue
        layer = int(win.get("kCGWindowLayer", 0) or 0)
        if layer != 0:
            continue
        owner = str(win.get("kCGWindowOwnerName") or "")
        bounds = win.get("kCGWindowBounds") or {}
        wid = win.get("kCGWindowNumber")
        if wid is None:
            continue
        width = float(bounds.get("Width") or 0)
        height = float(bounds.get("Height") or 0)
        if width < 40 or height < 40:
            continue
        entry = {
            "window_id": int(wid),
            "owner_pid": int(win.get("kCGWindowOwnerPID") or 0),
            "app": owner,
            "title": str(win.get("kCGWindowName") or ""),
            "bounds": {
                "x": int(bounds.get("X") or 0),
                "y": int(bounds.get("Y") or 0),
                "width": int(width),
                "height": int(height),
            },
        }
        owner_l = owner.lower()
        if wanted and (wanted in owner_l or owner_l in wanted):
            candidates.append(entry)
        elif frontmost and front_name and owner_l == front_name:
            candidates.append(entry)
        elif frontmost and not front_name and not wanted:
            candidates.append(entry)

    if not candidates and (wanted or frontmost):
        raise ValueError(
            f"no on-screen window for app={app!r} frontmost={frontmost}; "
            f"frontmost app is {_frontmost_app_name()!r}"
        )
    if not candidates:
        raise ValueError("no suitable on-screen window found")
    # Largest window for that app tends to be the main one.
    candidates.sort(
        key=lambda c: c["bounds"]["width"] * c["bounds"]["height"], reverse=True
    )
    return candidates[0]


# ── screenshot ────────────────────────────────────────────────────────


def _resize_png_to_logical(path: str, logical_w: int, logical_h: int) -> None:
    if logical_w <= 0 or logical_h <= 0:
        return
    try:
        with open(path, "rb") as fh:
            pix_w, pix_h = _png_pixel_size(fh.read(64))
        if pix_w <= 0 or (pix_w == logical_w and pix_h == logical_h):
            return
        subprocess.run(
            ["sips", "-z", str(logical_h), str(logical_w), path],
            check=False,
            capture_output=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def capture_screenshot(
    *,
    display_id: Optional[int] = None,
    app: Optional[str] = None,
    frontmost: bool = False,
) -> Dict[str, Any]:
    """
    Capture a PNG and return base64 + logical geometry.

    Coordinate space for clicks: logical points. Image is resized to logical
    width×height when possible so model coords match image pixels.
    """
    display = _resolve_display(display_id)
    window_bounds = None
    window_meta: Dict[str, Any] = {}

    try:
        fd, path = tempfile.mkstemp(prefix="rau-cua-", suffix=".png")
        os.close(fd)
    except OSError as exc:
        return {"ok": False, "error": f"temp file failed: {exc}"}

    try:
        cmd = ["screencapture", "-x"]
        if app or frontmost:
            info = _window_info(app=app, frontmost=frontmost or not app)
            window_bounds = info["bounds"]
            window_meta = {
                "window_id": info["window_id"],
                "app": info["app"],
                "bundle_id": _bundle_id(str(info["app"])),
                "title": info.get("title") or "",
                "window_bounds": window_bounds,
            }
            cmd += ["-l", str(info["window_id"]), path]
            logical_w = int(window_bounds["width"])
            logical_h = int(window_bounds["height"])
            scale = float(display.get("scale") or 1.0)
        else:
            idx = _display_index_for_screencapture(display)
            cmd += ["-D", str(idx), "-C", path]
            logical_w = int(display.get("width") or 0)
            logical_h = int(display.get("height") or 0)
            scale = float(display.get("scale") or 1.0)

        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            timeout=AUTOMATION_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or b"").decode("utf-8", "replace")
            return {
                "ok": False,
                "error": err.strip() or "screenshot capture failed",
            }

        if not (app or frontmost):
            _resize_png_to_logical(path, logical_w, logical_h)
        else:
            _resize_png_to_logical(path, logical_w, logical_h)

        with open(path, "rb") as image:
            data = image.read()
        if not data:
            return {"ok": False, "error": "screenshot capture failed"}

        pix_w, pix_h = _png_pixel_size(data)
        if logical_w <= 0:
            logical_w = pix_w
        if logical_h <= 0:
            logical_h = pix_h

        b64 = base64.b64encode(data).decode("ascii")
        out: Dict[str, Any] = {
            "ok": True,
            "action": "screenshot",
            "image_b64": b64,
            "image_b64_len": len(b64),
            "mime": "image/png",
            "width": logical_w,
            "height": logical_h,
            "scale": scale,
            "display_id": int(display["display_id"]),
            "coordinate_space": "logical_points",
            "displays": list_displays(),
        }
        out.update(window_meta)
        return out
    except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def capture_screenshot_b64() -> str:
    """Back-compat: main-display PNG base64, or empty string on failure."""
    shot = capture_screenshot()
    if shot.get("ok"):
        return str(shot.get("image_b64") or "")
    return ""


# ── capability probe ──────────────────────────────────────────────────


def cua_status() -> Dict[str, Any]:
    quartz = _quartz_available()
    cliclick = shutil.which("cliclick") is not None
    # Best-effort: AXIsProcessTrusted exists on modern macOS via ApplicationServices.
    accessibility = None
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore

        accessibility = bool(AXIsProcessTrusted())
    except Exception:
        try:
            code, _ = _osascript(
                'tell application "System Events" to get name of first process',
                timeout=STATUS_PROBE_TIMEOUT_SEC,
            )
            # 124 is our own timeout code: the probe is blocked, which for the
            # purposes of "can I drive this machine" is a no, not an unknown.
            accessibility = code == 0
        except Exception:
            accessibility = None

    screen_recording = None
    try:
        shot = capture_screenshot()
        screen_recording = bool(shot.get("ok") and shot.get("image_b64"))
    except Exception:
        screen_recording = False

    return {
        "ok": True,
        "action": "status",
        "quartz": quartz,
        "cliclick": cliclick,
        "accessibility": accessibility,
        "screen_recording": screen_recording,
        "coordinate_space": "logical_points",
        "displays": list_displays(),
        "frontmost_app": _frontmost_app_name(timeout=STATUS_PROBE_TIMEOUT_SEC),
        "hints": [
            "Grant Accessibility and Screen Recording to the host process (Terminal or Rau).",
            "Click/type coordinates are logical points; screenshots are sized to match.",
            "Call action=status before the first click if setup is uncertain.",
        ],
    }


# ── low-level input ───────────────────────────────────────────────────


def _osascript(script: str, timeout: float = AUTOMATION_TIMEOUT_SEC) -> Tuple[int, str]:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "osascript is unavailable"
    except subprocess.TimeoutExpired:
        return 124, "osascript timed out"


def _apple_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _move(x: int, y: int) -> Tuple[bool, str]:
    try:
        import Quartz  # type: ignore

        point = Quartz.CGPointMake(float(x), float(y))
        ev = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        return True, ""
    except Exception as exc:
        try:
            result = subprocess.run(
                ["cliclick", f"m:{x},{y}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=AUTOMATION_TIMEOUT_SEC,
            )
        except FileNotFoundError:
            return False, f"move failed: {exc}"
        except subprocess.TimeoutExpired:
            return False, "cliclick timed out"
        return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def _click(x: int, y: int, double: bool = False) -> Tuple[bool, str]:
    try:
        import Quartz  # type: ignore

        point = Quartz.CGPointMake(float(x), float(y))

        def post(kind: Any, click_state: int) -> None:
            ev = Quartz.CGEventCreateMouseEvent(
                None, kind, point, Quartz.kCGMouseButtonLeft
            )
            # macOS decides "double click" from the event's click state, not
            # from two clicks arriving close together. Without this, Finder and
            # most text views read a double_click as two ordinary clicks and
            # the action silently does the wrong thing.
            setter = getattr(Quartz, "CGEventSetIntegerValueField", None)
            field = getattr(Quartz, "kCGMouseEventClickState", None)
            if click_state > 1 and setter is not None and field is not None:
                setter(ev, field, click_state)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.01)

        post(Quartz.kCGEventLeftMouseDown, 1)
        post(Quartz.kCGEventLeftMouseUp, 1)
        if double:
            post(Quartz.kCGEventLeftMouseDown, 2)
            post(Quartz.kCGEventLeftMouseUp, 2)
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


def _drag(
    x: int,
    y: int,
    x2: int,
    y2: int,
    cancel: Optional[threading.Event] = None,
) -> Tuple[bool, str]:
    try:
        import Quartz  # type: ignore

        start = Quartz.CGPointMake(float(x), float(y))
        down = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, start, Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        time.sleep(0.02)
        # Where the pointer actually is, so a cancel can put the button down
        # here rather than somewhere it never travelled to.
        last_x, last_y = float(x), float(y)
        for step in range(1, DRAG_STEPS + 1):
            if cancel is not None and cancel.is_set():
                # Release where the drag got to. Releasing at the destination
                # would complete the very move the cancel was meant to stop —
                # the dragged file lands in the target folder anyway.
                up = Quartz.CGEventCreateMouseEvent(
                    None,
                    Quartz.kCGEventLeftMouseUp,
                    Quartz.CGPointMake(last_x, last_y),
                    Quartz.kCGMouseButtonLeft,
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
                return False, "action cancelled"
            t = step / DRAG_STEPS
            cx = x + (x2 - x) * t
            cy = y + (y2 - y) * t
            last_x, last_y = float(cx), float(cy)
            pt = Quartz.CGPointMake(float(cx), float(cy))
            drag = Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseDragged, pt, Quartz.kCGMouseButtonLeft
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, drag)
            time.sleep(0.008)
        end = Quartz.CGPointMake(float(x2), float(y2))
        up = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, end, Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        return True, ""
    except Exception as exc:
        # No Quartz, no drag. Two clicks are not a drag — they are two clicks,
        # landing on whatever happens to be under the pointer at each end, and
        # this used to perform both of them before reporting that it had
        # "refused". Refusing means doing nothing.
        return False, (
            f"drag needs Quartz, which is unavailable ({exc}); "
            "refused rather than substituting two clicks"
        )


def _utf16_length(text: str) -> int:
    """CGEventKeyboardSetUnicodeString counts UTF-16 code units, not str
    characters. Astral characters (emoji, CJK ext) are one str char but two
    units; passing len(text) truncates the pair and posts a lone surrogate."""
    return len(text.encode("utf-16-le")) // 2


def _type_text_quartz(
    text: str, cancel: Optional[threading.Event] = None
) -> Tuple[bool, str]:
    try:
        import Quartz  # type: ignore
    except Exception as exc:
        return False, f"Quartz typing unavailable: {exc}"

    for i in range(0, len(text), TYPE_CHUNK_CHARS):
        if cancel is not None and cancel.is_set():
            return False, "action cancelled"
        chunk = text[i : i + TYPE_CHUNK_CHARS]
        try:
            event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            if event is None:
                return False, "CGEventCreateKeyboardEvent failed"
            Quartz.CGEventKeyboardSetUnicodeString(event, _utf16_length(chunk), chunk)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            # Key-up with empty unicode keeps some apps happier.
            up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            time.sleep(0.015)
        except Exception as exc:
            return False, str(exc)
    return True, ""


def _type_text(
    text: str, cancel: Optional[threading.Event] = None
) -> Tuple[bool, str]:
    ok, detail = _type_text_quartz(text, cancel=cancel)
    if ok or detail == "action cancelled":
        return ok, detail
    # AppleScript fallback — chunked so cancel can land between pieces.
    for i in range(0, len(text), TYPE_CHUNK_CHARS):
        if cancel is not None and cancel.is_set():
            return False, "action cancelled"
        chunk = text[i : i + TYPE_CHUNK_CHARS]
        safe = chunk.replace("\\", "\\\\").replace('"', '\\"')
        code, output = _osascript(
            f'tell application "System Events" to keystroke "{safe}"'
        )
        if code != 0:
            return False, output or detail
        time.sleep(0.02)
    return True, ""


# macOS virtual keycodes (ANSI).
_KEYCODES: Dict[str, int] = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "backspace": 51,
    "escape": 53,
    "esc": 53,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

_MOD_FLAGS = {
    "cmd": "kCGEventFlagMaskCommand",
    "command": "kCGEventFlagMaskCommand",
    "meta": "kCGEventFlagMaskCommand",
    "shift": "kCGEventFlagMaskShift",
    "alt": "kCGEventFlagMaskAlternate",
    "option": "kCGEventFlagMaskAlternate",
    "ctrl": "kCGEventFlagMaskControl",
    "control": "kCGEventFlagMaskControl",
}

# Letter/digit keycodes for chords like cmd+c.
_CHAR_KEYCODES: Dict[str, int] = {
    **{c: code for c, code in zip("abcdefghijklmnopqrstuvwxyz", [
        0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35, 12, 15, 1, 17,
        32, 9, 13, 7, 16, 6,
    ])},
    **{str(d): code for d, code in zip("0123456789", [
        29, 18, 19, 20, 21, 23, 22, 26, 28, 25,
    ])},
}


def parse_key_chord(key: str) -> Tuple[List[str], str]:
    """Split 'cmd+shift+c' into (['cmd','shift'], 'c')."""
    # "-" doubles as the chord separator ('ctrl-c'); a bare "-" is the key.
    normalized = key.strip()
    if normalized != "-":
        normalized = normalized.replace("-", "+")
    parts = [p.strip().lower() for p in normalized.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key")
    mods: List[str] = []
    primary = parts[-1]
    for p in parts[:-1]:
        if p not in _MOD_FLAGS:
            raise ValueError(f"unsupported modifier: {p}")
        mods.append(p)
    return mods, primary


def _key(key: str) -> Tuple[bool, str]:
    try:
        mods, primary = parse_key_chord(key)
    except ValueError as exc:
        return False, str(exc)

    try:
        import Quartz  # type: ignore

        flags = 0
        for m in mods:
            flags |= getattr(Quartz, _MOD_FLAGS[m])

        if primary in _KEYCODES:
            keycode = _KEYCODES[primary]
        elif len(primary) == 1 and primary in _CHAR_KEYCODES:
            keycode = _CHAR_KEYCODES[primary]
        elif len(primary) == 1 and ord(primary) >= 32:
            # Single printable via unicode typing with modifiers held.
            down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(down, _utf16_length(primary), primary)
            Quartz.CGEventSetFlags(down, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
            up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventSetFlags(up, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            return True, ""
        else:
            return False, f"unsupported key: {key[:40]}"

        down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
        Quartz.CGEventSetFlags(down, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
        Quartz.CGEventSetFlags(up, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        return True, ""
    except Exception as exc:
        # AppleScript fallback for a few bare keys only (no chords).
        if mods:
            return False, f"key chord requires Quartz: {exc}"
        # keystroke "tab" would type the literal letters t-a-b; named keys
        # go through key code, single characters through keystroke.
        keycode = _KEYCODES.get(primary)
        if keycode is not None:
            script = f'tell application "System Events" to key code {keycode}'
        elif len(primary) == 1:
            script = f'tell application "System Events" to keystroke {_apple_string(primary)}'
        else:
            return False, f"unsupported key: {key[:40]}"
        status, output = _osascript(script)
        return status == 0, output or str(exc)


def _int_field(action: Dict[str, Any], name: str, default: int = 0) -> int:
    value = action.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if abs(parsed) > MAX_COORDINATE:
        raise ValueError(f"{name} is outside the supported range")
    return parsed


def _optional_int(action: Dict[str, Any], name: str) -> Optional[int]:
    if name not in action or action.get(name) is None:
        return None
    return _int_field(action, name)


def _seconds(value: Any, default: float = 0.5) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        raise ValueError("seconds must be a number") from None
    if not math.isfinite(parsed) or not 0 <= parsed <= MAX_WAIT_SEC:
        raise ValueError(f"seconds must be between 0 and {MAX_WAIT_SEC:g}")
    return parsed


def _bool_field(action: Dict[str, Any], name: str, default: bool = False) -> bool:
    value = action.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _attach_verify(
    result: Dict[str, Any],
    action: Dict[str, Any],
    cancel: Optional[threading.Event],
) -> None:
    if cancel is not None and cancel.is_set():
        result["verified"] = False
        result["verify_error"] = "cancelled before verify screenshot"
        return
    shot = capture_screenshot(
        display_id=_optional_int(action, "display_id"),
        app=str(action["app"]) if isinstance(action.get("app"), str) else None,
        frontmost=_bool_field(action, "frontmost", False),
    )
    if not shot.get("ok"):
        result["verified"] = False
        result["verify_error"] = shot.get("error") or "verify screenshot failed"
        return
    result["verified"] = True
    result["image_b64"] = shot["image_b64"]
    result["image_b64_len"] = shot.get("image_b64_len")
    result["mime"] = shot.get("mime", "image/png")
    for key in (
        "width",
        "height",
        "scale",
        "display_id",
        "coordinate_space",
        "displays",
        "window_bounds",
        "app",
        "title",
        "window_id",
    ):
        if key in shot:
            result[key] = shot[key]


def execute_action(
    action: Dict[str, Any],
    cancel: Optional[threading.Event] = None,
    *,
    auto_verify: bool = True,
) -> Dict[str, Any]:
    """
    action schema:
      { "action": "screenshot"|"status"|"click"|"double_click"|"move"|"type"|
                  "key"|"scroll"|"wait"|"drag",
        "x","y","x2","y2","text","key","dy","seconds",
        "display_id","app","frontmost" }
    """
    if not isinstance(action, dict):
        return {"action": "unknown", "ok": False, "error": "action must be an object"}
    raw_kind = action.get("action") or action.get("type") or "screenshot"
    if not isinstance(raw_kind, str):
        return {"action": "unknown", "ok": False, "error": "action name must be a string"}
    kind = raw_kind.lower().strip()
    if kind in ("cua_status",):
        kind = "status"
    result: Dict[str, Any] = {"action": kind, "ok": True}

    try:
        if cancel is not None and cancel.is_set():
            result["ok"] = False
            result["cancelled"] = True
            result["error"] = "action cancelled"
        elif kind == "status":
            result = cua_status()
        elif kind == "screenshot":
            result = capture_screenshot(
                display_id=_optional_int(action, "display_id"),
                app=str(action["app"]) if isinstance(action.get("app"), str) else None,
                frontmost=_bool_field(action, "frontmost", False),
            )
            result["action"] = "screenshot"
        else:
            display = _resolve_display(_optional_int(action, "display_id"))

            def _xy() -> Tuple[int, int]:
                return to_global(
                    _int_field(action, "x"),
                    _int_field(action, "y"),
                    display,
                )

            if kind in ("click", "double_click"):
                gx, gy = _xy()
                ok, detail = _click(gx, gy, double=kind == "double_click")
                if not ok:
                    result.update(ok=False, error=detail or "click failed")
            elif kind == "move":
                gx, gy = _xy()
                ok, detail = _move(gx, gy)
                if not ok:
                    result.update(ok=False, error=detail or "move failed")
            elif kind == "type":
                text = action.get("text") or ""
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
                if len(text) > MAX_TEXT_CHARS:
                    raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")
                ok, detail = _type_text(text, cancel=cancel)
                if not ok:
                    result.update(
                        ok=False,
                        error=detail or "typing failed",
                        cancelled=detail == "action cancelled",
                    )
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

                    if "x" in action and "y" in action:
                        gx, gy = _xy()
                        _move(gx, gy)
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
                gx, gy = _xy()
                gx2, gy2 = to_global(
                    _int_field(action, "x2"),
                    _int_field(action, "y2"),
                    display,
                )
                ok, detail = _drag(gx, gy, gx2, gy2, cancel=cancel)
                if not ok:
                    result.update(
                        ok=False,
                        error=detail or "drag failed",
                        cancelled=detail == "action cancelled",
                    )
            else:
                result.update(ok=False, error=f"unknown action {kind}")

            if (
                auto_verify
                and result.get("ok")
                and kind in VERIFY_ACTIONS
                and not result.get("cancelled")
            ):
                _attach_verify(result, action, cancel)

    except (TypeError, ValueError, OverflowError, RuntimeError) as exc:
        result.update(ok=False, error=str(exc))

    append_trace(
        "cua",
        {
            "action": kind,
            "ok": result.get("ok"),
            "verified": result.get("verified"),
            "display_id": result.get("display_id"),
        },
    )
    return result

"""Tests for computer-use vision plumbing, keys, and permissions."""
from __future__ import annotations

import base64
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.agent import danger  # noqa: E402
from rau.computer import cua  # noqa: E402
from rau.computer import session as comp_session  # noqa: E402
from rau.control.store import ControlStore  # noqa: E402
from rau.providers.base import (  # noqa: E402
    Message,
    ToolCall,
    messages_to_openai,
    tool_message_content_anthropic,
    tool_message_content_openai,
    tool_result_images,
    tool_result_text,
)
from rau.providers.anthropic_compat import _to_anthropic_messages  # noqa: E402
from rau import permissions  # noqa: E402


def _tiny_png(width: int = 4, height: int = 4) -> bytes:
    """Minimal valid PNG (IHDR + IEND) — not a real image body, size only."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # CRC ignored by our size parser; still need length+type+data+crc shape.
    chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    iend = struct.pack(">I", 0) + b"IEND" + b"\x00\x00\x00\x00"
    return signature + chunk + iend


class ToolResultVisionTests(unittest.TestCase):
    def test_tool_result_text_strips_image_bytes(self) -> None:
        b64 = base64.b64encode(_tiny_png()).decode("ascii") * 20  # long enough
        result = {
            "ok": True,
            "action": "screenshot",
            "image_b64": b64,
            "width": 100,
            "height": 50,
        }
        text = tool_result_text(result)
        self.assertNotIn(b64[:40], text)
        self.assertIn("has_image", text)
        self.assertIn("100", text)

    def test_tool_result_images_extracts_payload(self) -> None:
        b64 = "a" * 220
        imgs = tool_result_images({"image_b64": b64, "mime": "image/png"})
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0]["b64"], b64)

    def test_openai_tool_message_includes_image_url(self) -> None:
        b64 = "abcd" * 60
        msg = Message(
            role="tool",
            content='{"ok":true,"has_image":true}',
            tool_call_id="c1",
            name="cua_action",
            images=[{"mime": "image/png", "b64": b64}],
        )
        content = tool_message_content_openai(msg)
        self.assertIsInstance(content, list)
        types = {part["type"] for part in content}
        self.assertEqual(types, {"text", "image_url"})
        self.assertIn("base64," + b64, content[1]["image_url"]["url"])

    def test_messages_to_openai_carries_multimodal_tool_result(self) -> None:
        b64 = "xy" * 120
        convo = [
            Message(role="user", content="click the button"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="cua_action", arguments={"action": "screenshot"})
                ],
            ),
            Message(
                role="tool",
                content='{"ok":true}',
                tool_call_id="c1",
                name="cua_action",
                images=[{"mime": "image/png", "b64": b64}],
            ),
        ]
        wire = messages_to_openai(convo)
        tool_msgs = [m for m in wire if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIsInstance(tool_msgs[0]["content"], list)

    def test_anthropic_tool_result_includes_image_block(self) -> None:
        b64 = "zz" * 120
        msg = Message(
            role="tool",
            content='{"ok":true}',
            tool_call_id="c1",
            images=[{"mime": "image/png", "b64": b64}],
        )
        content = tool_message_content_anthropic(msg)
        self.assertIsInstance(content, list)
        image = next(p for p in content if p["type"] == "image")
        self.assertEqual(image["source"]["data"], b64)

        system, anth = _to_anthropic_messages(
            [
                Message(role="system", content="sys"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="c1", name="cua_action", arguments={"action": "screenshot"})
                    ],
                ),
                msg,
            ]
        )
        self.assertIn("sys", system)
        users = [m for m in anth if m["role"] == "user"]
        results = [
            b
            for m in users
            for b in m["content"]
            if b.get("type") == "tool_result"
        ]
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0]["content"], list)


class KeyChordTests(unittest.TestCase):
    def test_parse_key_chord(self) -> None:
        mods, primary = cua.parse_key_chord("cmd+shift+c")
        self.assertEqual(mods, ["cmd", "shift"])
        self.assertEqual(primary, "c")

    def test_parse_rejects_unknown_modifier(self) -> None:
        with self.assertRaises(ValueError):
            cua.parse_key_chord("super+c")

    def test_key_uses_quartz_flags(self) -> None:
        posted: List[Any] = []

        class FakeQuartz:
            kCGEventFlagMaskCommand = 0x100000
            kCGEventFlagMaskShift = 0x20000
            kCGHIDEventTap = 0

            @staticmethod
            def CGEventCreateKeyboardEvent(_src, keycode, key_down):
                return {"keycode": keycode, "down": key_down, "flags": 0}

            @staticmethod
            def CGEventSetFlags(event, flags):
                event["flags"] = flags

            @staticmethod
            def CGEventPost(_tap, event):
                posted.append(dict(event))

            @staticmethod
            def CGEventKeyboardSetUnicodeString(event, length, string):
                event["unicode"] = string

        with mock.patch.dict(sys.modules, {"Quartz": FakeQuartz}):
            ok, detail = cua._key("cmd+c")
        self.assertTrue(ok, detail)
        self.assertGreaterEqual(len(posted), 2)
        self.assertTrue(posted[0]["flags"] & FakeQuartz.kCGEventFlagMaskCommand)


class DragTests(unittest.TestCase):
    def test_drag_posts_down_dragged_up(self) -> None:
        kinds: List[str] = []

        class FakeQuartz:
            kCGEventLeftMouseDown = "down"
            kCGEventLeftMouseUp = "up"
            kCGEventLeftMouseDragged = "dragged"
            kCGMouseButtonLeft = 0
            kCGHIDEventTap = 0

            @staticmethod
            def CGPointMake(x, y):
                return (x, y)

            @staticmethod
            def CGEventCreateMouseEvent(_src, kind, point, _btn):
                return {"kind": kind, "point": point}

            @staticmethod
            def CGEventPost(_tap, event):
                kinds.append(event["kind"])

        with mock.patch.dict(sys.modules, {"Quartz": FakeQuartz}):
            with mock.patch.object(cua.time, "sleep", return_value=None):
                ok, detail = cua._drag(10, 10, 50, 40)
        self.assertTrue(ok, detail)
        self.assertEqual(kinds[0], "down")
        self.assertEqual(kinds[-1], "up")
        self.assertIn("dragged", kinds)


    def _fake_quartz(self, posted: List[Dict[str, Any]]):
        class FakeQuartz:
            kCGEventLeftMouseDown = "down"
            kCGEventLeftMouseUp = "up"
            kCGEventLeftMouseDragged = "dragged"
            kCGMouseButtonLeft = 0
            kCGHIDEventTap = 0

            @staticmethod
            def CGPointMake(x, y):
                return (x, y)

            @staticmethod
            def CGEventCreateMouseEvent(_src, kind, point, _btn):
                return {"kind": kind, "point": point}

            @staticmethod
            def CGEventPost(_tap, event):
                posted.append(dict(event))

        return FakeQuartz

    def test_cancelled_drag_releases_where_it_stopped(self) -> None:
        """
        A cancel that releases at the destination completes the very move it
        was meant to stop — the dragged file lands in the target folder anyway.
        """
        import threading

        posted: List[Dict[str, Any]] = []
        cancel = threading.Event()

        calls = {"n": 0}

        def creep(_seconds):
            # Let the drag travel a little, then pull the plug mid-flight.
            calls["n"] += 1
            if calls["n"] >= 4:
                cancel.set()

        with mock.patch.dict(sys.modules, {"Quartz": self._fake_quartz(posted)}):
            with mock.patch.object(cua.time, "sleep", side_effect=creep):
                ok, detail = cua._drag(0, 0, 1000, 500, cancel=cancel)

        self.assertFalse(ok)
        self.assertEqual(detail, "action cancelled")
        release = [e for e in posted if e["kind"] == "up"]
        self.assertEqual(len(release), 1, "the button must be released exactly once")
        self.assertNotEqual(
            release[0]["point"], (1000.0, 500.0), "released at the destination"
        )
        dragged = [e for e in posted if e["kind"] == "dragged"]
        self.assertEqual(release[0]["point"], dragged[-1]["point"])

    def test_drag_without_quartz_refuses_without_clicking(self) -> None:
        """Two clicks are not a drag, and 'refused' must mean nothing happened."""
        clicked: List[Any] = []

        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch.object(
                cua, "_click", side_effect=lambda *a, **k: clicked.append(a) or (True, "")
            ):
                ok, detail = cua._drag(10, 10, 50, 40)

        self.assertFalse(ok)
        self.assertEqual(clicked, [], "refusing a drag must not click anything")
        self.assertIn("refused", detail)


class ClickStateTests(unittest.TestCase):
    def test_double_click_sets_the_click_state(self) -> None:
        """
        macOS reads "double click" off the event's click state, not off two
        clicks arriving close together. Without it Finder and most text views
        see two ordinary clicks.
        """
        posted: List[Dict[str, Any]] = []

        class FakeQuartz:
            kCGEventLeftMouseDown = "down"
            kCGEventLeftMouseUp = "up"
            kCGMouseButtonLeft = 0
            kCGHIDEventTap = 0
            kCGMouseEventClickState = "clickState"

            @staticmethod
            def CGPointMake(x, y):
                return (x, y)

            @staticmethod
            def CGEventCreateMouseEvent(_src, kind, point, _btn):
                return {"kind": kind, "point": point, "clickState": 1}

            @staticmethod
            def CGEventSetIntegerValueField(event, field, value):
                event[field] = value

            @staticmethod
            def CGEventPost(_tap, event):
                posted.append(dict(event))

        with mock.patch.dict(sys.modules, {"Quartz": FakeQuartz}):
            with mock.patch.object(cua.time, "sleep", return_value=None):
                ok, _ = cua._click(5, 5, double=True)

        self.assertTrue(ok)
        self.assertEqual([e["clickState"] for e in posted], [1, 1, 2, 2])

    def test_single_click_stays_at_click_state_one(self) -> None:
        posted: List[Dict[str, Any]] = []

        class FakeQuartz:
            kCGEventLeftMouseDown = "down"
            kCGEventLeftMouseUp = "up"
            kCGMouseButtonLeft = 0
            kCGHIDEventTap = 0
            kCGMouseEventClickState = "clickState"

            @staticmethod
            def CGPointMake(x, y):
                return (x, y)

            @staticmethod
            def CGEventCreateMouseEvent(_src, kind, point, _btn):
                return {"kind": kind, "point": point, "clickState": 1}

            @staticmethod
            def CGEventSetIntegerValueField(event, field, value):
                event[field] = value

            @staticmethod
            def CGEventPost(_tap, event):
                posted.append(dict(event))

        with mock.patch.dict(sys.modules, {"Quartz": FakeQuartz}):
            with mock.patch.object(cua.time, "sleep", return_value=None):
                cua._click(5, 5)
        self.assertEqual([e["clickState"] for e in posted], [1, 1])


class StatusProbeTests(unittest.TestCase):
    def test_status_probes_never_wait_the_full_automation_timeout(self) -> None:
        """
        `cua_status` exists to answer "am I allowed to drive this machine".
        An osascript that needs Accessibility blocks until timeout when the
        permission is missing — exactly the case status is asked about — so at
        the automation timeout the answer arrived half a minute late.
        """
        seen: List[float] = []

        def fake_osascript(script, timeout=cua.AUTOMATION_TIMEOUT_SEC):
            seen.append(timeout)
            return 124, "osascript timed out"

        with mock.patch.object(cua, "_osascript", side_effect=fake_osascript):
            with mock.patch.object(cua, "capture_screenshot", return_value={"ok": False}):
                with mock.patch.object(cua, "list_displays", return_value=[]):
                    with mock.patch.dict(sys.modules, {"ApplicationServices": None}):
                        status = cua.cua_status()

        self.assertTrue(status["ok"])
        self.assertTrue(seen, "status should probe at least once")
        self.assertTrue(
            all(t <= cua.STATUS_PROBE_TIMEOUT_SEC for t in seen),
            f"status probed with long timeouts: {seen}",
        )
        self.assertLess(cua.STATUS_PROBE_TIMEOUT_SEC, cua.AUTOMATION_TIMEOUT_SEC)


class DisplayCoordTests(unittest.TestCase):
    def test_to_global_adds_origin(self) -> None:
        gx, gy = cua.to_global(5, 7, {"x": 100, "y": 200})
        self.assertEqual((gx, gy), (105, 207))

    def test_png_pixel_size(self) -> None:
        data = _tiny_png(1280, 800)
        self.assertEqual(cua._png_pixel_size(data), (1280, 800))


class StatusAndExecuteTests(unittest.TestCase):
    def test_status_shape(self) -> None:
        with mock.patch.object(cua, "capture_screenshot", return_value={"ok": True, "image_b64": "x" * 10}):
            with mock.patch.object(cua, "list_displays", return_value=[{"display_id": 1, "is_main": True}]):
                status = cua.cua_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["action"], "status")
        self.assertIn("quartz", status)
        self.assertIn("displays", status)
        self.assertIn("hints", status)

    def test_execute_screenshot_does_not_auto_verify(self) -> None:
        shot = {
            "ok": True,
            "action": "screenshot",
            "image_b64": "b" * 220,
            "width": 10,
            "height": 10,
            "scale": 2.0,
            "display_id": 1,
            "coordinate_space": "logical_points",
            "displays": [],
        }
        with mock.patch.object(cua, "capture_screenshot", return_value=shot) as cap:
            result = cua.execute_action({"action": "screenshot"}, auto_verify=True)
        self.assertTrue(result["ok"])
        self.assertNotIn("verified", result)
        self.assertEqual(cap.call_count, 1)

    def test_execute_click_auto_verifies(self) -> None:
        verify_shot = {
            "ok": True,
            "image_b64": "v" * 220,
            "width": 20,
            "height": 10,
            "scale": 1.0,
            "display_id": 1,
            "coordinate_space": "logical_points",
            "displays": [],
        }
        with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 1, "x": 0, "y": 0}):
            with mock.patch.object(cua, "_click", return_value=(True, "")):
                with mock.patch.object(cua, "capture_screenshot", return_value=verify_shot):
                    result = cua.execute_action(
                        {"action": "click", "x": 1, "y": 2}, auto_verify=True
                    )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("verified"))
        self.assertEqual(result.get("image_b64"), "v" * 220)

    def test_unknown_display_errors(self) -> None:
        with mock.patch.object(
            cua,
            "list_displays",
            return_value=[{"display_id": 99, "is_main": True, "x": 0, "y": 0, "width": 1, "height": 1, "scale": 1}],
        ):
            result = cua.execute_action(
                {"action": "click", "x": 0, "y": 0, "display_id": 12345},
                auto_verify=False,
            )
        self.assertFalse(result["ok"])
        self.assertIn("display_id", result["error"])


class WindowOriginTests(unittest.TestCase):
    """A window capture (screencapture -l) puts the window's top-left at
    image (0,0); coordinates read off that image must add the window origin,
    not the display origin, or clicks land offset by the window's position."""

    def _click(self, action: Dict[str, Any]) -> Tuple[List[Tuple[int, int]], Dict[str, Any]]:
        clicked: List[Tuple[int, int]] = []
        with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 1, "x": 0, "y": 0}):
            with mock.patch.object(
                cua,
                "_click",
                side_effect=lambda x, y, double=False: clicked.append((x, y)) or (True, ""),
            ):
                result = cua.execute_action(action, auto_verify=False)
        return clicked, result

    def test_app_click_adds_the_window_origin(self) -> None:
        window = {
            "window_id": 7,
            "app": "Safari",
            "bounds": {"x": 500, "y": 400, "width": 800, "height": 600},
        }
        with mock.patch.object(cua, "_window_info", return_value=window) as info:
            clicked, result = self._click({"action": "click", "x": 50, "y": 50, "app": "Safari"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(clicked, [(550, 450)])
        info.assert_called_once_with(app="Safari", frontmost=False)

    def test_frontmost_click_resolves_the_frontmost_window(self) -> None:
        window = {
            "window_id": 9,
            "app": "Finder",
            "bounds": {"x": 10, "y": 20, "width": 800, "height": 600},
        }
        with mock.patch.object(cua, "_window_info", return_value=window) as info:
            clicked, result = self._click({"action": "click", "x": 1, "y": 1, "frontmost": True})
        self.assertTrue(result["ok"], result)
        self.assertEqual(clicked, [(11, 21)])
        info.assert_called_once_with(app=None, frontmost=True)

    def test_carried_window_bounds_skip_re_resolution(self) -> None:
        with mock.patch.object(cua, "_window_info") as info:
            clicked, result = self._click(
                {
                    "action": "click",
                    "x": 50,
                    "y": 50,
                    "window_bounds": {"x": 500, "y": 400, "width": 800, "height": 600},
                }
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(clicked, [(550, 450)])
        info.assert_not_called()

    def test_display_capture_keeps_the_display_origin(self) -> None:
        with mock.patch.object(cua, "_window_info") as info:
            with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 2, "x": 100, "y": 200}):
                with mock.patch.object(cua, "_click", return_value=(True, "")) as click:
                    result = cua.execute_action(
                        {"action": "click", "x": 5, "y": 7}, auto_verify=False
                    )
        self.assertTrue(result["ok"], result)
        click.assert_called_once_with(105, 207, double=False)
        info.assert_not_called()

    def test_drag_offsets_both_endpoints_by_one_window_origin(self) -> None:
        drags: List[Tuple[int, int, int, int]] = []
        window = {
            "window_id": 7,
            "app": "Safari",
            "bounds": {"x": 500, "y": 400, "width": 800, "height": 600},
        }
        with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 1, "x": 0, "y": 0}):
            with mock.patch.object(cua, "_window_info", return_value=window) as info:
                with mock.patch.object(
                    cua,
                    "_drag",
                    side_effect=lambda x, y, x2, y2, cancel=None: drags.append((x, y, x2, y2)) or (True, ""),
                ):
                    result = cua.execute_action(
                        {"action": "drag", "x": 1, "y": 2, "x2": 3, "y2": 4, "app": "Safari"},
                        auto_verify=False,
                    )
        self.assertTrue(result["ok"], result)
        self.assertEqual(drags, [(501, 402, 503, 404)])
        self.assertEqual(info.call_count, 1)

    def test_type_never_resolves_a_window(self) -> None:
        with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 1, "x": 0, "y": 0}):
            with mock.patch.object(cua, "_window_info") as info:
                with mock.patch.object(cua, "_type_text", return_value=(True, "")):
                    result = cua.execute_action(
                        {"action": "type", "text": "hi", "app": "Safari"},
                        auto_verify=False,
                    )
        self.assertTrue(result["ok"], result)
        info.assert_not_called()


class SessionWindowOriginTests(unittest.TestCase):
    """The session/legacy compatibility path observes a window and then acts
    on image coordinates; the observation's window origin must reach
    execute_action or the click lands offset by the window's position."""

    def _window_shot(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "action": "screenshot",
            "image_b64": "x" * 220,
            "mime": "image/png",
            "width": 800,
            "height": 600,
            "scale": 1.0,
            "display_id": 1,
            "coordinate_space": "logical_points",
            "displays": [{"display_id": 1}],
            "window_id": 7,
            "app": "Safari",
            "bundle_id": "com.apple.Safari",
            "title": "Example",
            "window_bounds": {"x": 500, "y": 400, "width": 800, "height": 600},
        }

    def test_legacy_visual_click_lands_at_the_window_relative_point(self) -> None:
        acted: List[Dict[str, Any]] = []

        def fake_action(args: Dict[str, Any], **_kw: Any) -> Dict[str, Any]:
            acted.append(dict(args))
            return {"ok": True, "action": str(args.get("action") or "")}

        with tempfile.TemporaryDirectory() as tmp:
            manager = comp_session.ComputerSessionManager(
                store=ControlStore(Path(tmp) / "control.db"),
                capture=lambda **_kw: self._window_shot(),
                inspect=lambda **_kw: ([], {}),
                action=fake_action,
            )
            with mock.patch.object(comp_session, "COMPUTER", manager):
                result = comp_session.compatibility_cua_action(
                    {"action": "click", "x": 50, "y": 50, "app": "Safari"}
                )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(len(acted), 1)
        self.assertEqual(
            acted[0].get("window_bounds"),
            {"x": 500, "y": 400, "width": 800, "height": 600},
        )
        # End to end: the args the session built must map image pixel
        # (50,50) to global (550,450), not to the display-relative (50,50).
        clicked: List[Tuple[int, int]] = []
        with mock.patch.object(cua, "_resolve_display", return_value={"display_id": 1, "x": 0, "y": 0}):
            with mock.patch.object(
                cua,
                "_click",
                side_effect=lambda x, y, double=False: clicked.append((x, y)) or (True, ""),
            ):
                final = cua.execute_action(acted[0], auto_verify=False)
        self.assertTrue(final["ok"], final)
        self.assertEqual(clicked, [(550, 450)])

    def test_display_observation_carries_no_window_origin(self) -> None:
        acted: List[Dict[str, Any]] = []

        def fake_action(args: Dict[str, Any], **_kw: Any) -> Dict[str, Any]:
            acted.append(dict(args))
            return {"ok": True, "action": str(args.get("action") or "")}

        shot = self._window_shot()
        for key in ("window_id", "app", "bundle_id", "title", "window_bounds"):
            shot.pop(key)
        with tempfile.TemporaryDirectory() as tmp:
            manager = comp_session.ComputerSessionManager(
                store=ControlStore(Path(tmp) / "control.db"),
                capture=lambda **_kw: dict(shot),
                inspect=lambda **_kw: ([], {}),
                action=fake_action,
            )
            session_id = str(manager.start(frontmost=False)["id"])
            observed = manager.observe(session_id, frontmost=False)
            self.assertTrue(observed.get("ok"), observed)
            result = manager.act(
                session_id,
                {
                    "action": "click",
                    "target": {
                        "kind": "visual",
                        "observation_id": str(observed["observation"]["id"]),
                        "x": 50,
                        "y": 50,
                    },
                },
            )
            self.assertTrue(result.get("ok"), result)
            manager.finish(session_id)
        self.assertEqual(len(acted), 1)
        self.assertNotIn("window_bounds", acted[0])


class PermissionTests(unittest.TestCase):
    def test_move_is_dangerous(self) -> None:
        needs, _ = danger.classify_tool("cua_action", {"action": "move"})
        self.assertTrue(needs)

    def test_status_allowed_in_readonly(self) -> None:
        self.assertTrue(
            permissions.is_readonly_allowed("cua_action", {"action": "status"})
        )
        self.assertFalse(
            permissions.is_readonly_allowed("cua_action", {"action": "click"})
        )

    def test_bypass_logs_warning_for_dangerous_cua(self) -> None:
        traces: List[Dict[str, Any]] = []
        with mock.patch.object(permissions, "mode_for", return_value="bypass"):
            with mock.patch("rau.memory.store.append_trace", side_effect=lambda *a, **k: traces.append({"a": a, "k": k})):
                with mock.patch("logging.Logger.warning") as warn:
                    decision = permissions.tool_decision(
                        "subagents", "cua_action", {"action": "click", "x": 1, "y": 2}
                    )
        self.assertEqual(decision, "allow")
        warn.assert_called()
        self.assertTrue(any(t["a"][0] == "permission_bypass" for t in traces))


if __name__ == "__main__":
    unittest.main()

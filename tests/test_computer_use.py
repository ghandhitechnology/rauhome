"""Tests for computer-use vision plumbing, keys, and permissions."""
from __future__ import annotations

import base64
import struct
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.agent import danger  # noqa: E402
from rau.computer import cua  # noqa: E402
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

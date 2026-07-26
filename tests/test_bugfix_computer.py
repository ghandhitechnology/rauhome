"""Regression tests for computer-use bugfixes (unicode typing, key fallback,
key chord parsing, AX tree walking, and session lease cleanup)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.computer import cua  # noqa: E402
from rau.computer import session as comp_session  # noqa: E402
from rau.control.store import ControlStore  # noqa: E402


def _unicode_recording_quartz(recorded: List[Tuple[int, str]]):
    """Fake Quartz that records CGEventKeyboardSetUnicodeString arguments."""

    class FakeQuartz:
        kCGHIDEventTap = 0
        kCGEventFlagMaskCommand = 0x100000

        @staticmethod
        def CGEventCreateKeyboardEvent(_src, keycode, key_down):
            return {"keycode": keycode, "down": key_down}

        @staticmethod
        def CGEventKeyboardSetUnicodeString(_event, length, string):
            recorded.append((length, string))

        @staticmethod
        def CGEventSetFlags(_event, _flags):
            pass

        @staticmethod
        def CGEventPost(_tap, _event):
            pass

    return FakeQuartz


class UnicodeTypingLengthTests(unittest.TestCase):
    def test_astral_chars_pass_utf16_length(self) -> None:
        """
        CGEventKeyboardSetUnicodeString counts UTF-16 code units, not Python
        characters. An emoji is one str char but two UTF-16 units; passing
        len(text) truncates the pair and posts a lone surrogate.
        """
        recorded: List[Tuple[int, str]] = []
        with mock.patch.dict(
            sys.modules, {"Quartz": _unicode_recording_quartz(recorded)}
        ):
            with mock.patch.object(cua.time, "sleep", return_value=None):
                ok, detail = cua._type_text_quartz("a\U0001F600b")
        self.assertTrue(ok, detail)
        self.assertEqual(recorded, [(4, "a\U0001F600b")])

    def test_key_unicode_fallback_uses_utf16_length(self) -> None:
        recorded: List[Tuple[int, str]] = []
        with mock.patch.dict(
            sys.modules, {"Quartz": _unicode_recording_quartz(recorded)}
        ):
            ok, detail = cua._key("\U0001F600")
        self.assertTrue(ok, detail)
        self.assertEqual(recorded, [(2, "\U0001F600")])

    def test_bmp_text_length_unchanged(self) -> None:
        recorded: List[Tuple[int, str]] = []
        with mock.patch.dict(
            sys.modules, {"Quartz": _unicode_recording_quartz(recorded)}
        ):
            with mock.patch.object(cua.time, "sleep", return_value=None):
                ok, detail = cua._type_text_quartz("héllo")
        self.assertTrue(ok, detail)
        self.assertEqual(recorded, [(5, "héllo")])


class KeyFallbackTests(unittest.TestCase):
    def test_named_keys_use_key_codes_not_literal_words(self) -> None:
        """
        Without Quartz, `keystroke "tab"` types the literal letters t-a-b.
        Named keys must go through `key code N` like return already did.
        """
        scripts: List[str] = []

        def fake_osascript(script: str, timeout: float = 0):
            scripts.append(script)
            return 0, ""

        expected = {
            "tab": 48,
            "space": 49,
            "delete": 51,
            "backspace": 51,
            "escape": 53,
            "esc": 53,
            "return": 36,
            "enter": 36,
        }
        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch.object(cua, "_osascript", side_effect=fake_osascript):
                for name, keycode in expected.items():
                    scripts.clear()
                    ok, detail = cua._key(name)
                    self.assertTrue(ok, f"{name}: {detail}")
                    self.assertEqual(len(scripts), 1, name)
                    self.assertIn(f"key code {keycode}", scripts[0], name)
                    self.assertNotIn(f'keystroke "{name}"', scripts[0], name)

    def test_single_letter_still_uses_keystroke(self) -> None:
        scripts: List[str] = []
        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch.object(
                cua,
                "_osascript",
                side_effect=lambda script, timeout=0: (scripts.append(script), (0, ""))[1],
            ):
                ok, detail = cua._key("c")
        self.assertTrue(ok, detail)
        self.assertEqual(scripts, ['tell application "System Events" to keystroke "c"'])


class KeyChordParseTests(unittest.TestCase):
    def test_bare_dash_is_a_key(self) -> None:
        """'-' must not be mangled by the chord-separator normalization."""
        mods, primary = cua.parse_key_chord("-")
        self.assertEqual(mods, [])
        self.assertEqual(primary, "-")

    def test_dash_types_via_unicode_path(self) -> None:
        recorded: List[Tuple[int, str]] = []
        with mock.patch.dict(
            sys.modules, {"Quartz": _unicode_recording_quartz(recorded)}
        ):
            ok, detail = cua._key("-")
        self.assertTrue(ok, detail)
        self.assertEqual(recorded, [(1, "-")])


class _FakeAXModule:
    """Minimal ApplicationServices stand-in walking a fresh-object chain."""

    kAXRoleAttribute = "AXRole"
    kAXTitleAttribute = "AXTitle"
    kAXDescriptionAttribute = "AXDescription"
    kAXIdentifierAttribute = "AXIdentifier"
    kAXValueAttribute = "AXValue"
    kAXPositionAttribute = "AXPosition"
    kAXSizeAttribute = "AXSize"
    kAXChildrenAttribute = "AXChildren"

    def __init__(self, chain_length: int):
        self.remaining = chain_length

    @staticmethod
    def AXUIElementCreateApplication(_pid: int) -> Any:
        return object()

    def AXUIElementCopyAttributeValue(self, _element, attribute, _ref):
        if attribute == self.kAXChildrenAttribute:
            if self.remaining > 0:
                self.remaining -= 1
                # A brand-new object per child: freed parents' memory (and
                # therefore id()) is reused by later children on CPython.
                return 0, [object()]
            return 0, []
        if attribute == self.kAXRoleAttribute:
            return 0, "AXGroup"
        return 0, ""


class AccessibilityTreeTests(unittest.TestCase):
    def test_nodes_not_dropped_by_id_reuse(self) -> None:
        """
        Dedup keyed on id() is only safe while every element stays alive;
        otherwise CPython reuses a freed element's address for the next one
        and the live node is skipped as 'seen'.
        """
        fake_as = _FakeAXModule(chain_length=6)
        with mock.patch.dict(sys.modules, {"ApplicationServices": fake_as}):
            with mock.patch.object(
                comp_session.cua, "_window_info", return_value={"owner_pid": 999}
            ):
                nodes, _ = comp_session.accessibility_tree(frontmost=True)
        self.assertEqual(len(nodes), 7, f"nodes dropped: {len(nodes)}")


def _ok_shot() -> Dict[str, Any]:
    return {
        "ok": True,
        "action": "screenshot",
        "image_b64": "x" * 220,
        "mime": "image/png",
        "width": 10,
        "height": 10,
        "scale": 1.0,
        "display_id": 1,
        "coordinate_space": "logical_points",
        "displays": [{"display_id": 1}],
    }


class SessionLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = comp_session.ComputerSessionManager(
            store=ControlStore(Path(self._tmp.name) / "control.db"),
            capture=lambda **_kw: _ok_shot(),
            inspect=lambda **_kw: ([], {}),
            action=lambda *_a, **_kw: {"ok": True, "action": "click"},
        )
        patcher = mock.patch.object(comp_session, "COMPUTER", self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_legacy_screenshot_releases_lease(self) -> None:
        """
        A one-shot screenshot borrowed the single active lease but never
        released it, so the next session start failed with 'another
        computer-use session owns the machine' until the lease expired.
        """
        result = comp_session.compatibility_cua_action({"action": "screenshot"})
        self.assertTrue(result.get("ok"), result)
        try:
            again = self.manager.start()
        except RuntimeError as exc:
            self.fail(f"screenshot leaked the active lease: {exc}")
        self.manager.finish(str(again["id"]))

    def test_legacy_screenshot_failure_releases_lease(self) -> None:
        self.manager.capture = lambda **_kw: {"ok": False, "error": "denied"}
        result = comp_session.compatibility_cua_action({"action": "screenshot"})
        self.assertFalse(result.get("ok"))
        try:
            again = self.manager.start()
        except RuntimeError as exc:
            self.fail(f"failed screenshot leaked the active lease: {exc}")
        self.manager.finish(str(again["id"]))

    def test_legacy_act_exception_still_releases_lease(self) -> None:
        def boom(*_a, **_kw):
            raise ValueError("synthetic action failure")

        self.manager.action = boom
        with self.assertRaises(ValueError):
            comp_session.compatibility_cua_action({"action": "click", "x": 1, "y": 2})
        try:
            again = self.manager.start()
        except RuntimeError as exc:
            self.fail(f"raising action leaked the active lease: {exc}")
        self.manager.finish(str(again["id"]))

    def test_supplied_session_survives_screenshot(self) -> None:
        started = self.manager.start()
        session_id = str(started["id"])
        result = comp_session.compatibility_cua_action(
            {"action": "screenshot", "session_id": session_id}
        )
        self.assertTrue(result.get("ok"), result)
        kept = self.manager.status(session_id)
        self.assertTrue(kept.get("ok"))
        self.assertEqual(kept["session"]["state"], "active")
        self.manager.finish(session_id)


class ActTargetIndexTests(unittest.TestCase):
    def test_bad_index_returns_error_not_exception(self) -> None:
        """Every other target validation returns an error dict; a malformed
        index must not raise out of act()."""
        with tempfile.TemporaryDirectory() as tmp:
            manager = comp_session.ComputerSessionManager(
                store=ControlStore(Path(tmp) / "control.db"),
                capture=lambda **_kw: _ok_shot(),
                inspect=lambda **_kw: (
                    [{"id": "n1", "role": "AXButton", "title": "OK"}],
                    {},
                ),
                action=lambda *_a, **_kw: {"ok": True},
            )
            session_id = str(manager.start()["id"])
            observed = manager.observe(session_id)
            self.assertTrue(observed.get("ok"), observed)
            result = manager.act(
                session_id,
                {
                    "action": "click",
                    "target": {"kind": "semantic", "role": "AXButton", "index": "first"},
                },
            )
            self.assertFalse(result.get("ok"))
            self.assertIn("index", str(result.get("error")))


if __name__ == "__main__":
    unittest.main()

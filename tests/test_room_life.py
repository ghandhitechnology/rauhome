"""
Moving things around the room, and making things to put on the wall.

Run: python -m unittest tests.test_room_life -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.events import BUS  # noqa: E402
from rau.face import choreography, panels, props  # noqa: E402


class Recorder:
    """Collect bus events for the duration of a test."""

    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def stop(self) -> None:
        with BUS._lock:  # noqa: SLF001 — the bus has no public detach
            BUS._subs["*"] = [fn for fn in BUS._subs["*"] if fn is not self._append]


class MoveObjectTests(unittest.TestCase):
    def setUp(self) -> None:
        props.reset_layout()

    def tearDown(self) -> None:
        props.reset_layout()

    def test_an_errand_moves_the_object_and_announces_the_journey(self) -> None:
        recorder = Recorder("prop_move")
        try:
            with choreography.turn_scope("turn_1"):
                result = props.move_object({"object": "mug", "to": "shelf"})
        finally:
            recorder.stop()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["from"], "desk")
        self.assertEqual(result["to"], "shelf")
        self.assertTrue(result["errand_id"].startswith("errand_"))
        self.assertEqual(props.layout()["mug"], "shelf")

        moves = recorder.of("prop_move")
        self.assertEqual(len(moves), 1)
        # Both ends travel with the event: the renderer has to walk *from*
        # somewhere, and it cannot ask afterwards because the layout has
        # already moved on.
        self.assertEqual(moves[0]["from"], "desk")
        self.assertEqual(moves[0]["to"], "shelf")
        self.assertEqual(moves[0]["object"], "mug")
        self.assertEqual(moves[0]["layout"]["mug"], "shelf")

    def test_the_turn_is_carried_so_a_barge_in_can_drop_the_errand(self) -> None:
        recorder = Recorder("prop_move")
        try:
            with choreography.turn_scope("turn_abc"):
                props.move_object({"object": "books", "to": "shelf"})
        finally:
            recorder.stop()
        self.assertEqual(recorder.of("prop_move")[0]["turn_id"], "turn_abc")

    def test_moving_something_to_where_it_already_is_is_refused(self) -> None:
        result = props.move_object({"object": "mug", "to": "desk"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "already_there")
        # And no errand is published, so nobody walks across the room for it.
        recorder = Recorder("prop_move")
        try:
            props.move_object({"object": "mug", "to": "desk"})
        finally:
            recorder.stop()
        self.assertEqual(recorder.of("prop_move"), [])

    def test_unknown_objects_and_places_are_refused(self) -> None:
        self.assertEqual(
            props.move_object({"object": "piano", "to": "shelf"})["code"],
            "unknown_object",
        )
        self.assertEqual(
            props.move_object({"object": "mug", "to": "the_moon"})["code"],
            "unknown_spot",
        )
        self.assertEqual(
            props.move_object({"object": "mug", "to": "shelf", "speed": 3})["code"],
            "unknown_field",
        )
        self.assertEqual(props.move_object("put it away")["code"], "malformed")

    def test_the_layout_survives_for_the_next_turn_to_read(self) -> None:
        with choreography.turn_scope("t"):
            props.move_object({"object": "plant", "to": "sill"})
        described = props.describe_layout()
        self.assertIn("the potted plant is on the window sill", described)
        self.assertIn("the potted plant", props.prompt_fragment())

    def test_reset_puts_everything_home(self) -> None:
        with choreography.turn_scope("t"):
            props.move_object({"object": "box", "to": "rug"})
        self.assertEqual(props.layout()["box"], "rug")
        props.reset_layout()
        self.assertEqual(props.layout()["box"], props.PROPS["box"]["home"])

    def test_the_renderer_and_the_tool_agree_on_objects_and_places(self) -> None:
        web = Path(__file__).resolve().parent.parent / "web" / "src" / "clawd"
        source = (web / "props.ts").read_text()

        def names(marker: str) -> List[str]:
            block = source.split(marker, 1)[1].split("]", 1)[0]
            return re.findall(r"'(\w+)'", block)

        self.assertEqual(names("export const PROP_IDS = ["), list(props.PROP_IDS))
        self.assertEqual(names("export const SPOT_IDS = ["), list(props.SPOT_IDS))

        # Every place must also have somewhere for him to stand, or an errand
        # to it is a walk to nowhere.
        spots = source.split("export const PROP_SPOTS", 1)[1].split("}\n", 1)[0]
        for spot in props.SPOT_IDS:
            self.assertIn(f"{spot}:", spots, f"{spot} has no coordinates")


class ShowPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        panels.clear_panels()

    def tearDown(self) -> None:
        panels.clear_panels()

    def test_a_panel_is_stored_wrapped_and_announced(self) -> None:
        recorder = Recorder("panel_shown")
        try:
            with choreography.turn_scope("turn_2"):
                result = panels.show_panel(
                    {"title": "This week", "kind": "dashboard", "html": "<h1>Hi</h1>"}
                )
        finally:
            recorder.stop()

        self.assertTrue(result["ok"], result)
        shown = recorder.of("panel_shown")
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0]["title"], "This week")
        # Not `kind`: that names the event on the bus, and passing both raises.
        self.assertEqual(shown[0]["panel_kind"], "dashboard")
        self.assertEqual(shown[0]["turn_id"], "turn_2")

        panel = panels.get_panel(result["panel_id"])
        self.assertIsNotNone(panel)
        assert panel is not None
        self.assertIn("<h1>Hi</h1>", panel["document"])
        self.assertIn("<!doctype html>", panel["document"])

    def test_the_document_ships_a_policy_that_forbids_the_network(self) -> None:
        """
        The markup is model-written and is treated as hostile. This is the
        barrier that means a panel cannot send anything anywhere, even though
        its own inline script is allowed to run.
        """
        with choreography.turn_scope("t"):
            result = panels.show_panel({"title": "t", "html": "<p>x</p>"})
        document = panels.get_panel(result["panel_id"])["document"]
        self.assertIn("Content-Security-Policy", document)
        self.assertIn("default-src 'none'", panels.CSP)
        # Inline script and style are the only way a self-contained panel can
        # be interactive, so those are allowed — and nothing else is.
        self.assertIn("script-src 'unsafe-inline'", panels.CSP)
        for directive in ("connect-src", "frame-src", "object-src"):
            self.assertNotIn(directive, panels.CSP, f"{directive} would widen default-src")

    def test_the_title_cannot_break_out_of_the_skeleton(self) -> None:
        document = panels.wrap_document('</title><script>alert(1)</script>', "<p>x</p>")
        self.assertNotIn("<script>alert(1)</script>", document)
        self.assertIn("&lt;script&gt;", document)

    def test_oversized_and_malformed_panels_are_refused(self) -> None:
        self.assertEqual(
            panels.show_panel({"title": "t", "html": "y" * (panels.MAX_HTML_BYTES + 1)})["code"],
            "html_too_large",
        )
        self.assertEqual(panels.show_panel({"title": "", "html": "y"})["code"], "missing_title")
        self.assertEqual(panels.show_panel({"title": "t", "html": "  "})["code"], "missing_html")
        self.assertEqual(
            panels.show_panel({"title": "t", "kind": "hologram", "html": "y"})["code"],
            "unknown_kind",
        )
        self.assertEqual(
            panels.show_panel({"title": "t", "html": "y", "css": "x"})["code"],
            "unknown_field",
        )

    def test_the_wall_does_not_grow_without_bound(self) -> None:
        with choreography.turn_scope("t"):
            for i in range(panels.MAX_PANELS + 5):
                panels.show_panel({"title": f"panel {i}", "html": "<p>x</p>"})
        listed = panels.list_panels()
        self.assertEqual(len(listed), panels.MAX_PANELS)
        # Newest first, and the oldest have come down.
        self.assertEqual(listed[0]["title"], f"panel {panels.MAX_PANELS + 4}")
        self.assertNotIn("panel 0", [p["title"] for p in listed])

    def test_listings_never_carry_the_documents(self) -> None:
        with choreography.turn_scope("t"):
            panels.show_panel({"title": "t", "html": "<p>secret</p>"})
        for entry in panels.list_panels():
            self.assertNotIn("document", entry)


class ToolRegistrationTests(unittest.TestCase):
    def test_the_face_can_reach_both_tools(self) -> None:
        from rau.face import brain

        names = {t["function"]["name"] for t in brain.FACE_TOOLS}
        self.assertIn("move_object", names)
        self.assertIn("show_panel", names)

    def test_the_prompt_tells_the_model_what_is_in_the_room(self) -> None:
        from rau.face import brain

        prompt = brain._system_prompt()  # noqa: SLF001 — the thing under test
        self.assertIn("move_object", prompt)
        self.assertIn("show_panel", prompt)
        # Where things actually are, not just that objects exist.
        self.assertIn("the mug is on", prompt)


if __name__ == "__main__":
    unittest.main()

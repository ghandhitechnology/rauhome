"""
Moving things around the room, and making things to put on the wall.

Run: python -m unittest tests.test_room_life -v
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.control.store import control_store  # noqa: E402
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


class PanelStoreIsolation(unittest.TestCase):
    """
    Point the wall at a throwaway database for the duration of a test.

    Panels used to live in a module-level dict, so `clear_panels()` in a test
    cost nothing. They are rows now, and the store is a process-wide singleton
    — without this, running the suite would delete whatever the user actually
    has on their wall.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rau-panels-")
        self._real_path = control_store.path
        self._real_ready = control_store._ready  # noqa: SLF001
        control_store.path = Path(self._tmp.name) / "control.db"
        control_store._ready = False  # noqa: SLF001 — forces re-initialize
        control_store.initialize()

    def tearDown(self) -> None:
        control_store.path = self._real_path
        control_store._ready = self._real_ready  # noqa: SLF001
        self._tmp.cleanup()


class ShowPanelTests(PanelStoreIsolation):
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

    def test_raw_tool_json_is_recovered_into_a_panel(self) -> None:
        """Providers put broken streamed args in `_raw`; dashboards still go up."""
        payload = {
            "title": "Incheon weather",
            "kind": "dashboard",
            "html": "<div class=\"card\"><h1>12°</h1><style>.card{color:red}</style></div>",
        }
        raw = json.dumps(payload, ensure_ascii=False)
        # Truncated mid-string the way a streamed tool call often arrives.
        truncated = raw[:-8]
        with choreography.turn_scope("turn_raw"):
            result = panels.show_panel({"_raw": truncated})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["kind"], "dashboard")
        panel = panels.get_panel(result["panel_id"])
        self.assertIsNotNone(panel)
        assert panel is not None
        self.assertIn("Incheon weather", panel["document"])
        self.assertIn("12°", panel["document"])

    def test_raw_fence_and_extra_noise_still_recover(self) -> None:
        payload = json.dumps(
            {"title": "Note", "html": "<p>hi</p>"},
            ensure_ascii=False,
        )
        fenced = f"```json\n{payload}\n```"
        with choreography.turn_scope("turn_fence"):
            result = panels.show_panel({"_raw": fenced})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["title"], "Note")

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
            self.assertNotIn("body", entry)


class PanelPersistenceTests(PanelStoreIsolation):
    """The wall lives in control.db, so it has to outlive the process."""

    def test_a_panel_is_readable_from_the_store_not_a_module_dict(self) -> None:
        made = panels.show_panel({"title": "Kept", "html": "<p>still here</p>"})
        row = control_store.get_panel(made["panel_id"])
        self.assertIsNotNone(row)
        # The raw fragment is what is stored — the document is rendered on read,
        # which is what makes anchor-based editing possible at all.
        self.assertEqual(row["body"], "<p>still here</p>")
        self.assertNotIn("<!doctype html>", row["body"])
        self.assertIn("<!doctype html>", panels.get_panel(made["panel_id"])["document"])

    def test_headings_give_the_model_an_outline_without_the_body(self) -> None:
        panels.show_panel(
            {
                "title": "Weather",
                "html": "<h1>Incheon</h1><p>12</p><h2>Wind &amp; rain</h2>",
            }
        )
        entry = panels.list_panels()[0]
        self.assertEqual(entry["headings"], ["Incheon", "Wind & rain"])


class PanelEditingTests(PanelStoreIsolation):
    def setUp(self) -> None:
        super().setUp()
        self.panel_id = panels.show_panel(
            {
                "title": "Incheon weather",
                "kind": "dashboard",
                "html": "<h1>Incheon</h1><p id='now'>12°</p><p>steady</p>",
            }
        )["panel_id"]

    def test_a_patch_swaps_one_run_and_bumps_the_revision(self) -> None:
        result = panels.update_panel(
            {"panel_id": self.panel_id, "old": "12°", "new": "19°"}
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "patch")
        self.assertEqual(result["revision"], 2)
        self.assertIn("19°", panels.get_panel(self.panel_id)["body"])
        self.assertNotIn("12°", panels.get_panel(self.panel_id)["body"])

    def test_an_anchor_that_matches_twice_is_refused_rather_than_guessed(self) -> None:
        panels.update_panel({"panel_id": self.panel_id, "html": "<p>a</p><p>a</p>"})
        result = panels.update_panel(
            {"panel_id": self.panel_id, "old": "<p>a</p>", "new": "<p>b</p>"}
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "ambiguous_match")

    def test_a_missed_anchor_hands_back_the_nearest_real_text(self) -> None:
        # The excerpt is what stands in for a read-the-panel-back tool: the
        # model cannot afford to reread 96kB, so a failed patch has to teach it.
        result = panels.update_panel(
            {"panel_id": self.panel_id, "old": "<p id='now'>99°</p>", "new": "x"}
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "no_match")
        self.assertIn("12°", result["closest"])

    def test_a_replace_keeps_the_id_so_the_frame_does_not_jump(self) -> None:
        result = panels.update_panel(
            {"panel_id": self.panel_id, "html": "<h1>Rewritten</h1>", "title": "New"}
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["panel_id"], self.panel_id)
        self.assertEqual(result["mode"], "replace")
        self.assertEqual(panels.list_panels()[0]["title"], "New")
        self.assertEqual(panels.get_panel(self.panel_id)["body"], "<h1>Rewritten</h1>")

    def test_patch_and_replace_together_are_refused(self) -> None:
        result = panels.update_panel(
            {"panel_id": self.panel_id, "old": "a", "new": "b", "html": "<p>c</p>"}
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "conflicting_input")

    def test_editing_a_panel_that_is_not_there(self) -> None:
        result = panels.update_panel({"panel_id": "panel_nope", "html": "<p>x</p>"})
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "unknown_panel")

    def test_closing_is_permanent_and_announced(self) -> None:
        recorder = Recorder("panel_closed")
        try:
            result = panels.close_panel(self.panel_id)
        finally:
            recorder.stop()
        self.assertTrue(result["ok"], result)
        self.assertEqual([e["panel_id"] for e in recorder.events], [self.panel_id])
        self.assertIsNone(panels.get_panel(self.panel_id))
        self.assertEqual(panels.list_panels(), [])
        # And there is no archive to bring it back from.
        self.assertFalse(panels.close_panel(self.panel_id)["ok"])

    def test_presenting_announces_but_does_not_change_the_wall(self) -> None:
        recorder = Recorder("panel_presented")
        try:
            result = panels.present_panel(self.panel_id)
        finally:
            recorder.stop()
        self.assertTrue(result["ok"], result)
        self.assertEqual([e["panel_id"] for e in recorder.events], [self.panel_id])
        self.assertEqual(len(panels.list_panels()), 1)

    def test_presenting_something_that_is_gone_is_an_error_not_an_event(self) -> None:
        recorder = Recorder("panel_presented")
        try:
            result = panels.present_panel("panel_nope")
        finally:
            recorder.stop()
        self.assertFalse(result["ok"], result)
        self.assertEqual(recorder.events, [])


class SubagentPanelTests(PanelStoreIsolation):
    """A worker has to be able to hang what it built, or the work is invisible."""

    def test_the_schema_is_registered_so_arguments_validate(self) -> None:
        from rau.agent.tool_registry import descriptor, validate_arguments

        self.assertIsNotNone(descriptor("show_panel"))
        self.assertEqual(
            validate_arguments("show_panel", {"title": "t", "html": "<p>x</p>"}),
            {"title": "t", "html": "<p>x</p>"},
        )

    def test_a_panel_never_stops_a_worker_to_ask_permission(self) -> None:
        from rau.agent.tool_registry import descriptor

        # A sandboxed frame that cannot reach the network is not worth an
        # approval prompt, and pausing for one would strand a commissioned
        # dashboard halfway.
        self.assertEqual(descriptor("show_panel").approval_policy, "never")

    def test_panel_tools_reach_a_visual_goal_only(self) -> None:
        from rau.agent.executors import tools_for_goal

        visual = {t["function"]["name"] for t in tools_for_goal("Build a dashboard panel: x")}
        other = {t["function"]["name"] for t in tools_for_goal("reply to that email")}
        self.assertIn("show_panel", visual)
        self.assertNotIn("show_panel", other)

    def test_a_worker_hangs_a_panel_stamped_with_its_job(self) -> None:
        from rau.agent.tools import run_tool

        result = run_tool(
            "show_panel",
            {"title": "From a worker", "html": "<p>done</p>", "kind": "report"},
            job_id="job_123",
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(panels.panels_for_job("job_123")[0]["title"], "From a worker")
        self.assertEqual(panels.list_panels()[0]["source"], "subagent")

    def test_the_finished_job_summary_names_what_went_up(self) -> None:
        from rau.agent.orchestrator import _with_panels_note
        from rau.agent.tools import run_tool

        run_tool("show_panel", {"title": "Sales", "html": "<p>1</p>"}, job_id="job_9")
        woven = _with_panels_note("job_9", "Counted everything.")
        # Without this the user would find a panel on the wall with no idea
        # where it came from — the worker never speaks for itself.
        self.assertIn("Counted everything.", woven)
        self.assertIn("Sales", woven)
        self.assertEqual(_with_panels_note("job_none", "Nothing made."), "Nothing made.")


class ToolRegistrationTests(unittest.TestCase):
    def test_the_face_can_reach_both_tools(self) -> None:
        from rau.face import brain

        names = {t["function"]["name"] for t in brain.FACE_TOOLS}
        self.assertIn("move_object", names)
        self.assertIn("show_panel", names)

    def test_the_face_can_tend_the_wall_not_only_add_to_it(self) -> None:
        from rau.face import brain

        names = {t["function"]["name"] for t in brain.FACE_TOOLS}
        for tool in (
            "list_panels",
            "update_panel",
            "close_panel",
            "present_panel",
            "commission_panel",
        ):
            self.assertIn(tool, names)
            # Spoken requests reach these on the first round; waiting for round
            # two is what made them feel unreachable by voice.
            self.assertIn(tool, brain.VOICE_SLIM_TOOL_NAMES)

    def test_the_prompt_tells_the_model_what_is_in_the_room(self) -> None:
        from rau.face import brain

        prompt = brain._system_prompt()  # noqa: SLF001 — the thing under test
        self.assertIn("move_object", prompt)
        self.assertIn("show_panel", prompt)
        # Where things actually are, not just that objects exist.
        self.assertIn("the mug is on", prompt)


if __name__ == "__main__":
    unittest.main()

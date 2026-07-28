"""
Tests for LLM-directed body choreography.

Covers the tool itself (registration, schema, validation, payload limits),
its binding to a server-generated turn (correlation, cancellation, the fact
that it never asks for a confirmation the face cannot wait for), the live
event stream it rides on (ordering, `/api/chat` staying backward compatible),
and the voice timing that decides when a phrase-anchored cue actually fires.

Run: python -m unittest tests.test_body_choreography -v
"""
from __future__ import annotations

import re
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.events import BUS  # noqa: E402
from rau.face import choreography  # noqa: E402
from rau.providers.base import (  # noqa: E402
    ChatResult,
    StreamDone,
    TextDelta,
    ToolCall,
)


class Recorder:
    """Collect bus events for the duration of a test."""

    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def kinds(self) -> List[str]:
        return [event["kind"] for event in self.events]

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [event for event in self.events if event["kind"] == kind]

    def stop(self) -> None:
        with BUS._lock:  # noqa: SLF001 — the bus has no public detach
            BUS._subs["*"] = [fn for fn in BUS._subs["*"] if fn is not self._append]


class ToolRegistrationTests(unittest.TestCase):
    def test_face_exposes_the_tool_with_a_closed_world_schema(self) -> None:
        from rau.face import brain

        entry = next(
            tool
            for tool in brain.FACE_TOOLS
            if tool["function"]["name"] == "body_choreography"
        )
        item = entry["function"]["parameters"]["properties"]["cues"]["items"]
        self.assertEqual(item["properties"]["motion"]["enum"], list(choreography.MOTIONS))
        self.assertEqual(
            item["properties"]["station"]["enum"], list(choreography.STATIONS)
        )
        self.assertEqual(
            item["properties"]["gaze"]["enum"], list(choreography.GAZE_TARGETS)
        )
        self.assertEqual(item["properties"]["anchor"]["enum"], list(choreography.ANCHORS))
        self.assertEqual(
            entry["function"]["parameters"]["properties"]["cues"]["maxItems"],
            choreography.MAX_CUES,
        )

    def test_the_prompt_teaches_the_rules_the_validator_enforces(self) -> None:
        from rau.face import brain

        prompt = brain._system_prompt()  # noqa: SLF001 — the thing under test
        self.assertIn("body_choreography", prompt)
        for anchor in choreography.ANCHORS:
            self.assertIn(anchor, prompt)

    def test_the_renderer_and_the_tool_agree_on_the_vocabulary(self) -> None:
        """The enums are duplicated in TypeScript; drift would be silent."""
        web = Path(__file__).resolve().parent.parent / "web" / "src" / "clawd"

        def names(source: str, marker: str) -> List[str]:
            body = source.split(marker, 1)[1].split("]", 1)[0]
            return [
                chunk.strip().strip("'\",")
                for chunk in body.split("\n")
                if chunk.strip().startswith("'")
            ]

        body_ts = (web / "body.ts").read_text()
        self.assertEqual(
            names(body_ts, "export const BODY_MOTIONS = ["), list(choreography.MOTIONS)
        )
        self.assertEqual(
            names(body_ts, "export const BODY_STATIONS = ["), list(choreography.STATIONS)
        )
        self.assertEqual(
            names(body_ts, "export const GAZE_TARGETS = ["),
            list(choreography.GAZE_TARGETS),
        )

        # Motions and stations must also exist in the renderer's own tables.
        # The registry is assembled from two libraries — the conversational
        # clips and the occupational ones spread in from motionsLife.
        declared = set()
        for file, marker in (
            ("motions.ts", "export const MOTIONS = {"),
            ("motionsLife.ts", "export const LIFE_MOTIONS = {"),
        ):
            block = (web / file).read_text().split(marker, 1)[1].split("}", 1)[0]
            declared.update(re.findall(r"^\s*(\w+),\s*$", block, re.M))
        for motion in choreography.MOTIONS:
            self.assertIn(motion, declared, f"{motion} is not a real clip")
        # And nothing the renderer can play is missing from the tool, or the
        # model simply never learns that the clip exists.
        self.assertEqual(
            declared - {"LIFE_MOTIONS"},
            set(choreography.MOTIONS),
            "motions.ts and choreography.py disagree about what Rau can do",
        )
        room_ts = (web / "room.ts").read_text()
        for station in choreography.STATIONS:
            self.assertIn(f"id: '{station}'", room_ts, f"{station} is not a real place")

        # ...and the reverse. A station the renderer knows about but the tool
        # does not is a place in the room the model can never be sent to, which
        # is invisible until someone wonders why it never uses it.
        declared_stations = re.findall(r"\{ id: '(\w+)',", room_ts)
        self.assertTrue(declared_stations, "could not parse STATIONS from room.ts")
        self.assertEqual(
            sorted(set(declared_stations)),
            sorted(choreography.STATIONS),
            "room.ts and choreography.py disagree about where Rau can stand",
        )


class ValidationTests(unittest.TestCase):
    def submit(self, cues: Any) -> Dict[str, Any]:
        return choreography.submit_plan({"cues": cues}, turn_id="turn_test")

    def test_accepts_a_well_formed_plan_and_reports_what_it_took(self) -> None:
        result = self.submit(
            [
                {"anchor": "reply_start", "gaze": "user"},
                {
                    "anchor": "phrase",
                    "phrase": "the desk",
                    "motion": "type",
                    "station": "desk",
                    "hold_ms": 3000,
                },
                {"anchor": "reply_end", "motion": "wave"},
            ]
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["accepted_cues"], 3)
        self.assertTrue(result["plan_id"].startswith("plan_"))

    def test_defaults_a_hold_from_what_the_cue_actually_asks_for(self) -> None:
        cues = choreography.validate_cues(
            [
                {"anchor": "reply_start", "gaze": "user"},
                {"anchor": "reply_end", "motion": "wave"},
                {"anchor": "phrase", "phrase": "over there", "station": "window"},
            ]
        )
        self.assertEqual(cues[0]["hold_ms"], choreography.DEFAULT_HOLD_GAZE_MS)
        self.assertEqual(cues[1]["hold_ms"], choreography.DEFAULT_HOLD_MOTION_MS)
        self.assertEqual(cues[2]["hold_ms"], choreography.DEFAULT_HOLD_STATION_MS)

    def test_phrase_anchor_defaults_to_the_first_occurrence(self) -> None:
        cues = choreography.validate_cues(
            [{"anchor": "phrase", "phrase": "  hello  ", "motion": "nod"}]
        )
        self.assertEqual(cues[0]["phrase"], "hello")
        self.assertEqual(cues[0]["occurrence"], 1)

    def assertRejected(self, cues: Any, code: str, cue: Optional[int] = None) -> None:
        result = self.submit(cues)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], code, result)
        self.assertIsInstance(result["error"], str)
        if cue is not None:
            self.assertEqual(result.get("cue"), cue, result)

    def test_rejects_a_motion_the_renderer_does_not_have(self) -> None:
        self.assertRejected(
            [{"anchor": "reply_start", "motion": "moonwalk"}], "unknown_motion", 0
        )

    def test_rejects_an_invented_station_and_an_invented_gaze(self) -> None:
        self.assertRejected(
            [{"anchor": "reply_start", "station": "kitchen"}], "unknown_station", 0
        )
        self.assertRejected(
            [{"anchor": "reply_start", "gaze": "into the abyss"}], "unknown_gaze", 0
        )

    def test_rejects_a_malformed_anchor(self) -> None:
        self.assertRejected([{"anchor": "whenever", "motion": "wave"}], "malformed_anchor", 0)
        self.assertRejected([{"motion": "wave"}], "malformed_anchor", 0)

    def test_rejects_a_phrase_anchor_with_nothing_to_match(self) -> None:
        self.assertRejected(
            [{"anchor": "phrase", "motion": "nod"}], "missing_phrase", 0
        )
        self.assertRejected(
            [{"anchor": "phrase", "phrase": "   ", "motion": "nod"}],
            "missing_phrase",
            0,
        )

    def test_rejects_a_phrase_on_an_anchor_that_cannot_use_one(self) -> None:
        self.assertRejected(
            [{"anchor": "reply_end", "phrase": "bye", "motion": "wave"}],
            "conflicting_controls",
            0,
        )

    def test_rejects_a_cue_that_asks_for_nothing(self) -> None:
        self.assertRejected([{"anchor": "reply_start"}], "empty_cue", 0)

    def test_rejects_an_oversized_phrase(self) -> None:
        long = "x" * (choreography.MAX_PHRASE_CHARS + 1)
        self.assertRejected(
            [{"anchor": "phrase", "phrase": long, "motion": "nod"}],
            "phrase_too_long",
            0,
        )

    def test_rejects_holds_outside_the_bounds(self) -> None:
        for hold in (choreography.MIN_HOLD_MS - 1, choreography.MAX_HOLD_MS + 1):
            self.assertRejected(
                [{"anchor": "reply_start", "motion": "wave", "hold_ms": hold}],
                "hold_out_of_range",
                0,
            )
        self.assertRejected(
            [{"anchor": "reply_start", "motion": "wave", "hold_ms": "long"}],
            "malformed_hold",
            0,
        )
        self.assertRejected(
            [{"anchor": "reply_start", "motion": "wave", "hold_ms": True}],
            "malformed_hold",
            0,
        )

    def test_rejects_more_cues_than_a_turn_may_carry(self) -> None:
        cues = [
            {"anchor": "phrase", "phrase": f"word {i}", "motion": "nod"}
            for i in range(choreography.MAX_CUES + 1)
        ]
        self.assertRejected(cues, "too_many_cues")

    def test_rejects_a_plan_longer_than_the_ceiling(self) -> None:
        cues = [
            {
                "anchor": "phrase",
                "phrase": f"word {i}",
                "motion": "think",
                "hold_ms": choreography.MAX_HOLD_MS,
            }
            for i in range(choreography.MAX_CUES)
        ]
        # 8 x 8000ms = 64s, still inside two minutes.
        self.assertTrue(choreography.submit_plan({"cues": cues}, turn_id="t")["ok"])
        # Lower the ceiling to prove the check is real rather than unreachable.
        original = choreography.MAX_PLAN_MS
        choreography.MAX_PLAN_MS = 10_000
        try:
            self.assertRejected(cues, "plan_too_long")
        finally:
            choreography.MAX_PLAN_MS = original

    def test_rejects_two_cues_fighting_over_one_anchor(self) -> None:
        self.assertRejected(
            [
                {"anchor": "reply_start", "motion": "wave"},
                {"anchor": "reply_start", "motion": "nod"},
            ],
            "duplicate_anchor",
            1,
        )
        self.assertRejected(
            [
                {"anchor": "phrase", "phrase": "Hello", "motion": "wave"},
                {"anchor": "phrase", "phrase": "hello", "motion": "nod"},
            ],
            "duplicate_anchor",
            1,
        )

    def test_allows_the_same_phrase_at_a_different_occurrence(self) -> None:
        result = self.submit(
            [
                {"anchor": "phrase", "phrase": "again", "motion": "nod"},
                {
                    "anchor": "phrase",
                    "phrase": "again",
                    "occurrence": 2,
                    "motion": "shrug",
                },
            ]
        )
        self.assertTrue(result["ok"], result)

    def test_rejects_an_out_of_range_or_non_integer_occurrence(self) -> None:
        for occurrence in (0, choreography.MAX_OCCURRENCE + 1):
            self.assertRejected(
                [
                    {
                        "anchor": "phrase",
                        "phrase": "again",
                        "occurrence": occurrence,
                        "motion": "nod",
                    }
                ],
                "malformed_occurrence",
                0,
            )
        self.assertRejected(
            [
                {
                    "anchor": "phrase",
                    "phrase": "again",
                    "occurrence": "second",
                    "motion": "nod",
                }
            ],
            "malformed_occurrence",
            0,
        )

    def test_rejects_shapes_that_are_not_a_plan_at_all(self) -> None:
        self.assertRejected("wave at them", "malformed_plan")
        self.assertRejected([], "empty_plan")
        self.assertRejected(["wave"], "malformed_cue", 0)
        self.assertRejected(
            [{"anchor": "reply_start", "motion": "wave", "speed": 3}],
            "unknown_field",
            0,
        )
        self.assertFalse(
            choreography.submit_plan({"cues": [], "tempo": "fast"}, turn_id="t")["ok"]
        )


class TurnCorrelationTests(unittest.TestCase):
    def test_a_plan_outside_a_turn_is_refused_rather_than_broadcast(self) -> None:
        recorder = Recorder("body_plan")
        try:
            result = choreography.submit_plan(
                {"cues": [{"anchor": "reply_start", "motion": "wave"}]}
            )
        finally:
            recorder.stop()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_turn")
        self.assertEqual(recorder.of("body_plan"), [])

    def test_a_plan_carries_the_turn_the_server_opened_for_it(self) -> None:
        recorder = Recorder("body_plan")
        try:
            with choreography.turn_scope("turn_abc"):
                self.assertEqual(choreography.current_turn_id(), "turn_abc")
                result = choreography.submit_plan(
                    {"cues": [{"anchor": "reply_start", "motion": "wave"}]}
                )
            self.assertIsNone(choreography.current_turn_id())
        finally:
            recorder.stop()

        self.assertTrue(result["ok"])
        published = recorder.of("body_plan")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["turn_id"], "turn_abc")
        self.assertEqual(published[0]["plan_id"], result["plan_id"])
        self.assertEqual(published[0]["cues"][0]["motion"], "wave")

    def test_concurrent_turns_cannot_read_each_other_s_id(self) -> None:
        seen: Dict[str, Optional[str]] = {}
        started = threading.Barrier(2)

        def worker(name: str) -> None:
            with choreography.turn_scope(name):
                started.wait(timeout=2)
                seen[name] = choreography.current_turn_id()

        threads = [
            threading.Thread(target=worker, args=(name,))
            for name in ("turn_one", "turn_two")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(seen, {"turn_one": "turn_one", "turn_two": "turn_two"})

    def test_nested_scopes_restore_the_outer_turn(self) -> None:
        with choreography.turn_scope("outer"):
            with choreography.turn_scope("inner"):
                self.assertEqual(choreography.current_turn_id(), "inner")
            self.assertEqual(choreography.current_turn_id(), "outer")

    def test_cancelling_a_turn_announces_it_with_a_reason(self) -> None:
        recorder = Recorder("body_cancel")
        try:
            choreography.cancel_turn("turn_abc", "interrupted")
            choreography.cancel_turn("", "ignored")
        finally:
            recorder.stop()
        cancels = recorder.of("body_cancel")
        self.assertEqual(len(cancels), 1)
        self.assertEqual(cancels[0]["turn_id"], "turn_abc")
        self.assertEqual(cancels[0]["reason"], "interrupted")

    def test_the_tool_never_asks_for_a_confirmation_the_face_cannot_wait_for(self) -> None:
        from rau.face import brain

        with choreography.turn_scope("turn_visual"):
            result = brain._run_face_tool(  # noqa: SLF001 — the dispatch under test
                "body_choreography",
                {"cues": [{"anchor": "reply_start", "motion": "wave"}]},
            )
        self.assertTrue(result["ok"], result)
        self.assertNotIn("needs confirmation", str(result))


class FakeProvider:
    """A provider that calls the tool once, then speaks."""

    def __init__(self, cues: Any, prose: List[str]) -> None:
        self.cues = cues
        self.prose = prose
        self.rounds = 0

    def stream_turn(self, messages, **_kwargs):
        self.rounds += 1
        if self.rounds == 1:
            call = ToolCall(
                id="call_1", name="body_choreography", arguments={"cues": self.cues}
            )
            yield StreamDone(ChatResult(content="", tool_calls=[call]))
            return
        for chunk in self.prose:
            yield TextDelta(chunk)
        yield StreamDone(ChatResult(content="".join(self.prose)))

    def chat(self, messages, **_kwargs):
        return ChatResult(content="".join(self.prose))


class FaceTurnStreamTests(unittest.TestCase):
    """The event stream a client actually reconstructs a turn from."""

    def setUp(self) -> None:
        from rau.face import brain

        self.brain = brain
        self._diary = brain.append_diary
        self._soul = brain._system_prompt
        self._slot = brain.chat_for_slot
        self._prepare = brain.prepare_turn
        brain.append_diary = lambda *args, **kwargs: None
        brain._system_prompt = lambda extra="", **_kwargs: "soul"
        brain.reset_history()

    def tearDown(self) -> None:
        self.brain.append_diary = self._diary
        self.brain._system_prompt = self._soul
        self.brain.chat_for_slot = self._slot
        self.brain.prepare_turn = self._prepare
        self.brain.reset_history()

    def run_turn(self, cues: Any, prose: List[str], **kwargs) -> Any:
        provider = FakeProvider(cues, prose)
        self.brain.chat_for_slot = lambda _slot: (provider, {"model": "fake"})
        # Force a delta per token rather than the throttled default; the point
        # of the test is the ordering, not the rate limiter.
        original = self.brain.DELTA_INTERVAL_SEC
        self.brain.DELTA_INTERVAL_SEC = 0.0
        try:
            return self.brain.chat_streaming(
                "say something", on_token=lambda _t: None, **kwargs
            )
        finally:
            self.brain.DELTA_INTERVAL_SEC = original

    def test_the_plan_lands_between_the_turn_opening_and_its_first_word(self) -> None:
        recorder = Recorder(
            "chat_started", "body_plan", "chat_delta", "chat_done", "chat_error"
        )
        try:
            reply = self.run_turn(
                [{"anchor": "phrase", "phrase": "over here", "motion": "wave"}],
                ["Look ", "over here", " now."],
                turn_id="turn_stream",
            )
        finally:
            recorder.stop()

        kinds = recorder.kinds()
        self.assertEqual(kinds[0], "chat_started")
        self.assertEqual(kinds[1], "body_plan")
        self.assertEqual(kinds[-1], "chat_done")
        self.assertIn("chat_delta", kinds)
        self.assertNotIn("chat_error", kinds)
        # Every event names the same turn, and the plan's turn is that turn.
        self.assertEqual({event["turn_id"] for event in recorder.events}, {"turn_stream"})
        self.assertEqual(str(reply), "Look over here now.")
        self.assertEqual(recorder.of("chat_done")[0]["text"], "Look over here now.")
        self.assertEqual(reply.turn_id, "turn_stream")

    def test_deltas_are_cumulative_so_a_dropped_one_costs_no_text(self) -> None:
        recorder = Recorder("chat_delta")
        try:
            self.run_turn(
                [{"anchor": "reply_start", "motion": "perk"}],
                ["one ", "two ", "three"],
                turn_id="turn_cumulative",
            )
        finally:
            recorder.stop()

        texts = [event["text"] for event in recorder.of("chat_delta")]
        self.assertEqual(texts[-1], "one two three")
        for earlier, later in zip(texts, texts[1:]):
            self.assertTrue(later.startswith(earlier), texts)

    def test_the_phrase_a_cue_anchors_to_really_appears_in_the_reply(self) -> None:
        recorder = Recorder("body_plan", "chat_done")
        try:
            self.run_turn(
                [{"anchor": "phrase", "phrase": "over here", "motion": "wave"}],
                ["Look ", "over here", " now."],
                turn_id="turn_anchor",
            )
        finally:
            recorder.stop()
        phrase = recorder.of("body_plan")[0]["cues"][0]["phrase"]
        self.assertIn(phrase, recorder.of("chat_done")[0]["text"])

    def test_a_cancelled_turn_withdraws_its_plan_before_reporting_the_end(self) -> None:
        recorder = Recorder("body_plan", "body_cancel", "chat_done")
        stop = threading.Event()
        stop.set()
        try:
            with self.assertRaises(self.brain.Cancelled):
                self.run_turn(
                    [{"anchor": "reply_end", "motion": "wave"}],
                    ["never spoken"],
                    cancel=stop,
                    turn_id="turn_cut",
                )
        finally:
            recorder.stop()
        kinds = recorder.kinds()
        self.assertEqual(kinds, ["body_cancel", "chat_done"])
        self.assertEqual(recorder.of("body_cancel")[0]["reason"], "interrupted")
        self.assertTrue(recorder.of("chat_done")[0]["interrupted"])

    def test_a_failing_provider_withdraws_the_plan_and_says_why(self) -> None:
        class Broken(FakeProvider):
            def stream_turn(self, messages, **kwargs):
                yield TextDelta("half a sen")
                raise RuntimeError("provider fell over")

        provider = Broken([], [])
        self.brain.chat_for_slot = lambda _slot: (provider, {"model": "fake"})
        recorder = Recorder("body_cancel", "chat_error", "chat_done")
        try:
            with self.assertRaises(RuntimeError):
                self.brain.chat_streaming(
                    "say something", on_token=lambda _t: None, turn_id="turn_broken"
                )
        finally:
            recorder.stop()
        self.assertEqual(recorder.kinds(), ["body_cancel", "chat_error"])
        self.assertEqual(recorder.of("body_cancel")[0]["reason"], "error")
        self.assertIn("provider fell over", recorder.of("chat_error")[0]["detail"])

    def test_a_meta_command_still_opens_and_closes_its_turn(self) -> None:
        recorder = Recorder("chat_started", "chat_done")
        try:
            self.brain.chat_streaming(
                "/skills", on_token=lambda _t: None, turn_id="turn_meta"
            )
        finally:
            recorder.stop()
        self.assertEqual(recorder.kinds(), ["chat_started", "chat_done"])


class ChatEndpointTests(unittest.TestCase):
    def test_api_chat_keeps_the_whole_reply_and_names_its_turn(self) -> None:
        from rau.hub import server

        captured: Dict[str, Any] = {}

        def fake_streaming(text, *, on_token, turn_id=None, **_kwargs):
            captured["text"] = text
            captured["turn_id"] = turn_id
            on_token("streamed ")
            on_token("reply")
            return "streamed reply"

        original = server.state.push_control
        server.state.push_control = lambda _cmd: None
        from rau.face import brain

        original_streaming = brain.chat_streaming
        brain.chat_streaming = fake_streaming
        try:
            result = server.api_chat(server.ChatIn(text="hello"))
        finally:
            brain.chat_streaming = original_streaming
            server.state.push_control = original

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "streamed reply")
        self.assertTrue(result["turn_id"].startswith("turn_"))
        self.assertEqual(captured["turn_id"], result["turn_id"])
        self.assertEqual(captured["text"], "hello")

    def test_a_superseded_http_turn_never_logs_or_speaks_a_stale_reply(self) -> None:
        from rau.face import brain
        from rau.hub import server

        cancelled = brain.Cancelled(
            generated="old partial",
            user_text="old question",
            turn_id="turn_old",
        )
        logs: List[Tuple[Any, ...]] = []
        controls: List[Dict[str, Any]] = []
        with (
            mock.patch.object(brain, "chat_streaming", side_effect=cancelled),
            mock.patch.object(brain, "finish_interrupted_turn") as finish,
            mock.patch.object(server.state, "add_log", side_effect=lambda *a: logs.append(a)),
            mock.patch.object(
                server.state,
                "push_control",
                side_effect=lambda item: controls.append(item),
            ),
        ):
            result = server.api_chat(server.ChatIn(text="old question"))

        self.assertTrue(result["interrupted"])
        self.assertEqual(result["reply"], "")
        finish.assert_called_once_with(cancelled, "old partial")
        self.assertEqual([item[0] for item in logs], ["user"])
        self.assertEqual(controls, [])


class VoiceTimingTests(unittest.TestCase):
    """Character timestamps, and what happens when they are not available."""

    def test_linear_fallback_spans_the_measured_duration(self) -> None:
        from rau.voice.tts_stream import linear_char_ms

        times = linear_char_ms("abcd", 400)
        self.assertEqual(times, [0.0, 100.0, 200.0, 300.0])
        self.assertEqual(linear_char_ms("", 400), [])

    def test_scaling_maps_timestamps_onto_processed_audio(self) -> None:
        from rau.voice.tts_stream import scale_char_ms

        self.assertEqual(scale_char_ms([0.0, 100.0], 1.5), [0.0, 150.0])
        self.assertEqual(scale_char_ms([0.0, 100.0], 1.0), [0.0, 100.0])
        self.assertEqual(scale_char_ms([], 2.0), [])

    def test_alignment_is_used_when_it_matches_the_sentence_we_sent(self) -> None:
        from rau.voice.tts_stream import _AlignmentCollector

        collector = _AlignmentCollector("hi!")
        collector.add((["h", "i"], [0.0, 0.2]))
        collector.add((["!"], [0.5]))
        timing = collector.finish(700)
        self.assertEqual(timing.char_ms, [0.0, 200.0, 500.0])
        self.assertEqual(timing.duration_ms, 700)

    def test_alignment_that_does_not_match_the_text_is_discarded(self) -> None:
        from rau.voice.tts_stream import _AlignmentCollector

        collector = _AlignmentCollector("hi!")
        # Text normalisation on the provider side rewrote what it spoke.
        collector.add((["h", "e", "y"], [0.0, 0.2, 0.4]))
        timing = collector.finish(300)
        self.assertEqual(timing.char_ms, [0.0, 100.0, 200.0])

    def test_no_alignment_at_all_falls_back_to_even_spacing(self) -> None:
        from rau.voice.tts_stream import _AlignmentCollector

        collector = _AlignmentCollector("abcd")
        collector.add(None)
        self.assertEqual(collector.finish(400).char_ms, [0.0, 100.0, 200.0, 300.0])


class SpeakStreamTimingTests(unittest.TestCase):
    """`speak_stream` end to end, against a fake ElevenLabs client."""

    def setUp(self) -> None:
        from rau.voice import tts_stream

        self.tts = tts_stream
        self._client = tts_stream._client
        self._slot = tts_stream.get_slot
        tts_stream.get_slot = lambda _name: {"voice_id": "v", "model": "m"}

    def tearDown(self) -> None:
        self.tts._client = self._client
        self.tts.get_slot = self._slot

    def install(self, alignment: bool = True) -> None:
        tts = self.tts

        class Alignment:
            def __init__(self, chars, starts):
                self.characters = chars
                self.character_start_times_seconds = starts

        class Chunk:
            def __init__(self, pcm, align):
                import base64

                self.audio_base_64 = base64.b64encode(pcm).decode()
                self.alignment = align

        class Speech:
            def stream_with_timestamps(self, *, voice_id, text, model_id, output_format):
                # 1 ms of audio per character, at 24 kHz mono PCM16.
                per_char = b"\x01\x00" * 24
                for index, char in enumerate(text):
                    yield Chunk(
                        per_char,
                        Alignment([char], [index / 1000.0]) if alignment else None,
                    )

            def stream(self, *, voice_id, text, model_id, output_format):
                yield b"\x01\x00" * 24 * len(text)

        class Client:
            text_to_speech = Speech()

        tts._client = lambda: Client()

    def collect(self, tokens: List[str], robot: bool = False):
        timings: List[Any] = []
        audio: List[bytes] = []
        for _ in self.tts.speak_stream(
            iter(tokens),
            on_audio=audio.append,
            on_timing=timings.append,
            robot=robot,
        ):
            pass
        return audio, timings

    def test_each_sentence_reports_its_own_character_timeline(self) -> None:
        self.install(alignment=True)
        _, timings = self.collect(["Hello there. ", "And again."])
        self.assertEqual([t.text for t in timings], ["Hello there.", "And again."])
        first = timings[0]
        self.assertEqual(len(first.char_ms), len(first.text))
        self.assertEqual(first.char_ms[0], 0.0)
        # Times are within the sentence, never the whole reply.
        self.assertLess(first.char_ms[-1], first.duration_ms + 1)
        self.assertTrue(all(b >= a for a, b in zip(first.char_ms, first.char_ms[1:])))

    def test_a_backend_without_timestamps_still_yields_usable_timing(self) -> None:
        self.install(alignment=False)
        _, timings = self.collect(["Just one sentence here."])
        timing = timings[0]
        self.assertEqual(len(timing.char_ms), len(timing.text))
        self.assertEqual(timing.char_ms[0], 0.0)
        self.assertGreater(timing.char_ms[-1], 0.0)

    def test_the_effects_pass_rescales_timestamps_to_the_audio_that_plays(self) -> None:
        self.install(alignment=True)

        class Doubler:
            def process_pcm(self, pcm: bytes) -> bytes:
                return pcm + pcm

        original = self.tts.RobotVoice
        self.tts.RobotVoice = Doubler
        try:
            audio, timings = self.collect(["Hello there."], robot=True)
        finally:
            self.tts.RobotVoice = original

        timing = timings[0]
        self.assertEqual(len(audio), 1)
        self.assertEqual(timing.duration_ms, self.tts.pcm_duration_ms(audio[0]))
        # Doubling the audio doubles where every character lands in it.
        self.assertAlmostEqual(timing.char_ms[1], 2.0, places=3)

    def test_a_cancelled_reply_stops_reporting_timings(self) -> None:
        self.install(alignment=True)
        cancel = threading.Event()
        cancel.set()
        timings: List[Any] = []
        for _ in self.tts.speak_stream(
            iter(["Hello there. ", "And again."]),
            on_audio=lambda _pcm: None,
            on_timing=timings.append,
            cancel=cancel,
            robot=False,
        ):
            pass
        self.assertEqual(timings, [])


class VoiceSessionChoreographyTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_turn_gets_an_id_and_a_barge_withdraws_its_plan(self) -> None:
        from rau.voice import session as voice_session

        sent: List[Dict[str, Any]] = []

        async def send_json(payload):
            sent.append(payload)

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        session._turn_body = lambda turn: turn.cancel.wait(0.5)  # type: ignore[method-assign]
        recorder = Recorder("body_cancel")
        try:
            await session.begin_turn("hello")
            turn = session._active_turn
            assert turn is not None
            self.assertTrue(turn.turn_id.startswith("turn_"))
            session.phase = "speaking"
            await session.barge(120.0)
            self.assertTrue(turn.cancel.is_set())
        finally:
            recorder.stop()
            await session.close()

        cancels = recorder.of("body_cancel")
        self.assertTrue(cancels)
        self.assertEqual(cancels[0]["turn_id"], turn.turn_id)
        self.assertEqual(cancels[0]["reason"], "interrupted")
        # The browser is told which reply was cut, so it can drop that plan too.
        cancelled = [frame for frame in sent if frame.get("t") == "cancelled"]
        self.assertEqual(cancelled[0]["turn_id"], turn.turn_id)

    async def test_a_superseding_turn_withdraws_the_plan_it_replaces(self) -> None:
        from rau.voice import session as voice_session

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        session._turn_body = lambda turn: turn.cancel.wait(0.5)  # type: ignore[method-assign]
        recorder = Recorder("body_cancel")
        try:
            await session.begin_turn("first")
            first = session._active_turn
            assert first is not None
            await session.begin_turn("second")
            second = session._active_turn
            assert second is not None
            self.assertNotEqual(first.turn_id, second.turn_id)
        finally:
            recorder.stop()
            await session.close()

        reasons = {
            event["turn_id"]: event["reason"] for event in recorder.of("body_cancel")
        }
        self.assertEqual(reasons.get(first.turn_id), "superseded")

    async def test_alignment_reaches_the_browser_placed_in_the_reply_timeline(self) -> None:
        from rau.voice import session as voice_session
        from rau.voice.tts_stream import SentenceTiming

        sent: List[Dict[str, Any]] = []

        async def send_json(payload):
            sent.append(payload)

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        captured: Dict[str, Any] = {}

        def fake_speak(tokens, *, on_audio, on_sentence, on_timing, cancel):
            captured["on_audio"] = on_audio
            captured["on_sentence"] = on_sentence
            captured["on_timing"] = on_timing
            for _ in tokens:
                pass
            return iter(())

        original_speak = voice_session.speak_stream
        original_brain = voice_session.brain.chat_streaming
        voice_session.speak_stream = fake_speak
        voice_session.brain.chat_streaming = (
            lambda text, **kwargs: kwargs["on_token"]("hi") or "hi"
        )
        try:
            await session.begin_turn("go")
            turn = session._active_turn
            assert turn is not None
            await _settle(lambda: "on_timing" in captured)

            # One sentence of 1000 samples, then a second one after it.
            pcm = b"\x00\x00" * 1000
            captured["on_sentence"]("First one.")
            captured["on_timing"](
                SentenceTiming("First one.", [0.0, 10.0], 41.6)
            )
            captured["on_audio"](pcm)
            captured["on_sentence"]("Second one.")
            captured["on_timing"](
                SentenceTiming("Second one.", [0.0, 12.0], 41.6)
            )
            captured["on_audio"](pcm)
            await _settle(
                lambda: len([f for f in sent if f.get("t") == "say_align"]) >= 2
            )
        finally:
            voice_session.speak_stream = original_speak
            voice_session.brain.chat_streaming = original_brain
            await session.close()

        aligns = [frame for frame in sent if frame.get("t") == "say_align"]
        self.assertEqual([frame["text"] for frame in aligns], ["First one.", "Second one."])
        self.assertEqual(aligns[0]["offset_ms"], 0.0)
        # The second sentence starts where the first one's audio ended.
        self.assertAlmostEqual(aligns[1]["offset_ms"], 41.7, places=1)
        self.assertEqual({frame["turn_id"] for frame in aligns}, {turn.turn_id})
        self.assertEqual(aligns[0]["char_ms"], [0.0, 10.0])


class EndToEndTests(unittest.TestCase):
    """
    A whole turn over the real wire: a model that choreographs and then speaks,
    an HTTP client that gets the finished reply, and a `/ws` client that gets
    the plan and the text it is anchored to, in order.
    """

    def test_a_choreographed_turn_reaches_a_browser_in_order(self) -> None:
        from fastapi.testclient import TestClient

        from rau.face import brain
        from rau.hub import server

        cues = [
            {"anchor": "reply_start", "gaze": "user", "hold_ms": 400},
            {
                "anchor": "phrase",
                "phrase": "over at the desk",
                "motion": "type",
                "station": "desk",
                "hold_ms": 2500,
            },
            {"anchor": "reply_end", "motion": "wave", "hold_ms": 900},
        ]
        prose = ["I left it ", "over at the desk", ", have a look."]
        provider = FakeProvider(cues, prose)

        saved = {
            "slot": brain.chat_for_slot,
            "soul": brain._system_prompt,
            "diary": brain.append_diary,
            "delta": brain.DELTA_INTERVAL_SEC,
            "dreamer": server.start_dreamer,
            "heartbeat": server.start_heartbeat,
        }
        brain.chat_for_slot = lambda _slot: (provider, {"model": "fake"})
        brain._system_prompt = lambda extra="", **_kwargs: "soul"
        brain.append_diary = lambda *args, **kwargs: None
        brain.DELTA_INTERVAL_SEC = 0.0
        # Background work is not what this is testing, and a dreamer waking up
        # mid-turn would reach for a real provider.
        server.start_dreamer = lambda: None
        server.start_heartbeat = lambda: None
        brain.reset_history()

        try:
            client = TestClient(server.app, base_url="http://127.0.0.1:8765")
            with client:
                # TestClient hard-codes "testserver" for sockets; the hub only
                # accepts a loopback Host, exactly as a browser would send.
                with client.websocket_connect(
                    "/ws",
                    headers={
                        "host": "127.0.0.1:8765",
                        "origin": "http://127.0.0.1:8765",
                    },
                ) as ws:
                    self.assertEqual(ws.receive_json()["kind"], "hello")
                    response = client.post("/api/chat", json={"text": "where is it?"})
                    self.assertEqual(response.status_code, 200)
                    body = response.json()

                    events: List[Dict[str, Any]] = []
                    for _ in range(200):
                        event = ws.receive_json()
                        if event.get("turn_id") != body["turn_id"]:
                            continue
                        events.append(event)
                        if event["kind"] in ("chat_done", "chat_error"):
                            break
        finally:
            brain.chat_for_slot = saved["slot"]
            brain._system_prompt = saved["soul"]
            brain.append_diary = saved["diary"]
            brain.DELTA_INTERVAL_SEC = saved["delta"]
            server.start_dreamer = saved["dreamer"]
            server.start_heartbeat = saved["heartbeat"]
            brain.reset_history()

        reply = "I left it over at the desk, have a look."
        self.assertTrue(body["ok"])
        self.assertEqual(body["reply"], reply)
        self.assertTrue(body["turn_id"].startswith("turn_"))

        kinds = [event["kind"] for event in events]
        self.assertEqual(kinds[0], "chat_started")
        self.assertEqual(kinds[1], "body_plan")
        self.assertEqual(kinds[-1], "chat_done")
        self.assertIn("chat_delta", kinds)

        plan = events[1]
        self.assertEqual(plan["plan_id"][:5], "plan_")
        self.assertEqual([c["anchor"] for c in plan["cues"]], [c["anchor"] for c in cues])
        self.assertEqual(plan["cues"][1]["station"], "desk")

        # The phrase the plan hangs on is really in the reply, and the deltas
        # give a client the moment at which it became visible.
        anchor = plan["cues"][1]["phrase"]
        self.assertIn(anchor, reply)
        deltas = [event["text"] for event in events if event["kind"] == "chat_delta"]
        first_visible = next(text for text in deltas if anchor in text)
        self.assertLess(len(first_visible), len(reply))
        self.assertEqual(events[-1]["text"], reply)

        # The log the rest of the UI polls agrees with what was streamed.
        from rau import state

        self.assertEqual(state.get_log()[-1], {**state.get_log()[-1], "text": reply})


async def _settle(done, timeout: float = 2.0) -> None:
    """Let the loop drain thread-safe callbacks until `done()` or timeout."""
    import asyncio

    deadline = asyncio.get_running_loop().time() + timeout
    while not done():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the session to settle")
        await asyncio.sleep(0.01)


if __name__ == "__main__":
    unittest.main()

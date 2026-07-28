"""
Regression tests for the face-brain stability sweep.

Covers: the six-round tool loop closing in prose instead of trailing off into
"one sec" narration, a barge-in keeping a record of the tools that already ran
(with the interruption note riding as a user parenthetical, never system), the
interruption note surviving a provider error that lands together with the
barge, the deferred diary write happening exactly once, table talk being
journaled when playback drains rather than when generation ends, a leading
mood tag never reaching the listener, per-turn skill prompts accumulating
instead of replacing each other, the compaction flag surviving a thread that
cannot start, a concurrent face turn getting a clear busy answer, the card
table being a place the model can send Rau, and the retired entry points
staying gone.

Run: python -m unittest tests.test_stability_face -v
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.face import brain, choreography  # noqa: E402
from rau.providers.base import (  # noqa: E402
    ChatResult,
    Message,
    StreamDone,
    TextDelta,
    ToolCall,
)


class ScriptedProvider:
    """Plays back scripted rounds: each `stream_turn` call serves the next one."""

    def __init__(self, rounds: List[Dict[str, Any]]) -> None:
        self.rounds = rounds
        self.calls: List[Dict[str, Any]] = []

    def stream_turn(self, messages, **kwargs):
        self.calls.append(kwargs)
        spec = self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]
        for delta in spec.get("deltas", []):
            yield TextDelta(delta)
        yield StreamDone(
            ChatResult(
                content=spec.get("content", ""),
                tool_calls=spec.get("tool_calls", []),
            )
        )

    def chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        spec = self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]
        return ChatResult(
            content=spec.get("content", ""),
            tool_calls=spec.get("tool_calls", []),
        )


def tool_round(call_id: str, name: str, narration: str) -> Dict[str, Any]:
    return {
        "deltas": [narration],
        "content": narration,
        "tool_calls": [ToolCall(id=call_id, name=name, arguments={})],
    }


class BrainTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._diary = brain.append_diary
        self._prompt = brain._system_prompt
        self._slot = brain.chat_for_slot
        self.diary: List[Any] = []
        brain.append_diary = lambda *args: self.diary.append(args)
        brain._system_prompt = lambda extra="", **_kwargs: "soul"
        brain.reset_history()

    def tearDown(self) -> None:
        brain.append_diary = self._diary
        brain._system_prompt = self._prompt
        brain.chat_for_slot = self._slot
        brain.reset_history()

    def install(self, provider: ScriptedProvider) -> None:
        brain.chat_for_slot = lambda _slot: (provider, {"model": "fake"})

    def test_the_last_tool_round_is_forced_to_close_in_prose(self) -> None:
        # F1: five rounds of tool calls used to leave the reply as nothing but
        # the "one sec" narration spoken before each call.
        provider = ScriptedProvider(
            [tool_round(f"call_{i}", "list_skills", "One sec— ") for i in range(5)]
            + [{"deltas": ["Done — the list is above."], "content": "Done — the list is above."}]
        )
        self.install(provider)

        reply = brain.chat_streaming("what can you do", on_token=lambda _t: None)

        self.assertEqual(len(provider.calls), 6)
        self.assertIsNotNone(provider.calls[0]["tools"])
        # The closing round leaves the model no way to call another tool.
        self.assertIsNone(provider.calls[-1]["tools"])
        self.assertIn("Done — the list is above.", str(reply))

    def test_a_barge_in_keeps_the_tools_that_ran_and_a_user_role_note(self) -> None:
        # F2 + F3 + F4: executed tools leave a one-line marker, the note is a
        # user parenthetical (system would be hoisted into Anthropic's
        # persistent prompt), and finishing twice changes nothing.
        cancel = threading.Event()
        provider = ScriptedProvider(
            [
                tool_round("call_1", "list_skills", "Looking… "),
                {"deltas": ["here you go"], "content": "here you go"},
            ]
        )
        self.install(provider)

        def on_tool(_name, _args, _result) -> None:
            cancel.set()

        with self.assertRaises(brain.Cancelled) as caught:
            brain.chat_streaming(
                "hi", on_token=lambda _t: None, on_tool=on_tool, cancel=cancel
            )
        brain.finish_interrupted_turn(caught.exception, "Looking…")
        history = brain.snapshot_history()
        brain.finish_interrupted_turn(caught.exception, "Looking…")
        self.assertEqual(history, brain.snapshot_history(), "second finish must be a no-op")

        markers = [m for m in history if "(tool list_skills ran:" in m.content]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].role, "user")
        notes = [m for m in history if "You were interrupted here" in m.content]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].role, "user")
        self.assertNotIn("system", {m.role for m in history})
        heard = [m for m in history if m.role == "assistant" and m.content == "Looking…"]
        self.assertEqual(len(heard), 1)
        self.assertEqual(self.diary, [("user", "hi"), ("rau", "Looking…")])

    def test_an_error_landing_with_the_barge_still_commits_the_note(self) -> None:
        # F4: the generic error path used to commit the heard prose without
        # the interruption note, so the next turn repeated itself.
        class BrokenProvider:
            def stream_turn(self, messages, **kwargs):
                yield TextDelta("half a sen")
                raise RuntimeError("provider fell over")

        self.install(BrokenProvider())
        cancel = threading.Event()

        def on_token(_token: str) -> None:
            cancel.set()

        with self.assertRaises(RuntimeError):
            brain.chat_streaming("hi", on_token=on_token, cancel=cancel)

        history = brain.snapshot_history()
        self.assertIn(
            ("assistant", "half a sen"), [(m.role, m.content) for m in history]
        )
        notes = [m for m in history if "You were interrupted here" in m.content]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].role, "user")
        self.assertEqual(self.diary, [("user", "hi"), ("rau", "half a sen")])

    def test_a_leading_mood_tag_never_reaches_the_listener(self) -> None:
        # F5: the tag sets the mood at the end of the turn, but must not be
        # spoken or shown while streaming.
        provider = ScriptedProvider(
            [{"deltas": ["[HA", "PPY]", " Hel", "lo."], "content": "[HAPPY] Hello."}]
        )
        self.install(provider)
        from rau import state

        before = state.get_emotion()
        tokens: List[str] = []
        try:
            reply = brain.chat_streaming("hi", on_token=tokens.append)
            self.assertEqual(state.get_emotion()["emotion"], "happy")
        finally:
            state.set_emotion(str(before.get("emotion") or "idle"), "")

        spoken_out = "".join(tokens)
        self.assertNotIn("[HAPPY]", spoken_out)
        self.assertNotIn("[", spoken_out)
        self.assertEqual(spoken_out.strip(), "Hello.")
        # heard keeps the raw text, so apply_reply_mood still cleans the reply.
        self.assertEqual(str(reply), "Hello.")

    def test_a_non_tag_bracket_is_passed_through_untouched(self) -> None:
        provider = ScriptedProvider(
            [{"deltas": ["[laughs] ", "hi"], "content": "[laughs] hi"}]
        )
        self.install(provider)
        tokens: List[str] = []
        brain.chat_streaming("hi", on_token=tokens.append)
        self.assertEqual("".join(tokens), "[laughs] hi")

    def test_two_skills_loaded_in_one_turn_both_steer_the_system_prompt(self) -> None:
        # F6: loading skill B used to rebuild the prompt from scratch, erasing
        # skill A's instructions loaded one round earlier.
        extras: List[str] = []
        brain._system_prompt = lambda extra="", **_kwargs: extras.append(extra) or "soul"
        provider = ScriptedProvider(
            [
                tool_round("call_1", "use_skill", "Loading… "),
                tool_round("call_2", "use_skill", "And the other… "),
                {"deltas": ["done"], "content": "done"},
            ]
        )
        self.install(provider)
        provider.rounds[0]["tool_calls"][0].arguments = {"name": "alpha"}
        provider.rounds[1]["tool_calls"][0].arguments = {"name": "beta"}

        with mock.patch.object(
            brain,
            "use_skill_tool",
            lambda name: {"ok": True, "prompt": f"loaded-{name}"},
        ):
            brain.chat_streaming("hi", on_token=lambda _t: None)

        self.assertTrue(
            any("loaded-alpha" in extra and "loaded-beta" in extra for extra in extras),
            extras,
        )

    def test_table_talk_is_journaled_when_playback_drains(self) -> None:
        # F8: a deferred (voice) turn used to journal the full reply the moment
        # generation ended, even if a later barge kept it off the air.
        records: List[Any] = []
        provider = ScriptedProvider([{"deltas": ["well played"], "content": "well played"}])
        self.install(provider)
        with (
            mock.patch.object(brain.kittens, "active", lambda: True),
            mock.patch(
                "rau.games.kittens.journal.record",
                lambda who, kind, text: records.append((who, kind, text)),
            ),
            mock.patch("rau.games.kittens.banter.note_user_chat", lambda: None),
        ):
            reply = brain.chat_streaming(
                "nice hand", on_token=lambda _t: None, defer_diary=True
            )
            self.assertEqual(records, [], "nothing journals at generation end")
            brain.commit_streamed_turn(reply)
            self.assertIn(("user", "user_chat", "nice hand"), records)
            self.assertIn(("rau", "rau_chat", "well played"), records)

    def test_an_interrupted_turn_journals_only_what_was_heard(self) -> None:
        records: List[Any] = []
        cancel = threading.Event()
        provider = ScriptedProvider(
            [{"deltas": ["heard half", " and the rest"], "content": "heard half and the rest"}]
        )
        self.install(provider)
        with (
            mock.patch.object(brain.kittens, "active", lambda: True),
            mock.patch(
                "rau.games.kittens.journal.record",
                lambda who, kind, text: records.append((who, kind, text)),
            ),
            mock.patch("rau.games.kittens.banter.note_user_chat", lambda: None),
        ):
            with self.assertRaises(brain.Cancelled) as caught:
                brain.chat_streaming(
                    "nice hand",
                    on_token=lambda _t: cancel.set(),
                    cancel=cancel,
                    defer_diary=True,
                )
            brain.finish_interrupted_turn(caught.exception, "heard half")
        self.assertIn(("rau", "rau_chat", "heard half"), records)
        self.assertNotIn(("rau", "rau_chat", "heard half and the rest"), records)

    def test_the_deferred_diary_write_happens_exactly_once(self) -> None:
        # F9: the marker-less branch was guarded only by a plain attribute and
        # could double-write when a barge raced the end of playback.
        reply = brain.StreamingReply("full reply", None, "question", True, "turn_x")
        brain.finish_interrupted_turn(reply, "heard")
        brain.finish_interrupted_turn(reply, "heard")
        brain.commit_streamed_turn(reply)
        self.assertEqual(self.diary, [("user", "question"), ("rau", "heard")])

    def test_finish_and_commit_racing_still_write_the_diary_once(self) -> None:
        reply = brain.StreamingReply("full", None, "q", True, "turn_y")
        barrier = threading.Barrier(2)

        def finish() -> None:
            barrier.wait(timeout=2)
            brain.finish_interrupted_turn(reply, "heard")

        def commit() -> None:
            barrier.wait(timeout=2)
            brain.commit_streamed_turn(reply)

        threads = [
            threading.Thread(target=finish),
            threading.Thread(target=commit),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(self.diary), 2, self.diary)
        self.assertEqual(self.diary[0], ("user", "q"))
        self.assertIn(self.diary[1], [("rau", "heard"), ("rau", "full")])

    def test_the_compaction_flag_survives_a_thread_that_cannot_start(self) -> None:
        # F10: a failed Thread.start used to leak the flag, silently disabling
        # all future compaction.
        with (
            mock.patch.object(brain.compaction, "should_compact", lambda _s, _b: True),
            mock.patch.object(
                brain, "snapshot_history", lambda: [Message(role="user", content="x")]
            ),
            mock.patch.object(
                brain.threading, "Thread", side_effect=RuntimeError("cannot start")
            ),
        ):
            brain._maybe_compact_history()
        self.assertTrue(
            brain._compacting.acquire(blocking=False),
            "the compaction flag leaked after a failed Thread.start",
        )
        brain._compacting.release()

    def test_a_second_face_turn_gets_a_clear_busy_answer(self) -> None:
        # F12: two concurrent turns would braid their replies into one history.
        provider = ScriptedProvider([{"deltas": ["hi"], "content": "hi"}])
        self.install(provider)
        acquired = brain._face_turn_lock.acquire(blocking=False)
        self.assertTrue(acquired, "turn lock held by a previous test?")
        try:
            tokens: List[str] = []
            out = brain.chat_streaming("hello", on_token=tokens.append)
            self.assertEqual(str(out), brain.BUSY_REPLY)
            self.assertEqual("".join(tokens), brain.BUSY_REPLY)
            self.assertEqual(brain.chat("hello"), brain.BUSY_REPLY)
        finally:
            brain._face_turn_lock.release()
        self.assertEqual(provider.calls, [], "a busy turn must not reach the provider")
        self.assertEqual(self.diary, [])
        # Once the first turn is done the next one runs normally again.
        reply = brain.chat_streaming("hello", on_token=lambda _t: None)
        self.assertEqual(str(reply), "hi")

    def test_a_system_turn_waits_out_the_turn_in_flight(self) -> None:
        # weave_result speaks for a finished deep-work job: there is no user
        # to re-ask, so bouncing with BUSY_REPLY would discard the result.
        provider = ScriptedProvider(
            [{"deltas": ["it is done"], "content": "it is done"}]
        )
        self.install(provider)
        acquired = brain._face_turn_lock.acquire(blocking=False)
        self.assertTrue(acquired, "turn lock held by a previous test?")
        out: List[str] = []

        def run_weave() -> None:
            out.append(brain.weave_result("goal", "result"))

        thread = threading.Thread(target=run_weave)
        try:
            thread.start()
            time.sleep(0.2)
            self.assertTrue(
                thread.is_alive(), "a system turn must wait, not bounce"
            )
            self.assertEqual(out, [])
        finally:
            brain._face_turn_lock.release()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(out, ["it is done"])
        self.assertEqual(self.diary[-1], ("rau", "it is done"))

    def test_a_system_turn_gives_up_after_the_wait_instead_of_hanging(self) -> None:
        provider = ScriptedProvider([{"content": "unreachable"}])
        self.install(provider)
        acquired = brain._face_turn_lock.acquire(blocking=False)
        self.assertTrue(acquired, "turn lock held by a previous test?")
        try:
            with mock.patch.object(brain, "SYSTEM_TURN_WAIT_SEC", 0.05):
                start = time.monotonic()
                self.assertEqual(
                    brain.weave_result("goal", "result"), brain.BUSY_REPLY
                )
                self.assertLess(time.monotonic() - start, 5.0)
        finally:
            brain._face_turn_lock.release()
        self.assertEqual(provider.calls, [], "a timed-out turn must not reach the provider")

    def test_the_retired_entry_points_are_gone(self) -> None:
        # F11: both were dead code with no production callers.
        self.assertFalse(hasattr(brain, "chat_stream"))
        self.assertFalse(hasattr(brain, "truncate_last_assistant"))


class CardTableStationTests(unittest.TestCase):
    def test_the_card_table_is_a_station_the_model_can_choose(self) -> None:
        # F7: room.ts declares the card table; without it here the model could
        # never be sent there.
        self.assertIn("table", choreography.STATIONS)
        result = choreography.submit_plan(
            {"cues": [{"anchor": "now", "station": "table"}]}, turn_id="turn_table"
        )
        self.assertTrue(result["ok"], result)
        item = choreography.BODY_CHOREOGRAPHY_TOOL["function"]["parameters"]["properties"][
            "cues"
        ]["items"]
        self.assertIn("table", item["properties"]["station"]["enum"])


if __name__ == "__main__":
    unittest.main()

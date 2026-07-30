"""
Regression tests for the face-brain stability sweep.

Covers: the bounded tool loop closing in prose instead of trailing off into
"one sec" narration, a barge-in keeping a record of the tools that already ran
(with the interruption note riding as a user parenthetical, never system), the
interruption note surviving a provider error that lands together with the
barge, the deferred diary write happening exactly once, table talk being
journaled when playback drains rather than when generation ends, a leading
mood tag never reaching the listener, per-turn skill prompts accumulating
instead of replacing each other, the compaction flag surviving a thread that
cannot start, newest-turn-wins foreground preemption, stale tool-result
quarantine, the card table being a place the model can send Rau, and the
retired entry points staying gone.

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

    def test_the_tool_loop_closes_when_the_provider_returns_prose(self) -> None:
        provider = ScriptedProvider(
            [tool_round(f"call_{i}", "list_skills", "One sec— ") for i in range(5)]
            + [{"deltas": ["Done — the list is above."], "content": "Done — the list is above."}]
        )
        self.install(provider)

        reply = brain.chat_streaming("what can you do", on_token=lambda _t: None)

        self.assertEqual(len(provider.calls), 6)
        self.assertIsNotNone(provider.calls[0]["tools"])
        self.assertIn("Done — the list is above.", str(reply))

    def test_a_foreground_turn_can_run_twenty_tools_then_must_close(self) -> None:
        provider = ScriptedProvider(
            [
                tool_round(f"call_{index}", "list_skills", "")
                for index in range(brain.MAX_FACE_TOOL_CALLS)
            ]
            + [{"deltas": ["All twenty checks are done."], "content": "All twenty checks are done."}]
        )
        self.install(provider)
        ran: List[str] = []

        reply = brain.chat_streaming(
            "check everything",
            on_token=lambda _t: None,
            on_tool=lambda name, _args, _result: ran.append(name),
        )

        self.assertEqual(len(ran), brain.MAX_FACE_TOOL_CALLS)
        self.assertEqual(
            len(provider.calls),
            brain.MAX_FACE_TOOL_CALLS + 1,
        )
        self.assertIsNone(provider.calls[-1]["tools"])
        self.assertEqual(str(reply), "All twenty checks are done.")
        history_reply = [
            message.content
            for message in brain.snapshot_history()
            if message.role == "assistant"
        ][-1]
        self.assertIn("Internal continuity note, not spoken", history_reply)
        self.assertIn("20 tool calls completed", history_reply)
        self.assertNotIn("Internal continuity note", str(reply))

    def test_a_provider_batch_cannot_execute_past_the_twenty_call_budget(self) -> None:
        requested = [
            ToolCall(id=f"batch_{index}", name="list_skills", arguments={})
            for index in range(brain.MAX_FACE_TOOL_CALLS + 3)
        ]
        second_messages: List[Message] = []

        class BatchProvider:
            def __init__(self) -> None:
                self.calls = 0

            def stream_turn(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    yield StreamDone(ChatResult(content="", tool_calls=requested))
                    return
                second_messages.extend(messages)
                yield TextDelta("Budgeted work complete.")
                yield StreamDone(ChatResult(content="Budgeted work complete."))

        provider = BatchProvider()
        self.install(provider)
        executed: List[str] = []
        spoken: List[str] = []
        with mock.patch.object(
            brain,
            "_run_face_tool",
            side_effect=lambda name, _args: executed.append(name)
            or {"ok": True, "summary": "done"},
        ):
            reply = brain.chat_streaming(
                "run a large batch",
                on_token=spoken.append,
                voice=True,
            )

        self.assertEqual(len(executed), brain.MAX_FACE_TOOL_CALLS)
        # Every requested call is paired for provider protocol validity; the
        # three over budget explicitly say they were not executed.
        tool_results = [m for m in second_messages if m.role == "tool"]
        self.assertEqual(len(tool_results), brain.MAX_FACE_TOOL_CALLS + 3)
        self.assertEqual(
            sum("not executed" in m.content for m in tool_results),
            3,
        )
        progress = "".join(spoken)
        self.assertNotIn("I’ve completed", progress)
        self.assertNotIn("I’m starting", progress)
        self.assertTrue(str(reply).endswith("Budgeted work complete."))

    def test_voice_stays_silent_while_tools_run_without_provider_prose(self) -> None:
        provider = ScriptedProvider(
            [tool_round(f"call_{index}", "list_skills", "") for index in range(5)]
            + [{"deltas": ["I’m done."], "content": "I’m done."}]
        )
        self.install(provider)
        tokens: List[str] = []

        reply = brain.chat_streaming(
            "check the available abilities",
            on_token=tokens.append,
            voice=True,
        )

        spoken = "".join(tokens)
        self.assertEqual(spoken, "I’m done.")
        self.assertNotIn("I’m starting", spoken)
        self.assertNotIn("I’ve completed", spoken)
        self.assertEqual(str(reply).split()[-2:], ["I’m", "done."])

    def test_body_choreography_never_becomes_a_spoken_checkin(self) -> None:
        provider = ScriptedProvider(
            [
                tool_round("move_1", "body_choreography", ""),
                {"deltas": ["Here I am."], "content": "Here I am."},
            ]
        )
        self.install(provider)
        tokens: List[str] = []

        reply = brain.chat_streaming(
            "wave hello",
            on_token=tokens.append,
            voice=True,
        )

        self.assertEqual("".join(tokens), "Here I am.")
        self.assertEqual(str(reply), "Here I am.")
        self.assertNotIn("planning movement", str(reply).lower())

    def test_observable_summary_exists_without_provider_reasoning(self) -> None:
        provider = ScriptedProvider(
            [{"deltas": ["Direct answer."], "content": "Direct answer."}]
        )
        self.install(provider)
        activity = mock.Mock()
        activity.start.side_effect = [
            {"id": "response"},
            {"id": "approach"},
        ]

        with mock.patch.object(brain, "ACTIVITY", activity):
            reply = brain.chat_streaming("simple question", on_token=lambda _t: None)

        self.assertEqual(str(reply), "Direct answer.")
        approach_call = next(
            call
            for call in activity.start.call_args_list
            if len(call.args) > 1 and call.args[1] == "Approach summary"
        )
        self.assertFalse(
            approach_call.kwargs["details"]["provider_reasoning_available"]
        )
        finishes = [call.kwargs for call in activity.finish.call_args_list]
        summary = next(
            item["summary"]
            for item in finishes
            if "observable actions" in item.get("summary", "")
        )
        self.assertIn("no tool calls were needed", summary.lower())

    def test_an_empty_stream_gets_a_tool_free_visible_retry(self) -> None:
        provider = ScriptedProvider(
            [
                {"content": ""},
                {
                    "deltas": ["A specific recovered answer."],
                    "content": "A specific recovered answer.",
                },
            ]
        )
        self.install(provider)
        spoken: List[str] = []

        reply = brain.chat_streaming("tell me something", on_token=spoken.append)

        self.assertEqual(str(reply), "A specific recovered answer.")
        self.assertEqual("".join(spoken), "A specific recovered answer.")
        self.assertEqual(len(provider.calls), 2)
        self.assertIsNone(provider.calls[-1]["tools"])
        self.assertEqual(provider.calls[-1]["effort"], "minimal")

    def test_last_resort_empty_replies_rotate_and_match_the_language(self) -> None:
        first = brain._local_empty_reply("hello")
        second = brain._local_empty_reply("hello")
        korean = brain._local_empty_reply("안녕하세요")

        self.assertNotEqual(first, second)
        self.assertNotIn("with you", first.lower())
        self.assertRegex(korean, r"[가-힣]")

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

    def test_a_new_user_turn_preempts_a_blocked_stream_immediately(self) -> None:
        old_started = threading.Event()
        release_old = threading.Event()

        class BlockingProvider:
            def stream_turn(self, messages, **kwargs):
                prompt = [m.content for m in messages if m.role == "user"][-1]
                if prompt == "old":
                    yield TextDelta("old partial")
                    old_started.set()
                    release_old.wait(timeout=5)
                    yield StreamDone(ChatResult(content="old partial stale"))
                    return
                yield TextDelta("new answer")
                yield StreamDone(ChatResult(content="new answer"))

        self.install(BlockingProvider())
        old_error: List[Exception] = []
        old_playback_cancel = threading.Event()

        def run_old() -> None:
            try:
                brain.chat_streaming(
                    "old",
                    on_token=lambda _t: None,
                    cancel=old_playback_cancel,
                )
            except Exception as exc:
                old_error.append(exc)

        thread = threading.Thread(target=run_old)
        thread.start()
        self.assertTrue(old_started.wait(timeout=2))

        started = time.monotonic()
        reply = brain.chat_streaming("new", on_token=lambda _t: None)
        elapsed = time.monotonic() - started
        self.assertEqual(str(reply), "new answer")
        self.assertLess(elapsed, 1.0, "new turn waited on the stale provider")
        self.assertTrue(
            old_playback_cancel.is_set(),
            "cross-surface preemption must stop stale voice playback too",
        )

        release_old.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(old_error), 1)
        self.assertIsInstance(old_error[0], brain.Cancelled)
        brain.finish_interrupted_turn(old_error[0], "old partial")
        history = [(m.role, m.content) for m in brain.snapshot_history()]
        self.assertIn(("assistant", "new answer"), history)
        self.assertNotIn(("assistant", "old partial stale"), history)

    def test_an_inflight_tool_settles_but_its_stale_callback_is_hidden(self) -> None:
        tool_started = threading.Event()
        release_tool = threading.Event()
        callbacks: List[str] = []

        class ToolProvider:
            def stream_turn(self, messages, **kwargs):
                prompt = [m.content for m in messages if m.role == "user"][-1]
                if prompt == "old":
                    yield StreamDone(
                        ChatResult(
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="call_old",
                                    name="start_hard_task",
                                    arguments={"goal": "keep running"},
                                )
                            ],
                        )
                    )
                    return
                yield TextDelta("priority answer")
                yield StreamDone(ChatResult(content="priority answer"))

        def slow_tool(_name, _args):
            tool_started.set()
            release_tool.wait(timeout=5)
            return {"ok": True, "summary": "subagent launched"}

        self.install(ToolProvider())
        old_error: List[Exception] = []

        def run_old() -> None:
            try:
                brain.chat_streaming(
                    "old",
                    on_token=lambda _t: None,
                    on_tool=lambda name, _args, _result: callbacks.append(name),
                )
            except Exception as exc:
                old_error.append(exc)

        with mock.patch.object(brain, "_run_face_tool", side_effect=slow_tool):
            thread = threading.Thread(target=run_old)
            thread.start()
            self.assertTrue(tool_started.wait(timeout=2))
            reply = brain.chat_streaming("new", on_token=lambda _t: None)
            self.assertEqual(str(reply), "priority answer")
            self.assertTrue(thread.is_alive(), "the active tool should settle safely")
            release_tool.set()
            thread.join(timeout=5)

        self.assertEqual(callbacks, [])
        self.assertEqual(len(old_error), 1)
        self.assertIsInstance(old_error[0], brain.Cancelled)
        self.assertIn(
            ("start_hard_task", "subagent launched"),
            old_error[0].tools_ran,
        )

    def test_a_system_turn_waits_out_the_turn_in_flight(self) -> None:
        # weave_result speaks for a finished deep-work job: there is no user
        # to re-ask, so it waits for foreground conversation to become idle.
        provider = ScriptedProvider(
            [{"deltas": ["it is done"], "content": "it is done"}]
        )
        self.install(provider)
        active = brain._begin_foreground_turn(user_priority=True)
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
            brain._end_foreground_turn(active)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(out, ["it is done"])
        self.assertEqual(self.diary[-1], ("rau", "it is done"))

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

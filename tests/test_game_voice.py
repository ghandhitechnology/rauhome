"""
The regression that made Rau mute at a table.

Run: python -m unittest tests.test_game_voice -v

Every model call the two games make is small: eight tokens for a Nope, forty
eight for a chess line, sixty for a proactive one, four hundred for a whole
turn. None of them called `provider.chat` with an `effort`, and the trap is
that omitting it does not mean "no reasoning" — `apply_reasoning_payload` reads
`None` as *use the catalog default*, and the DeepSeek default is "high". So
every one of those budgets went to a thinking block, `content` came back empty
or truncated, and:

* kittens turns failed to parse, fell through to the fallback move, and said
  nothing
* kittens Nope decisions always timed out into the reflex
* proactive banter, in both games, never once managed to speak

Chess had a second, independent version of the same silence: it read
`getattr(result, "text", "")`, and `ChatResult` has no `text` attribute, so its
lines were empty even when the request was well formed.

These tests pin the request shape rather than the model's answer, because that
is where the bug lived. A passing suite here says he is capable of speaking; it
says nothing about whether what he says is any good.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import banter as kittens_banter  # noqa: E402
from rau.games.kittens import player as kittens_player  # noqa: E402
from rau.games.kittens import session, tools  # noqa: E402
from rau.games.kittens import vibe as kittens_vibe  # noqa: E402
from rau.games.kittens.deck import ATTACK, SKIP  # noqa: E402
from rau.games.kittens.engine import PHASE_PLAYING, RAU, USER, Game  # noqa: E402
from rau.providers.base import ChatResult  # noqa: E402
from rau.providers.reasoning import build_reasoning_fields  # noqa: E402
from tests.test_kittens_session import isolate_memory, quiesce  # noqa: E402


class RecordingProvider:
    """Captures the kwargs of every chat call and answers with fixed text."""

    def __init__(self, reply: str = "sure.") -> None:
        self.reply = reply
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(dict(kwargs))
        return ChatResult(content=self.reply)


def _slot() -> Dict[str, Any]:
    return {"model": "deepseek-v4-pro", "max_tokens": 60, "temperature": 0.5}


class ThinkingIsDisabledOnGameCalls(unittest.TestCase):
    """Every game call must ask for `minimal`, or it gets an empty answer."""

    def _effort_of(self, call) -> Any:
        provider = RecordingProvider('{"move": {"move": "draw"}, "say": "hi."}')
        with patch(
            "rau.providers.registry.chat_for_slot",
            return_value=(provider, _slot()),
        ):
            call()
        self.assertTrue(provider.calls, "the provider was never called")
        return provider.calls[0].get("effort")

    def test_kittens_turn(self):
        self.assertEqual(
            self._effort_of(lambda: kittens_player._ask_model("prompt")), "minimal"
        )

    def test_kittens_banter(self):
        self.assertEqual(
            self._effort_of(lambda: kittens_banter._ask("prompt")), "minimal"
        )

    def test_kittens_vibe(self):
        self.assertEqual(
            self._effort_of(lambda: kittens_vibe._ask("history")), "minimal"
        )

    def test_chess_move_line(self):
        from rau.games.chess import player as chess_player

        self.assertEqual(self._effort_of(lambda: chess_player._ask("prompt")), "minimal")

    def test_chess_banter(self):
        from rau.games.chess import banter as chess_banter

        self.assertEqual(self._effort_of(lambda: chess_banter._ask("prompt")), "minimal")

    def test_kittens_nope(self):
        game = Game(seed=1)
        game.hands[RAU] = ["nope", SKIP]
        game.hands[USER] = [ATTACK]
        game.current = USER
        game.phase = PHASE_PLAYING
        game.play(USER, ATTACK)
        self.assertEqual(
            self._effort_of(lambda: kittens_player.decide_nope(game)), "minimal"
        )


class ChessReadsTheRightField(unittest.TestCase):
    """`ChatResult` carries `content`; the old code read a `text` that never existed."""

    def _reply(self, call) -> str:
        provider = RecordingProvider("i saw that coming.")
        with patch(
            "rau.providers.registry.chat_for_slot",
            return_value=(provider, _slot()),
        ):
            return call()

    def test_chess_move_line_is_not_dropped(self):
        from rau.games.chess import player as chess_player

        self.assertEqual(self._reply(lambda: chess_player._ask("p")), "i saw that coming.")

    def test_chess_banter_line_is_not_dropped(self):
        from rau.games.chess import banter as chess_banter

        self.assertEqual(self._reply(lambda: chess_banter._ask("p")), "i saw that coming.")


class ReasoningPayloadShape(unittest.TestCase):
    """The provider-level fact the game modules depend on."""

    def test_minimal_disables_deepseek_thinking(self):
        fields = build_reasoning_fields("deepseek", "deepseek-v4-pro", "minimal")
        self.assertEqual(fields.get("thinking"), {"type": "disabled"})

    def test_absent_effort_is_not_neutral(self):
        """The trap, pinned: no effort means the catalog default, which thinks."""
        fields = build_reasoning_fields("deepseek", "deepseek-v4-pro", None)
        self.assertEqual(fields.get("thinking"), {"type": "enabled"})


class CannedLines(unittest.TestCase):
    def test_every_move_kind_has_a_line(self):
        for kind in (
            "draw",
            "play",
            "combo",
            "nope",
            "pass_nope",
            "give_favor",
            "take_from_discard",
            "insert_kitten",
            "concede",
        ):
            self.assertTrue(kittens_player.table_line(kind), kind)

    def test_unknown_kind_still_speaks(self):
        self.assertTrue(kittens_player.table_line("something-new"))

    def test_korean_locale_has_every_line(self):
        with patch("rau.language.get_locale", return_value="ko"):
            for kind in kittens_player.TABLE_LINES:
                self.assertTrue(kittens_player.table_line(kind), kind)


class HeAlwaysSaysSomething(unittest.TestCase):
    """A move with no line is the bug in a smaller window."""

    def setUp(self) -> None:
        isolate_memory(self)
        self._real_take = kittens_player.take_turn
        self._real_nope = kittens_player.decide_nope
        kittens_player.take_turn = lambda game: None
        kittens_player.decide_nope = lambda game: False

        self.said: List[str] = []
        patcher = patch.object(kittens_player, "table_talk", self.said.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        quiesce()
        kittens_player.take_turn = self._real_take
        kittens_player.decide_nope = self._real_nope

    def _live_hand(self) -> Game:
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [SKIP]
        game.draw = [ATTACK, SKIP, SKIP]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        return game

    def test_move_without_a_say_still_speaks(self):
        game = self._live_hand()
        with patch.object(
            kittens_player,
            "_ask_model",
            return_value='{"move": {"move": "draw"}, "say": ""}',
        ):
            self._real_take(game)
        self.assertTrue(self.said, "he moved in silence")

    def test_dead_provider_still_speaks(self):
        game = self._live_hand()

        def boom(prompt: str) -> str:
            raise RuntimeError("provider down")

        with patch.object(kittens_player, "_ask_model", boom):
            self._real_take(game)
        self.assertTrue(self.said, "the fallback move went out mute")


class BanterWaitsForHisMoveLine(unittest.TestCase):
    """He speaks on every move now, so the seat check alone no longer guards."""

    def tearDown(self) -> None:
        kittens_player.reset_speech()

    def test_a_fresh_hand_does_not_hold_banter_back(self):
        kittens_player.reset_speech()
        self.assertEqual(kittens_player.last_spoke(), 0.0)

    def test_speaking_stamps_the_clock(self):
        kittens_player.reset_speech()
        with patch("rau.face.choreography.new_turn_id", return_value="t1"), patch(
            "rau.state.add_log"
        ), patch("rau.state.push_control"), patch("rau.events.BUS.emit"):
            kittens_player.table_talk("your funeral.")
        gap = time.monotonic() - kittens_player.last_spoke()
        self.assertLess(gap, kittens_banter.MIN_GAP_SEC)

    def test_an_empty_line_does_not_stamp_the_clock(self):
        kittens_player.reset_speech()
        kittens_player.table_talk("   ")
        self.assertEqual(kittens_player.last_spoke(), 0.0)


class TableTalkBrowserRouting(unittest.TestCase):
    """
    A browser voice session has no out-of-turn TTS hook for table talk.

    The desktop speak queue always gets the line; while a browser voice socket
    is attached, the gap is logged — once per hand, not once per line.
    """

    def setUp(self) -> None:
        kittens_player.reset_speech()

    def tearDown(self) -> None:
        from rau.games.kittens import journal

        kittens_player.reset_speech()
        journal.clear()

    def _talk(self):
        with patch("rau.face.choreography.new_turn_id", return_value="t1"), patch(
            "rau.state.add_log"
        ), patch("rau.events.BUS.emit"):
            kittens_player.table_talk("your funeral.")

    def test_desktop_speak_always_gets_the_line(self):
        with patch("rau.state._browser_voice_sessions", 0), patch(
            "rau.state.push_control"
        ) as push:
            with self.assertNoLogs("rau.games.kittens.player", level="INFO"):
                self._talk()
        push.assert_called_once_with({"action": "speak", "text": "your funeral."})

    def test_an_active_browser_session_is_noted_once_per_hand(self):
        with patch("rau.state._browser_voice_sessions", 1), patch(
            "rau.state.push_control"
        ) as push:
            with self.assertLogs("rau.games.kittens.player", level="INFO") as logs:
                self._talk()
                self._talk()
        # The desktop queue is not displaced — it is the only path there is.
        self.assertEqual(push.call_count, 2)
        self.assertEqual(len(logs.records), 1, "one note per hand, not one per line")
        self.assertIn("no out-of-turn TTS hook", logs.records[0].getMessage())

    def test_a_fresh_hand_notes_the_gap_again(self):
        with patch("rau.state._browser_voice_sessions", 1), patch(
            "rau.state.push_control"
        ):
            with self.assertLogs("rau.games.kittens.player", level="INFO"):
                self._talk()
            kittens_player.reset_speech()  # what a new deal does
            with self.assertLogs("rau.games.kittens.player", level="INFO"):
                self._talk()


class VibeDefaultsToPlayful(unittest.TestCase):
    """A broken memory read must not quietly turn him polite forever."""

    def tearDown(self) -> None:
        kittens_vibe.reset()

    def test_unprimed_read_is_the_default(self):
        kittens_vibe.reset()
        self.assertEqual(kittens_vibe.read(), kittens_vibe.DEFAULT_VIBE)

    def test_read_is_never_empty(self):
        kittens_vibe.reset()
        self.assertTrue(kittens_vibe.read().strip())

    def test_a_failing_memory_read_leaves_the_default(self):
        kittens_vibe.reset()
        with patch(
            "rau.memory.store.recent_context", side_effect=RuntimeError("no disk")
        ):
            kittens_vibe.prime()
            deadline = time.time() + 5
            while kittens_vibe.busy().is_set() and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(kittens_vibe.read(), kittens_vibe.DEFAULT_VIBE)

    def test_an_empty_diary_costs_nothing(self):
        """No history means no question worth asking — and no request at all."""
        kittens_vibe.reset()
        provider = RecordingProvider("should never be reached")
        with patch("rau.memory.store.recent_context", return_value="  "), patch(
            "rau.providers.registry.chat_for_slot", return_value=(provider, _slot())
        ):
            kittens_vibe.prime()
            deadline = time.time() + 5
            while kittens_vibe.busy().is_set() and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(provider.calls, [])
        self.assertEqual(kittens_vibe.read(), kittens_vibe.DEFAULT_VIBE)

    def test_a_stale_read_cannot_land_on_a_new_hand(self):
        """A slow read from the last hand must not overwrite this one."""
        kittens_vibe.reset()
        released = __import__("threading").Event()

        def slow(history: str) -> str:
            released.wait(5)
            return "STALE"

        with patch("rau.memory.store.recent_context", return_value="history"), patch.object(
            kittens_vibe, "_ask", slow
        ):
            kittens_vibe.prime()
            # A new hand is dealt while that read is still in flight.
            kittens_vibe.reset()
            released.set()
            time.sleep(0.2)
        self.assertEqual(kittens_vibe.read(), kittens_vibe.DEFAULT_VIBE)

    def test_a_good_read_replaces_the_default(self):
        kittens_vibe.reset()
        provider = RecordingProvider("They have been ribbing you all week.")
        with patch(
            "rau.memory.store.recent_context", return_value="user: you're terrible"
        ), patch(
            "rau.providers.registry.chat_for_slot", return_value=(provider, _slot())
        ):
            kittens_vibe.prime()
            deadline = time.time() + 5
            while kittens_vibe.busy().is_set() and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(kittens_vibe.read(), "They have been ribbing you all week.")


class VibeReachesThePrompts(unittest.TestCase):
    """The read is only worth making if both halves actually see it."""

    def setUp(self) -> None:
        isolate_memory(self)

    def tearDown(self) -> None:
        quiesce()

    def test_turn_prompt_carries_the_vibe(self):
        game = Game(seed=2)
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [SKIP]
        game.current = RAU
        game.phase = PHASE_PLAYING
        with patch.object(kittens_vibe, "read", return_value="VIBE-MARKER"):
            prompt = kittens_player._turn_prompt(game)
        self.assertIn("VIBE-MARKER", prompt)

    def test_banter_prompt_carries_the_vibe(self):
        game = Game(seed=3)
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [SKIP]
        game.current = USER
        game.phase = PHASE_PLAYING
        with patch.object(kittens_vibe, "read", return_value="VIBE-MARKER"):
            prompt = kittens_banter._prompt(game, "moved")
        self.assertIn("VIBE-MARKER", prompt)

    def test_banter_prompt_carries_the_transcript(self):
        from rau.games.kittens import journal

        game = Game(seed=4)
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [SKIP]
        game.current = USER
        game.phase = PHASE_PLAYING
        journal.clear()
        journal.record("rau", "table_talk", "JOURNAL-MARKER")
        try:
            prompt = kittens_banter._prompt(game, "moved")
        finally:
            journal.clear()
        self.assertIn("JOURNAL-MARKER", prompt)


if __name__ == "__main__":
    unittest.main()

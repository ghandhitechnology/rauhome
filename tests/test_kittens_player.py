"""
Rau's player half — parse, retry, fallback, and shared journal.

Run: python -m unittest tests.test_kittens_player -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import journal, player, session, tools  # noqa: E402
from rau.games.kittens import view as view_mod  # noqa: E402
from rau.games.kittens.deck import ATTACK, SKIP  # noqa: E402
from rau.games.kittens.engine import PHASE_PLAYING, RAU, USER, Game  # noqa: E402
from tests.test_kittens_session import isolate_memory, quiesce  # noqa: E402


class ParseTurnReply(unittest.TestCase):
    def test_clean_json(self):
        move, say = player.parse_turn_reply(
            '{"move": {"move": "draw"}, "say": "drawing."}'
        )
        self.assertEqual(move, {"move": "draw"})
        self.assertEqual(say, "drawing.")

    def test_fenced_json(self):
        move, say = player.parse_turn_reply(
            'Sure.\n```json\n{"move": {"move": "play", "card": "skip"}, "say": "skip."}\n```\n'
        )
        self.assertEqual(move, {"move": "play", "card": "skip"})
        self.assertEqual(say, "skip.")

    def test_prose_around_json(self):
        move, say = player.parse_turn_reply(
            'Alright then {"move": {"move": "draw"}, "say": "ok"} done.'
        )
        self.assertEqual(move, {"move": "draw"})
        self.assertEqual(say, "ok")

    def test_garbage_returns_none(self):
        move, say = player.parse_turn_reply("I refuse to play")
        self.assertIsNone(move)
        self.assertEqual(say, "")


class TakeTurn(unittest.TestCase):
    def setUp(self) -> None:
        isolate_memory(self)
        import rau.games.kittens.engine as engine_mod
        import rau.games.kittens.player as player_mod

        self._engine = engine_mod
        self._window_ms = engine_mod.NOPE_WINDOW_MS
        engine_mod.NOPE_WINDOW_MS = 1
        self._player = player_mod
        self._real_take = player_mod.take_turn
        self._real_ask = player_mod._ask_model
        self._real_nope = player_mod.decide_nope
        player_mod.decide_nope = lambda game: False
        # Disable the pump's player hook so only the direct call under test runs.
        player_mod.take_turn = lambda game: None

    def tearDown(self) -> None:
        quiesce()
        self._engine.NOPE_WINDOW_MS = self._window_ms
        self._player.take_turn = self._real_take
        self._player._ask_model = self._real_ask
        self._player.decide_nope = self._real_nope

    def test_illegal_then_valid_retries_once(self):
        calls: List[str] = []

        def ask(prompt: str) -> str:
            calls.append(prompt)
            if len(calls) == 1:
                return '{"move": {"move": "play", "card": "defuse"}, "say": "nope"}'
            return '{"move": {"move": "draw"}, "say": "fine, drawing."}'

        self._player._ask_model = ask
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
        self._real_take(game)
        self.assertEqual(len(calls), 2)
        self.assertIn("Illegal", calls[1])
        self.assertEqual(game.current, USER)

    def test_fallback_plays_last_legal_move(self):
        self._player._ask_model = lambda prompt: "????"
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [SKIP]
        game.draw = [ATTACK, SKIP]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        before = game.current
        self._real_take(game)
        self.assertNotEqual(game.current, before)

    def test_say_is_recorded_in_the_journal(self):
        self._player._ask_model = lambda prompt: (
            '{"move": {"move": "draw"}, "say": "watching you."}'
        )
        with patch.object(player, "table_talk", wraps=player.table_talk) as talk:
            tools.run_tool("start_kittens", {})
            game = session.current()
            assert game is not None
            game.hands[RAU] = [SKIP]
            game.draw = [ATTACK, SKIP]
            game.current = RAU
            game.phase = PHASE_PLAYING
            game.pending = None
            game.awaiting_seat = None
            self._real_take(game)
            talk.assert_called()
        text = journal.tail()
        self.assertIn("watching you", text)
        self.assertIn("drew", text.lower())


class JournalShared(unittest.TestCase):
    def setUp(self) -> None:
        isolate_memory(self)
        journal.clear()

    def tearDown(self) -> None:
        quiesce()
        journal.clear()

    def test_cleared_on_deal(self):
        journal.record("user", "user_chat", "hello")
        tools.run_tool("start_kittens", {})
        # Deal records its own event; prior chat must be gone.
        text = journal.tail()
        self.assertNotIn("hello", text)
        self.assertIn("Dealt", text)

    def test_user_chat_lands_in_player_prompt_via_journal(self):
        tools.run_tool("start_kittens", {})
        journal.record("user", "user_chat", "don't draw the kitten")
        game = session.current()
        assert game is not None
        prompt = player._turn_prompt(game)
        self.assertIn("don't draw the kitten", prompt)

    def test_player_say_lands_in_talker_fragment(self):
        tools.run_tool("start_kittens", {})
        journal.record("rau", "table_talk", "your move, friend")
        game = session.current()
        assert game is not None
        text = view_mod.talker_fragment(game, RAU)
        self.assertIn("your move, friend", text)


class NopeReflex(unittest.TestCase):
    def test_timeout_falls_back_to_reflex_on_attack(self):
        game = Game(seed=1)
        game.hands[RAU] = ["nope", SKIP]
        game.hands[USER] = [ATTACK]
        game.current = USER
        game.phase = PHASE_PLAYING
        game.play(USER, ATTACK)
        # Freeze the model so the deadline expires.
        with patch.object(player, "_nope_prompt", return_value="x"):
            with patch("rau.games.kittens.player.DECIDE_TIMEOUT_SEC", 0.05):
                with patch(
                    "rau.providers.registry.chat_for_slot",
                    side_effect=RuntimeError("slow"),
                ):
                    # Even with a broken provider, Attack is worth Noping.
                    # decide_nope catches provider errors inside the worker.
                    decided = player.decide_nope(game)
        # Worker fails → empty answer → reflex on Attack → True
        self.assertTrue(decided)


if __name__ == "__main__":
    unittest.main()

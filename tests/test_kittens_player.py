"""
Rau's player half — parse, retry, fallback, and shared journal.

Run: python -m unittest tests.test_kittens_player -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import deck as deck_mod  # noqa: E402
from rau.games.kittens import journal, player, session, tools  # noqa: E402
from rau.games.kittens import view as view_mod  # noqa: E402
from rau.games.kittens.deck import ATTACK, DEFUSE, EXPLODING_KITTEN, SKIP  # noqa: E402
from rau.games.kittens.engine import PHASE_DEFUSE, PHASE_PLAYING, RAU, USER, Game  # noqa: E402
from rau.providers.base import ChatResult  # noqa: E402
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

    def test_fallback_plays_attack_instead_of_blindly_drawing(self):
        self._player._ask_model = lambda prompt: "not json"
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [ATTACK]
        game.hands[USER] = [SKIP]
        game.draw = [SKIP, SKIP]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None

        self._real_take(game)

        self.assertNotIn(ATTACK, game.hands[RAU])
        self.assertIn(ATTACK, game.discard)
        self.assertNotIn(SKIP, game.hands[RAU], "blind draw fallback still ran")

    def test_fallback_does_not_stall_waiting_for_a_human_favor_choice(self):
        self._player._ask_model = lambda prompt: "not json"
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [deck_mod.FAVOR]
        game.hands[USER] = [SKIP]
        game.draw = [SKIP, ATTACK]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None

        self._real_take(game)

        self.assertIn(deck_mod.FAVOR, game.hands[RAU])
        self.assertIn(SKIP, game.hands[RAU])
        self.assertEqual(game.current, USER)

    def test_passive_model_draw_can_be_replaced_by_favor(self):
        self._player._ask_model = lambda prompt: (
            '{"move": {"move": "draw"}, "say": "I guess I draw."}'
        )
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [deck_mod.FAVOR]
        game.hands[USER] = [SKIP]
        game.draw = [SKIP, ATTACK]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None

        self._real_take(game)

        self.assertIn(deck_mod.FAVOR, game.discard)
        self.assertEqual(game.awaiting_seat, USER)

    def test_passive_model_draw_is_replaced_by_first_proactive_move(self):
        self._player._ask_model = lambda prompt: (
            '{"move": {"move": "draw"}, "say": "I guess I draw."}'
        )
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [ATTACK]
        game.hands[USER] = [SKIP]
        game.draw = [SKIP, SKIP]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None

        self._real_take(game)

        self.assertIn(ATTACK, game.discard)
        self.assertNotIn(SKIP, game.hands[RAU])

    def test_after_an_action_the_model_may_draw(self):
        self._player._ask_model = lambda prompt: (
            '{"move": {"move": "draw"}, "say": "now I draw."}'
        )
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [ATTACK]
        game.hands[USER] = [SKIP]
        game.draw = [SKIP, ATTACK]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        game.actions_this_turn = 1

        self._real_take(game)

        self.assertIn(SKIP, game.hands[RAU])
        self.assertIn(ATTACK, game.hands[RAU], "a second proactive move was forced")

    def test_known_kitten_overrides_draw_even_after_an_earlier_action(self):
        self._player._ask_model = lambda prompt: (
            '{"move": {"move": "draw"}, "say": "now I draw."}'
        )
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[RAU] = [SKIP]
        game.hands[USER] = [ATTACK]
        game.draw = [EXPLODING_KITTEN, ATTACK]
        game.current = RAU
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        game.actions_this_turn = 1
        game.known_top[RAU] = [EXPLODING_KITTEN, ATTACK]

        self._real_take(game)

        self.assertIn(SKIP, game.discard)
        self.assertEqual(game.draw[0], EXPLODING_KITTEN)
        self.assertEqual(game.current, USER)

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

    def test_provider_content_is_used_instead_of_draw_fallback(self):
        """A real ChatResult must reach the parser rather than look empty."""

        class Provider:
            def chat(self, *args, **kwargs):
                return ChatResult(
                    content=(
                        '{"move": {"move": "play", "card": "skip"}, '
                        '"say": "skipping this one."}'
                    )
                )

        with patch(
            "rau.providers.registry.chat_for_slot",
            return_value=(
                Provider(),
                {
                    "model": "test-player",
                    "max_tokens": 100,
                    "temperature": 0,
                },
            ),
        ):
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
            self._real_take(game)

        self.assertNotIn(SKIP, game.hands[RAU])
        self.assertIn(SKIP, game.discard)
        self.assertNotIn(ATTACK, game.hands[RAU], "the draw fallback ran")


class FallbackMove(unittest.TestCase):
    """The guaranteed move must actually be guaranteed — placeholders are not playable."""

    def test_the_insert_placeholder_becomes_a_real_index(self):
        game = Game(seed=1)
        game.hands[RAU] = [DEFUSE]
        game.hands[USER] = [SKIP]
        game.draw = [EXPLODING_KITTEN, ATTACK]
        game.current = RAU
        game.draw_card(RAU)
        assert game.phase == PHASE_DEFUSE
        move = player._fallback_move(game)
        self.assertEqual(move["move"], "insert_kitten")
        self.assertIsInstance(move["index"], int, "int('0..N') is how the table wedged")
        game.insert_kitten(RAU, move["index"])  # must not raise
        self.assertEqual(game.phase, PHASE_PLAYING)

    def test_the_named_card_placeholder_becomes_a_real_card(self):
        game = Game(seed=1)
        with patch.object(
            game,
            "legal_moves",
            return_value=[
                {
                    "move": "combo",
                    "cards": ["tacocat"] * 3,
                    "named_card": "<any card you want from their hand>",
                }
            ],
        ):
            move = player._fallback_move(game)
        self.assertIn(move["named_card"], deck_mod.ALL_CARDS)


class ListedMoves(unittest.TestCase):
    """A move the prompt lists must play exactly as copied."""

    def _listed(self, game: Game) -> List[Dict[str, Any]]:
        text = view_mod.prompt_fragment(game, RAU)
        return [
            json.loads(line[2:])
            for line in text.splitlines()
            if line.startswith("- {")
        ]

    def test_the_defuse_listing_plays_as_printed(self):
        game = Game(seed=1)
        game.hands[RAU] = [DEFUSE]
        game.hands[USER] = [SKIP]
        game.draw = [EXPLODING_KITTEN, ATTACK]
        game.current = RAU
        game.draw_card(RAU)
        assert game.phase == PHASE_DEFUSE
        moves = self._listed(game)
        self.assertEqual([m["move"] for m in moves], ["insert_kitten"])
        self.assertIsInstance(moves[0]["index"], int, "a listed move must copy verbatim")
        game.insert_kitten(RAU, moves[0]["index"])  # must not raise
        self.assertEqual(game.phase, PHASE_PLAYING)

    def test_a_three_of_a_kind_listing_names_a_real_card(self):
        game = Game(seed=1)
        game.hands[RAU] = ["tacocat", "tacocat", "tacocat", SKIP]
        game.hands[USER] = [SKIP, ATTACK]
        game.current = RAU
        moves = [
            m
            for m in self._listed(game)
            if m["move"] == "combo" and len(m["cards"]) == 3
        ]
        self.assertTrue(moves, "the set is held, so it must be listed")
        for move in moves:
            self.assertIn(move["named_card"], deck_mod.ALL_CARDS)
        game.combo(RAU, moves[0]["cards"], named_card=moves[0]["named_card"])


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
    def test_provider_content_can_pass_on_an_attack(self):
        """PASS in ChatResult.content must override the aggressive reflex."""

        class Provider:
            def chat(self, *args, **kwargs):
                return ChatResult(content="PASS")

        game = Game(seed=1)
        game.hands[RAU] = ["nope", SKIP]
        game.hands[USER] = [ATTACK]
        game.current = USER
        game.phase = PHASE_PLAYING
        game.play(USER, ATTACK)
        with patch(
            "rau.providers.registry.chat_for_slot",
            return_value=(Provider(), {"model": "test-player"}),
        ):
            self.assertFalse(player.decide_nope(game))

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

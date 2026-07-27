"""
Nobody sees anybody else's cards.

Rau's whole claim to being a real opponent rests on this file. If hidden state
leaks into the websocket payload the game is a lie in one direction; if it leaks
into his prompt it is a lie in the other. Both are checked by brute force over
whole games rather than by reading `view.py` and hoping.

The technique is a canary: a card type is forced to exist in exactly one place,
and then every payload produced over hundreds of moves is searched for it. A leak
anywhere — a stray field, a debug key, a log line that quotes a hand — trips it.

Run: python -m unittest tests.test_kittens_fairness -v
"""
from __future__ import annotations

import json
import random
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import deck as deck_mod  # noqa: E402
from rau.games.kittens import view as view_mod  # noqa: E402
from rau.games.kittens.deck import DEFUSE, EXPLODING_KITTEN  # noqa: E402
from rau.games.kittens.engine import (  # noqa: E402
    PHASE_OVER,
    RAU,
    USER,
    Game,
    IllegalMove,
)

#: A card type with no special rules, so moving every copy of it into one hand
#: changes nothing about how the game plays.
CANARY = "beard_cat"
OTHER_CANARY = "hairy_potato_cat"


def _isolate(game: Game, card: str, seat: str) -> None:
    """Make `card` exist only in `seat`'s hand, swapping replacements in."""
    pool = [c for c in deck_mod.CAT_CARDS if c not in (CANARY, OTHER_CANARY)]
    filler = pool[0]
    for holder in (USER, RAU):
        game.hands[holder] = [filler if c == card else c for c in game.hands[holder]]
    game.draw = [filler if c == card else c for c in game.draw]
    game.discard = [filler if c == card else c for c in game.discard]
    game.hands[seat].append(card)
    game.hands[seat].sort()


def _play_random(game: Game, rng: random.Random, seat: str) -> None:
    """One random legal move for `seat`. Silent if there is nothing to do."""
    moves = game.legal_moves(seat)
    if not moves:
        return
    move = rng.choice(moves)
    kind = move["move"]
    try:
        if kind == "play":
            game.play(seat, move["card"])
        elif kind == "combo":
            named = rng.choice(deck_mod.ALL_CARDS) if len(move["cards"]) == 3 else None
            game.combo(seat, move["cards"], named_card=named)
        elif kind == "draw":
            game.draw_card(seat)
        elif kind == "nope":
            game.nope(seat)
        elif kind == "pass_nope":
            game.pass_nope(seat)
        elif kind == "give_favor":
            game.give_favor(seat, move["card"])
        elif kind == "take_from_discard":
            game.take_from_discard(seat, move["card"])
        elif kind == "insert_kitten":
            game.insert_kitten(seat, rng.randint(0, len(game.draw)))
    except IllegalMove as exc:  # pragma: no cover - a bug in legal_moves
        raise AssertionError(f"legal_moves offered an illegal move: {move} ({exc})")


def _step(game: Game, rng: random.Random) -> None:
    game.tick(time.time() + 3600)
    if game.phase == PHASE_OVER:
        return
    _play_random(game, rng, game.awaiting_seat or game.current)


def _walk(node: Any, hit) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            hit(key, value)
            _walk(value, hit)
    elif isinstance(node, list):
        for value in node:
            _walk(value, hit)


def _without_your_own_guesses(view: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip the two places the payload quotes the user back to themselves.

    Three-of-a-kind works by naming a card out loud. That name, and the line in
    the feed announcing it, are the user's own words — finding a card there says
    nothing about whether Rau was holding it. Everything else in the payload is
    fair game for the leak hunt.
    """
    view = json.loads(json.dumps(view))
    if view.get("pending"):
        view["pending"].pop("named_card", None)
    view["log"] = [
        entry
        for entry in view.get("log", [])
        if not (entry.get("seat") == USER and "Demanded" in entry.get("text", ""))
    ]
    return view


class BrowserPayload(unittest.TestCase):
    def test_rau_hand_never_reaches_the_browser(self):
        for seed in range(60):
            rng = random.Random(seed)
            game = Game(seed=seed)
            _isolate(game, CANARY, RAU)
            for _ in range(400):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                if game.phase == PHASE_OVER:
                    break  # hands are turned face up at the end, on purpose
                payload = json.dumps(_without_your_own_guesses(view_mod.browser_view(game)))
                if CANARY in payload:
                    # If the browser can see it, it must not still be hidden in
                    # his hand — the only honest routes out are the discard pile
                    # and a transfer into the user's own hand.
                    self.assertNotIn(
                        CANARY,
                        game.hands[RAU],
                        f"seed {seed}: Rau's {CANARY} leaked while still in his hand",
                    )

    def test_the_draw_order_never_reaches_the_browser(self):
        for seed in range(60):
            rng = random.Random(seed)
            game = Game(seed=seed)
            for _ in range(400):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                view = view_mod.browser_view(game)
                self.assertEqual(
                    view.get("known_top"),
                    game.known_top[USER],
                    "only your own peek is yours",
                )
                # The pile is a number, never a sequence.
                self.assertIsInstance(view["deck_count"], int)
                found: List[str] = []
                _walk(view, lambda k, v: found.append(k))
                for forbidden in ("draw", "hands", "seed", "deck"):
                    self.assertNotIn(
                        forbidden, found, f"'{forbidden}' has no business in a seat view"
                    )

    def test_hand_counts_are_visible_but_hands_are_not(self):
        game = Game(seed=3)
        view = view_mod.browser_view(game)
        self.assertEqual(view["hand_counts"], {USER: 8, RAU: 8})
        self.assertEqual(sorted(view["hand"]), sorted(game.hands[USER]))
        self.assertNotIn("final_hands", view, "not until it is over")

    def test_hands_are_revealed_once_the_game_is_over(self):
        game = Game(seed=3)
        game.concede(USER)
        view = view_mod.browser_view(game)
        self.assertEqual(view["final_hands"][RAU], sorted(game.hands[RAU]))


class ModelPrompt(unittest.TestCase):
    def test_the_user_hand_never_reaches_the_prompt(self):
        for seed in range(60):
            rng = random.Random(seed)
            game = Game(seed=seed)
            _isolate(game, CANARY, USER)
            for _ in range(400):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                text = view_mod.prompt_fragment(game, RAU)
                if deck_mod.label(CANARY) in text or CANARY in text:
                    self.assertTrue(
                        CANARY in game.discard
                        or CANARY in game.hands[RAU]
                        or game.phase == PHASE_OVER,
                        f"seed {seed}: your {CANARY} leaked into Rau's context",
                    )

    def test_the_draw_order_never_reaches_the_prompt(self):
        for seed in range(40):
            rng = random.Random(seed)
            game = Game(seed=seed)
            for _ in range(300):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                text = view_mod.prompt_fragment(game, RAU)
                # A peek he paid a See the Future for is his to keep; anything
                # deeper than that is not.
                allowed = set(game.known_top[RAU])
                depth = len(allowed)
                for card in game.draw[depth:]:
                    if card in allowed:
                        continue
                    if card in game.hands[RAU] or card in game.discard:
                        continue  # nameable for honest reasons
                    self.assertNotIn(
                        f"top of the deck: {deck_mod.label(card)}",
                        text,
                        "he is reading past what he paid for",
                    )

    def test_he_is_told_the_size_of_your_hand_and_nothing_else_about_it(self):
        game = Game(seed=11)
        text = view_mod.prompt_fragment(game, RAU)
        self.assertIn("8 cards", text)
        self.assertIn("cannot see them", text)

    def test_every_move_he_is_offered_is_spelled_out(self):
        game = Game(seed=5)
        game.current = RAU
        text = view_mod.prompt_fragment(game, RAU)
        self.assertIn("Legal moves right now", text)
        self.assertIn('"move":', text)
        for move in game.legal_moves(RAU):
            if move["move"] == "play":
                self.assertIn(f'"card": "{move["card"]}"', text)

    def test_the_fragment_is_empty_of_rules_lecture_when_it_is_not_his_turn(self):
        game = Game(seed=5)
        game.current = USER
        text = view_mod.prompt_fragment(game, RAU)
        self.assertIn("their turn", text.lower())
        self.assertNotIn("Legal moves right now", text)

    def test_a_finished_game_says_so_and_stops(self):
        game = Game(seed=5)
        game.concede(USER)
        text = view_mod.prompt_fragment(game, RAU)
        self.assertIn("You won", text)
        self.assertNotIn("Legal moves", text)


class Symmetry(unittest.TestCase):
    def test_each_seat_sees_exactly_its_own_hand(self):
        for seed in range(30):
            rng = random.Random(seed)
            game = Game(seed=seed)
            for _ in range(200):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                for seat in (USER, RAU):
                    view = view_mod.seat_view(game, seat)
                    self.assertEqual(sorted(view["hand"]), sorted(game.hands[seat]))
                    self.assertEqual(view["seat"], seat)

    def test_neither_seat_is_told_where_the_kitten_is(self):
        for seed in range(30):
            rng = random.Random(seed)
            game = Game(seed=seed)
            for _ in range(300):
                if game.phase == PHASE_OVER:
                    break
                _step(game, rng)
                for seat in (USER, RAU):
                    known = view_mod.seat_view(game, seat)["known_top"]
                    if EXPLODING_KITTEN in known:
                        # Only ever via a See the Future they actually played.
                        self.assertEqual(
                            known,
                            game.known_top[seat],
                            "and only as deep as they paid for",
                        )
                        self.assertLessEqual(len(known), deck_mod.FUTURE_DEPTH)


if __name__ == "__main__":
    unittest.main()

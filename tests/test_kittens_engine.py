"""
The rules of Exploding Kittens, checked against the rulebook.

No UI, no model, no network — the engine is the risky part and this is where the
risk is retired.

Run: python -m unittest tests.test_kittens_engine -v
"""
from __future__ import annotations

import random
import sys
import time
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import deck as deck_mod  # noqa: E402
from rau.games.kittens.deck import (  # noqa: E402
    ATTACK,
    DEFUSE,
    EXPLODING_KITTEN,
    FAVOR,
    NOPE,
    SEE_THE_FUTURE,
    SHUFFLE,
    SKIP,
)
from rau.games.kittens.engine import (  # noqa: E402
    PHASE_DEFUSE,
    PHASE_FAVOR,
    PHASE_NOPE,
    PHASE_OVER,
    PHASE_PLAYING,
    PHASE_SALVAGE,
    RAU,
    USER,
    Game,
    IllegalMove,
)


def settle(game: Game) -> None:
    """Let every open Nope window expire, the way wall-clock time would."""
    for _ in range(8):
        if not game.tick(time.time() + 3600):
            break


def rigged(*, user: List[str], rau: List[str], draw: List[str]) -> Game:
    """A game with a known hand and a known deck, so outcomes are assertions."""
    game = Game(seed=1)
    game.hands[USER] = sorted(user)
    game.hands[RAU] = sorted(rau)
    game.draw = list(draw)
    game.discard = []
    game.current = USER
    game.turns_to_take = 1
    game.phase = PHASE_PLAYING
    return game


class DeckComposition(unittest.TestCase):
    def test_full_deck_is_the_box(self):
        full = deck_mod.build_full_deck()
        self.assertEqual(len(full), 56)
        self.assertEqual(full.count(EXPLODING_KITTEN), 4)
        self.assertEqual(full.count(DEFUSE), 6)
        self.assertEqual(full.count(NOPE), 5)
        self.assertEqual(full.count(SEE_THE_FUTURE), 5)
        for cat in deck_mod.CAT_CARDS:
            self.assertEqual(full.count(cat), 4)

    def test_two_player_setup_matches_the_rulebook(self):
        for seed in range(25):
            draw, hand_a, hand_b = deck_mod.deal_two_player(random.Random(seed))
            self.assertEqual(len(hand_a), 8, "seven cards plus a Defuse")
            self.assertEqual(len(hand_b), 8)
            self.assertEqual(hand_a.count(DEFUSE), 1, "exactly one guaranteed Defuse")
            self.assertEqual(hand_b.count(DEFUSE), 1)
            self.assertNotIn(EXPLODING_KITTEN, hand_a)
            self.assertNotIn(EXPLODING_KITTEN, hand_b)
            self.assertEqual(draw.count(EXPLODING_KITTEN), 1, "players minus one")
            self.assertEqual(draw.count(DEFUSE), 4, "the six, less the two dealt")
            # Three kittens and nothing else stay in the box.
            self.assertEqual(len(draw) + len(hand_a) + len(hand_b), 53)

    def test_deal_is_reproducible_from_its_seed(self):
        self.assertEqual(
            deck_mod.deal_two_player(random.Random(7)),
            deck_mod.deal_two_player(random.Random(7)),
        )


class Turns(unittest.TestCase):
    def test_drawing_ends_the_turn(self):
        game = rigged(user=[SKIP], rau=[SKIP], draw=[SHUFFLE, SHUFFLE])
        game.draw_card(USER)
        self.assertEqual(game.current, RAU)

    def test_playing_a_card_does_not_end_the_turn(self):
        game = rigged(user=[SHUFFLE, SEE_THE_FUTURE], rau=[], draw=[SKIP] * 5)
        game.play(USER, SHUFFLE)
        settle(game)
        self.assertEqual(game.current, USER, "you keep playing until you draw")
        game.play(USER, SEE_THE_FUTURE)
        settle(game)
        self.assertEqual(game.current, USER)

    def test_skip_ends_the_turn_without_drawing(self):
        game = rigged(user=[SKIP], rau=[], draw=[SHUFFLE] * 4)
        before = len(game.draw)
        game.play(USER, SKIP)
        settle(game)
        self.assertEqual(game.current, RAU)
        self.assertEqual(len(game.draw), before, "Skip costs you nothing but the card")

    def test_attack_hands_over_two_turns(self):
        game = rigged(user=[ATTACK], rau=[], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        settle(game)
        self.assertEqual(game.current, RAU)
        self.assertEqual(game.turns_to_take, 2)

    def test_attack_does_not_draw(self):
        game = rigged(user=[ATTACK], rau=[], draw=[SHUFFLE] * 6)
        before = len(game.draw)
        game.play(USER, ATTACK)
        settle(game)
        self.assertEqual(len(game.draw), before)

    def test_attacks_stack_to_four(self):
        game = rigged(user=[ATTACK], rau=[ATTACK], draw=[SHUFFLE] * 8)
        game.play(USER, ATTACK)
        settle(game)
        self.assertEqual((game.current, game.turns_to_take), (RAU, 2))
        game.play(RAU, ATTACK)
        settle(game)
        self.assertEqual(
            (game.current, game.turns_to_take), (USER, 4), "2 owed + 2 more"
        )

    def test_two_owed_turns_are_both_taken(self):
        game = rigged(user=[ATTACK], rau=[], draw=[SHUFFLE] * 8)
        game.play(USER, ATTACK)
        settle(game)
        game.draw_card(RAU)
        self.assertEqual(game.current, RAU, "one down, one to go")
        game.draw_card(RAU)
        self.assertEqual(game.current, USER)


class NopeStack(unittest.TestCase):
    def test_a_nope_cancels_the_action(self):
        game = rigged(user=[ATTACK], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        self.assertEqual(game.phase, PHASE_NOPE)
        game.nope(RAU)
        settle(game)
        self.assertEqual(game.current, USER, "the Attack never happened")
        self.assertEqual(game.turns_to_take, 1)

    def test_nope_the_nope_lets_it_through(self):
        game = rigged(user=[ATTACK, NOPE], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        game.nope(RAU)
        game.nope(USER)
        settle(game)
        self.assertEqual((game.current, game.turns_to_take), (RAU, 2))

    def test_third_nope_cancels_again(self):
        game = rigged(user=[ATTACK, NOPE], rau=[NOPE, NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        game.nope(RAU)
        game.nope(USER)
        game.nope(RAU)
        settle(game)
        self.assertEqual(game.current, USER, "odd number of Nopes cancels")

    def test_you_cannot_nope_your_own_card(self):
        game = rigged(user=[ATTACK, NOPE], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        with self.assertRaises(IllegalMove):
            game.nope(USER)

    def test_window_does_not_open_when_the_human_holds_no_nope(self):
        # They know their own hand, so a pause could only be dead air.
        game = rigged(user=[], rau=[ATTACK], draw=[SHUFFLE] * 6)
        game.current = RAU
        game.play(RAU, ATTACK)
        self.assertEqual(game.phase, PHASE_PLAYING, "resolved without waiting")

    def test_window_always_opens_against_rau(self):
        # If it closed early when he had no Nope, the pause itself would tell the
        # human he was holding one.
        game = rigged(user=[ATTACK], rau=[], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        self.assertEqual(game.phase, PHASE_NOPE)

    def test_expired_window_resolves_the_action(self):
        game = rigged(user=[ATTACK], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK, now=1000.0)
        self.assertFalse(game.tick(1002.0), "still inside the window")
        self.assertTrue(game.tick(1099.0))
        self.assertEqual(game.turns_to_take, 2)

    def test_passing_resolves_immediately(self):
        game = rigged(user=[ATTACK], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        game.pass_nope(RAU)
        self.assertEqual(game.phase, PHASE_PLAYING)
        self.assertEqual(game.turns_to_take, 2)


class Cards(unittest.TestCase):
    def test_see_the_future_shows_three_and_changes_nothing(self):
        top = [SKIP, ATTACK, FAVOR, SHUFFLE]
        game = rigged(user=[SEE_THE_FUTURE], rau=[], draw=list(top))
        game.play(USER, SEE_THE_FUTURE)
        settle(game)
        self.assertEqual(game.known_top[USER], top[:3])
        self.assertEqual(game.draw, top, "looking is not taking")

    def test_shuffle_invalidates_every_peek(self):
        game = rigged(user=[SEE_THE_FUTURE, SHUFFLE], rau=[], draw=[SKIP] * 12)
        game.play(USER, SEE_THE_FUTURE)
        settle(game)
        self.assertTrue(game.known_top[USER])
        game.play(USER, SHUFFLE)
        settle(game)
        self.assertEqual(game.known_top[USER], [], "a stale peek is a lie")

    def test_a_peek_shortens_as_the_deck_is_drawn(self):
        game = rigged(user=[SEE_THE_FUTURE], rau=[], draw=[SKIP, ATTACK, FAVOR, SHUFFLE])
        game.play(USER, SEE_THE_FUTURE)
        settle(game)
        game.draw_card(USER)
        self.assertEqual(game.known_top[USER], [ATTACK, FAVOR])

    def test_favor_blocks_until_the_victim_chooses(self):
        game = rigged(user=[FAVOR], rau=[SKIP, ATTACK], draw=[SHUFFLE] * 6)
        game.play(USER, FAVOR)
        settle(game)
        self.assertEqual(game.phase, PHASE_FAVOR)
        self.assertEqual(game.awaiting_seat, RAU)
        with self.assertRaises(IllegalMove):
            game.draw_card(USER)
        game.give_favor(RAU, ATTACK)
        self.assertEqual(game.phase, PHASE_PLAYING)
        self.assertIn(ATTACK, game.hands[USER])
        self.assertNotIn(ATTACK, game.hands[RAU])

    def test_favor_against_an_empty_hand_does_nothing(self):
        game = rigged(user=[FAVOR], rau=[], draw=[SHUFFLE] * 6)
        game.play(USER, FAVOR)
        settle(game)
        self.assertEqual(game.phase, PHASE_PLAYING)

    def test_defuse_cannot_be_played_from_hand(self):
        game = rigged(user=[DEFUSE], rau=[], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.play(USER, DEFUSE)

    def test_a_cat_card_alone_does_nothing(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[cat], rau=[], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.play(USER, cat)

    def test_nope_cannot_be_played_out_of_the_blue(self):
        game = rigged(user=[NOPE], rau=[], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.play(USER, NOPE)


class Combos(unittest.TestCase):
    def test_two_of_a_kind_steals_at_random(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[cat, cat], rau=[ATTACK], draw=[SHUFFLE] * 6)
        game.combo(USER, [cat, cat])
        settle(game)
        self.assertEqual(game.hands[RAU], [], "their only card is gone")
        self.assertIn(ATTACK, game.hands[USER])

    def test_two_of_a_kind_must_match(self):
        a, b = deck_mod.CAT_CARDS[0], deck_mod.CAT_CARDS[1]
        game = rigged(user=[a, b], rau=[ATTACK], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.combo(USER, [a, b])

    def test_three_of_a_kind_takes_the_card_you_name(self):
        cat = deck_mod.CAT_CARDS[2]
        game = rigged(user=[cat] * 3, rau=[ATTACK, SKIP], draw=[SHUFFLE] * 6)
        game.combo(USER, [cat] * 3, named_card=SKIP)
        settle(game)
        self.assertIn(SKIP, game.hands[USER])
        self.assertEqual(game.hands[RAU], [ATTACK])

    def test_naming_a_card_they_do_not_hold_gets_nothing(self):
        cat = deck_mod.CAT_CARDS[2]
        game = rigged(user=[cat] * 3, rau=[ATTACK], draw=[SHUFFLE] * 6)
        game.combo(USER, [cat] * 3, named_card=SKIP)
        settle(game)
        self.assertEqual(game.hands[RAU], [ATTACK])
        self.assertNotIn(SKIP, game.hands[USER])

    def test_three_of_a_kind_needs_a_name(self):
        cat = deck_mod.CAT_CARDS[2]
        game = rigged(user=[cat] * 3, rau=[ATTACK], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.combo(USER, [cat] * 3)

    def test_five_different_cards_salvage_the_discard_pile(self):
        five = [SKIP, ATTACK, FAVOR, SHUFFLE, SEE_THE_FUTURE]
        game = rigged(user=list(five), rau=[], draw=[SHUFFLE] * 6)
        game.discard = [NOPE]
        game.combo(USER, five)
        settle(game)
        self.assertEqual(game.phase, PHASE_SALVAGE)
        game.take_from_discard(USER, NOPE)
        self.assertIn(NOPE, game.hands[USER])
        self.assertEqual(game.phase, PHASE_PLAYING)

    def test_five_must_be_distinct(self):
        game = rigged(user=[SKIP] * 5, rau=[], draw=[SHUFFLE] * 6)
        game.discard = [NOPE]
        with self.assertRaises(IllegalMove):
            game.combo(USER, [SKIP] * 5)

    def test_a_combo_can_be_noped(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[cat, cat], rau=[NOPE, ATTACK], draw=[SHUFFLE] * 6)
        game.combo(USER, [cat, cat])
        game.nope(RAU)
        settle(game)
        self.assertIn(ATTACK, game.hands[RAU], "nothing was stolen")

    def test_you_cannot_play_cards_you_do_not_hold(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[cat], rau=[], draw=[SHUFFLE] * 6)
        with self.assertRaises(IllegalMove):
            game.combo(USER, [cat, cat])
        self.assertEqual(game.hands[USER], [cat], "and the failed attempt costs nothing")


class Explosions(unittest.TestCase):
    def test_drawing_the_kitten_without_a_defuse_loses(self):
        game = rigged(user=[SKIP], rau=[], draw=[EXPLODING_KITTEN])
        game.draw_card(USER)
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.winner, RAU)

    def test_a_defuse_saves_you_and_must_be_put_back(self):
        game = rigged(user=[DEFUSE], rau=[], draw=[EXPLODING_KITTEN, SKIP, ATTACK])
        game.draw_card(USER)
        self.assertEqual(game.phase, PHASE_DEFUSE)
        self.assertNotIn(DEFUSE, game.hands[USER], "the Defuse is spent")
        self.assertNotIn(EXPLODING_KITTEN, game.hands[USER], "it never enters a hand")
        with self.assertRaises(IllegalMove):
            game.draw_card(USER)
        game.insert_kitten(USER, 1)
        self.assertEqual(game.draw, [SKIP, EXPLODING_KITTEN, ATTACK])
        self.assertEqual(game.current, RAU, "defusing still ends your turn")

    def test_the_kitten_can_go_straight_back_on_top(self):
        game = rigged(user=[DEFUSE], rau=[], draw=[EXPLODING_KITTEN, SKIP])
        game.draw_card(USER)
        game.insert_kitten(USER, 0)
        self.assertEqual(game.draw[0], EXPLODING_KITTEN)

    def test_the_kitten_can_go_to_the_bottom(self):
        game = rigged(user=[DEFUSE], rau=[], draw=[EXPLODING_KITTEN, SKIP, ATTACK])
        game.draw_card(USER)
        game.insert_kitten(USER, len(game.draw))
        self.assertEqual(game.draw[-1], EXPLODING_KITTEN)

    def test_an_out_of_range_insert_is_refused(self):
        game = rigged(user=[DEFUSE], rau=[], draw=[EXPLODING_KITTEN, SKIP])
        game.draw_card(USER)
        with self.assertRaises(IllegalMove):
            game.insert_kitten(USER, 99)

    def test_defusing_does_not_reveal_where_it_went(self):
        game = rigged(user=[DEFUSE, SEE_THE_FUTURE], rau=[], draw=[EXPLODING_KITTEN, SKIP, ATTACK])
        game.play(USER, SEE_THE_FUTURE)
        settle(game)
        game.draw_card(USER)
        game.insert_kitten(USER, 2)
        self.assertEqual(game.known_top[USER], [], "the deck moved under the peek")

    def test_the_game_is_over_for_good(self):
        game = rigged(user=[], rau=[], draw=[EXPLODING_KITTEN])
        game.draw_card(USER)
        with self.assertRaises(IllegalMove):
            game.draw_card(RAU)


class LegalMoves(unittest.TestCase):
    def test_only_the_player_to_move_has_moves(self):
        game = rigged(user=[SKIP], rau=[SKIP], draw=[SHUFFLE] * 6)
        self.assertTrue(game.legal_moves(USER))
        self.assertEqual(game.legal_moves(RAU), [])

    def test_unplayable_cards_are_never_offered(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[DEFUSE, NOPE, cat], rau=[], draw=[SHUFFLE] * 6)
        played = {m.get("card") for m in game.legal_moves(USER) if m["move"] == "play"}
        self.assertEqual(played, set(), "Defuse, Nope and a lone cat are all unplayable")
        self.assertIn({"move": "draw"}, game.legal_moves(USER))

    def test_combos_appear_only_when_held(self):
        cat = deck_mod.CAT_CARDS[0]
        game = rigged(user=[cat, cat, cat], rau=[], draw=[SHUFFLE] * 6)
        sizes = {len(m["cards"]) for m in game.legal_moves(USER) if m["move"] == "combo"}
        self.assertEqual(sizes, {2, 3})

    def test_during_a_window_the_only_moves_are_nope_and_pass(self):
        game = rigged(user=[ATTACK], rau=[NOPE], draw=[SHUFFLE] * 6)
        game.play(USER, ATTACK)
        self.assertEqual(
            game.legal_moves(RAU), [{"move": "nope"}, {"move": "pass_nope"}]
        )
        self.assertEqual(game.legal_moves(USER), [], "you already committed")

    def test_every_offered_move_is_actually_legal(self):
        # The model is handed this list and trusted to pick from it. If anything
        # in it were illegal, the opponent would stall on its own turn.
        for seed in range(30):
            game = Game(seed=seed)
            for move in game.legal_moves(USER):
                trial = Game(seed=seed)
                if move["move"] == "play":
                    trial.play(USER, move["card"])
                elif move["move"] == "combo":
                    named = SKIP if len(move["cards"]) == 3 else None
                    trial.combo(USER, move["cards"], named_card=named)
                elif move["move"] == "draw":
                    trial.draw_card(USER)


class FullGames(unittest.TestCase):
    def test_random_play_always_terminates_with_a_winner(self):
        for seed in range(120):
            rng = random.Random(seed)
            game = Game(seed=seed)
            for _ in range(600):
                if game.phase == PHASE_OVER:
                    break
                settle(game)
                if game.phase == PHASE_OVER:
                    break
                seat = game.awaiting_seat or game.current
                moves = game.legal_moves(seat)
                if not moves:
                    self.fail(f"seed {seed}: {seat} has nothing legal in {game.phase}")
                move = rng.choice(moves)
                if move["move"] == "play":
                    game.play(seat, move["card"])
                elif move["move"] == "combo":
                    named = rng.choice(deck_mod.ALL_CARDS) if len(move["cards"]) == 3 else None
                    game.combo(seat, move["cards"], named_card=named)
                elif move["move"] == "draw":
                    game.draw_card(seat)
                elif move["move"] == "nope":
                    game.nope(seat)
                elif move["move"] == "pass_nope":
                    game.pass_nope(seat)
                elif move["move"] == "give_favor":
                    game.give_favor(seat, move["card"])
                elif move["move"] == "take_from_discard":
                    game.take_from_discard(seat, move["card"])
                elif move["move"] == "insert_kitten":
                    game.insert_kitten(seat, rng.randint(0, len(game.draw)))
            self.assertEqual(game.phase, PHASE_OVER, f"seed {seed} never finished")
            self.assertIn(game.winner, (USER, RAU))

    def test_cards_are_never_created_or_destroyed(self):
        for seed in range(40):
            rng = random.Random(seed)
            game = Game(seed=seed)
            total = len(game.draw) + sum(len(h) for h in game.hands.values())
            self.assertEqual(total, 53)
            for _ in range(400):
                if game.phase == PHASE_OVER:
                    break
                settle(game)
                if game.phase == PHASE_OVER:
                    break
                seat = game.awaiting_seat or game.current
                moves = game.legal_moves(seat)
                move = rng.choice(moves)
                if move["move"] == "play":
                    game.play(seat, move["card"])
                elif move["move"] == "combo":
                    named = rng.choice(deck_mod.ALL_CARDS) if len(move["cards"]) == 3 else None
                    game.combo(seat, move["cards"], named_card=named)
                elif move["move"] == "draw":
                    game.draw_card(seat)
                elif move["move"] == "nope":
                    game.nope(seat)
                elif move["move"] == "pass_nope":
                    game.pass_nope(seat)
                elif move["move"] == "give_favor":
                    game.give_favor(seat, move["card"])
                elif move["move"] == "take_from_discard":
                    game.take_from_discard(seat, move["card"])
                elif move["move"] == "insert_kitten":
                    game.insert_kitten(seat, rng.randint(0, len(game.draw)))
                counted = (
                    len(game.draw)
                    + sum(len(h) for h in game.hands.values())
                    + len(game.discard)
                )
                self.assertEqual(counted, 53, f"seed {seed}: cards went missing")


if __name__ == "__main__":
    unittest.main()

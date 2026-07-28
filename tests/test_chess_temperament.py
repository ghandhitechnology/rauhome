"""
The table manners: who sits where, and when he stops playing.

Two behaviours live here and both were promised rather than emergent. The
colours alternate between finished games, the way they do between two people at
a real board. And he behaves like a club player about lost and dead positions —
resigns the one, offers a draw in the other, and answers your offer out loud —
because an engine that grinds a lost king around the board to mate is the single
fastest way to stop believing anyone is sitting opposite you.

The temperament runs on the two booleans `MoveChoice` carries and nothing else,
so every test here drives `pump._run_rau_turn` directly with a stubbed engine
whose judgements are the fixture. No Stockfish, no providers, no threads racing
the assertions: the pump is parked and the turn function is called by hand,
which is the same code path minus the clock.

Run: python -m unittest tests.test_chess_temperament -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List, Optional

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.chess import engine as engine_mod  # noqa: E402
from rau.games.chess import level, player, pump, session, timing  # noqa: E402
from rau.games.chess.board import PHASE_OVER, PHASE_PLAYING, RAU, USER  # noqa: E402
from rau.games.chess.engine import MoveChoice  # noqa: E402
from tests.test_chess_session import (  # noqa: E402
    isolate_memory,
    park_the_pump,
    quiesce,
    silence_the_providers,
)


def _choice(board: chess.Board, **judgement: object) -> MoveChoice:
    """A real legal move in this position, wearing whatever judgement the test
    needs. The move must be genuine — it goes through the same door as the
    browser's — but the temperament only ever reads the flags."""
    move = next(iter(board.legal_moves))
    return MoveChoice(
        move=move,
        san=board.san(move),
        bucket=str(judgement.get("bucket", "level")),
        swing=float(judgement.get("swing", 0.0)),  # type: ignore[arg-type]
        is_capture=board.is_capture(move),
        is_check=board.gives_check(move),
        is_castle=board.is_castling(move),
        is_promotion=move.promotion is not None,
        piece="P",
        hopeless=bool(judgement.get("hopeless", False)),
        dead_level=bool(judgement.get("dead_level", False)),
    )


class TemperamentCase(unittest.TestCase):
    """A parked pump, a stubbed engine, and his lines caught in a list."""

    def setUp(self) -> None:
        isolate_memory(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)
        park_the_pump()

        # The pump cannot be trusted to stay parked: `apply_move` and `start`
        # both call `ensure()`, and a revived pump takes Rau's turn on its own
        # thread within a tick — racing the very calls these tests make by hand.
        # So the *module attribute* is stubbed out, the way `silence_the_engine`
        # does it, and the tests keep a private reference to the real function.
        # The loop looks the name up at call time and finds the stub; we call
        # the genuine article, alone, on this thread.
        self._real_turn = pump._run_rau_turn  # noqa: SLF001

        def no_turn() -> None:
            pump.thinking().clear()

        pump._run_rau_turn = no_turn  # noqa: SLF001
        self.addCleanup(setattr, pump, "_run_rau_turn", self._real_turn)

        self.judgement: dict = {}
        self.said: List[str] = []

        def fake_best_move(
            board: chess.Board,
            *,
            elo: int,
            game_id: str = "",
            previous: Optional[float] = None,
        ) -> MoveChoice:
            return _choice(board, **self.judgement)

        real_best = engine_mod.best_move
        engine_mod.best_move = fake_best_move  # type: ignore[assignment]
        self.addCleanup(setattr, engine_mod, "best_move", real_best)

        real_plan = timing.think_plan
        timing.think_plan = lambda board, choice, *, rng: timing.ThinkPlan(
            delay=0.01, hovers=[]
        )
        self.addCleanup(setattr, timing, "think_plan", real_plan)

        real_talk = player.table_talk
        player.table_talk = self.said.append  # type: ignore[assignment]
        self.addCleanup(setattr, player, "table_talk", real_talk)

    def game(self, rau_color: str = "black"):
        session.start(rau_color=rau_color)
        game = session.current()
        assert game is not None
        return game

    def user_moves(self, game) -> None:
        move = next(iter(game.board.legal_moves))
        result = session.apply_move(
            USER,
            {
                "move": "move",
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
            },
        )
        assert result.get("ok"), result

    def rau_turn(self) -> None:
        self._real_turn()  # the path the pump drives, minus the pump

    def exchange(self, game) -> None:
        """One full move pair: theirs, then his, at the current judgement."""
        self.user_moves(game)
        self.rau_turn()


class Resigning(TemperamentCase):
    def test_a_hopeless_position_held_long_enough_is_resigned(self):
        pump.RESIGN_MIN_PLY = 0
        self.addCleanup(setattr, pump, "RESIGN_MIN_PLY", 40)
        game = self.game()
        self.judgement = {"bucket": "losing", "hopeless": True}

        for _ in range(pump.RESIGN_STREAK):
            self.exchange(game)

        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.winner, USER)
        self.assertEqual(game.over_reason, "resignation")
        self.assertTrue(
            any(line in player.TABLE_LINES["resign"] for line in self.said),
            f"he resigned silently: {self.said}",
        )

    def test_one_wild_reading_does_not_break_him(self):
        """Streaks, not readings: a single bad search result is a hiccup."""
        pump.RESIGN_MIN_PLY = 0
        self.addCleanup(setattr, pump, "RESIGN_MIN_PLY", 40)
        game = self.game()

        self.judgement = {"bucket": "losing", "hopeless": True}
        self.exchange(game)
        self.exchange(game)
        self.judgement = {"bucket": "level"}  # the search steadies
        self.exchange(game)
        self.judgement = {"bucket": "losing", "hopeless": True}
        self.exchange(game)
        self.exchange(game)

        self.assertEqual(game.phase, PHASE_PLAYING, "resigned over a hiccup")

    def test_he_does_not_resign_the_opening(self):
        """RESIGN_MIN_PLY is the embarrassment floor. Hopeless on move three is
        played on anyway, which is what a person does."""
        game = self.game()
        self.judgement = {"bucket": "losing", "hopeless": True}
        for _ in range(pump.RESIGN_STREAK + 1):
            self.exchange(game)
        self.assertEqual(game.phase, PHASE_PLAYING)


class OfferingTheDraw(TemperamentCase):
    def setUp(self) -> None:
        super().setUp()
        pump.OFFER_MIN_PLY = 0
        self.addCleanup(setattr, pump, "OFFER_MIN_PLY", 60)

    def test_a_dead_position_earns_one_offer_and_only_one(self):
        game = self.game()
        self.judgement = {"dead_level": True}

        for _ in range(pump.OFFER_STREAK):
            self.exchange(game)

        self.assertIsNotNone(game.offer, "the dead position never produced an offer")
        self.assertEqual(game.offer.get("by"), RAU)
        self.assertTrue(any(line in player.TABLE_LINES["offer_draw"] for line in self.said))

        # Declined, and the position stays dead: he does not nag.
        session.apply_move(USER, {"move": "decline_draw"})
        park_the_pump()
        said_before = len(self.said)
        self.exchange(game)
        self.exchange(game)
        self.assertIsNone(game.offer, "he offered again after being told no")
        self.assertEqual(len(self.said), said_before)

    def test_his_offer_survives_their_thinking_and_can_be_taken(self):
        game = self.game()
        self.judgement = {"dead_level": True}
        for _ in range(pump.OFFER_STREAK):
            self.exchange(game)

        result = session.apply_move(USER, {"move": "accept_draw"})
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertIsNone(game.winner)


class AnsweringTheirs(TemperamentCase):
    def test_a_dead_draw_offered_the_normal_way_is_accepted(self):
        """Offer, then move, then wait — the order every real game uses. The
        offer must still be standing when his turn comes, and he must take it."""
        game = self.game()
        session.apply_move(USER, {"move": "offer_draw"})
        park_the_pump()
        self.judgement = {"dead_level": True}
        self.exchange(game)

        self.assertEqual(game.phase, PHASE_OVER)
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "draw agreed")
        self.assertTrue(any(line in player.TABLE_LINES["accept_draw"] for line in self.said))

    def test_a_swindle_is_declined_out_loud_and_the_game_goes_on(self):
        game = self.game()
        session.apply_move(USER, {"move": "offer_draw"})
        park_the_pump()
        self.judgement = {"bucket": "winning"}
        moves_before = len(game.moves)
        self.exchange(game)

        self.assertEqual(game.phase, PHASE_PLAYING)
        self.assertIsNone(game.offer, "the offer was left hanging")
        self.assertTrue(
            any(line in player.TABLE_LINES["decline_draw"] for line in self.said),
            "he declined in silence, which reads as not having heard",
        )
        self.assertEqual(len(game.moves), moves_before + 2, "declining cost him his move")

    def test_losing_he_takes_the_gift(self):
        game = self.game()
        session.apply_move(USER, {"move": "offer_draw"})
        park_the_pump()
        self.judgement = {"bucket": "losing"}
        self.exchange(game)
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertIsNone(game.winner)


class TheColours(TemperamentCase):
    """Alternation: finished games swap the seats, abandoned ones do not."""

    def finish(self, game) -> None:
        session.apply_move(USER, {"move": "resign"})
        session.end("booked")

    def test_the_first_game_gives_the_newcomer_white(self):
        view = session.start()
        self.assertEqual(view["rau_color"], "black")

    def test_finished_games_alternate_the_seats(self):
        view = session.start()
        self.assertEqual(view["rau_color"], "black")
        self.finish(session.current())

        view = session.start()
        self.assertEqual(view["rau_color"], "white", "the rematch did not swap sides")
        self.finish(session.current())

        view = session.start()
        self.assertEqual(view["rau_color"], "black")

    def test_an_abandoned_board_does_not_count_as_a_game(self):
        view = session.start()
        self.finish(session.current())  # one finished game: next default is white

        session.start()
        session.end("walked away mid-game")  # abandoned: no result, no flip

        view = session.start()
        self.assertEqual(
            view["rau_color"], "white", "walking away flipped the colours"
        )

    def test_asking_for_a_side_still_wins(self):
        session.start()
        self.finish(session.current())  # alternation now says white

        view = session.start(rau_color="black")
        park_the_pump()
        self.assertEqual(view["rau_color"], "black")

    def test_the_bookkeeping_never_leaves_the_process(self):
        session.start()
        self.finish(session.current())
        self.assertIn("last_rau_color", level.tally())
        self.assertNotIn("last_rau_color", session.tally())


if __name__ == "__main__":
    unittest.main()

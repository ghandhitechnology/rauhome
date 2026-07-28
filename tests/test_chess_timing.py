"""
The pause, and the claw inside it, held to its promises.

`timing.py` is the module that carries the whole "there is a person on the other
side of this board" claim, and it is the only module in the chess layer that can
be proven outright: it is pure, it takes an injected `random.Random`, and it
never opens a subprocess. So nothing here is sampled or approximated for
convenience — the delay bound is checked over hundreds of positions, the commit
rate is checked as a distribution rather than as a single lucky draw, and the
hover script is checked against the position it claims to be looking at.

Three properties are load-bearing and everything else in this file is texture
around them.

The first is that the delay never leaves `[FLOOR_SEC, CEIL_SEC]`. `pump.py`
sleeps for whatever this returns; a zero would make the move land before the user
let go of their own piece, and a number the wrong side of twenty seconds would
read as a crash. Neither is a bug you find in staging, because the lognormal tail
that produces them is rare and the failure looks like Rau being Rau.

The second is that the hover dwells sum to no more than the delay. The script is
played out beat by beat while the delay runs, so a script longer than the pause
means the claw is still reaching when the piece has already moved.

The third is that the same seed gives the same theatre twice. Without it none of
the above can be tested at all, and a replayed game would perform differently
from the one that was recorded.

Run: python -m unittest tests.test_chess_timing -v
"""
from __future__ import annotations

import random
import statistics
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.chess import timing  # noqa: E402
from rau.games.chess.engine import MoveChoice  # noqa: E402
from rau.games.chess.timing import (  # noqa: E402
    BAND_BOOK,
    BAND_CROWDED,
    BAND_ENDGAME,
    BAND_FORCED,
    BAND_ORDINARY,
    BAND_RECAPTURE,
    BAND_STARE,
    CEIL_SEC,
    COMMIT_CHANCE,
    FLOOR_SEC,
    HOVER_FILL,
    MIN_DWELL,
    HoverStep,
    ThinkPlan,
    think_plan,
)

#: A position with exactly one legal move: the king on h1 must take the queen on
#: g2 or stand in check. Nothing to decide, so nothing to think about.
FORCED_FEN = "7k/8/8/8/8/8/6q1/7K w - - 0 1"

#: A full-board middlegame, forty-seven legal moves, nothing hanging. This is the
#: position the "quiet and crowded" band exists for.
CROWDED_FEN = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2Q1RK1 w - - 0 9"

#: Four pawns each and two kings. Less board to read, so a faster answer.
ENDGAME_FEN = "8/5pk1/6p1/7p/7P/6P1/5PK1/8 w - - 0 40"

#: Twelve men or more and thirty legal moves or fewer: neither crowded nor an
#: endgame, which is what "otherwise" means.
ORDINARY_FEN = "r4rk1/pp3ppp/2n1p3/q1ppP3/3P4/P1PB1N2/2P2PPP/R2Q1RK1 w - - 0 15"

#: Two queens against a bare king. Four men — an endgame by the man count — and
#: thirty-six legal moves, so it is also crowded. It exists to settle which of
#: those two the module believes.
CROWDED_ENDGAME_FEN = "7k/8/8/8/8/8/8/K1QQ4 w - - 0 60"

#: The moves into a Najdorf that end with the user taking on f4, so the reply is
#: a recapture in a position with forty-seven legal moves.
RECAPTURE_LINE = [
    "e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6",
    "Be2", "e5", "Nb3", "Be7", "O-O", "O-O", "Be3", "Be6", "f4", "exf4",
]


def choice_for(
    board: chess.Board,
    move: chess.Move,
    *,
    swing: float = 0.0,
    bucket: str = "level",
) -> MoveChoice:
    """
    The real `MoveChoice`, filled in the way `engine.best_move` fills it.

    Deliberately the engine's own dataclass rather than a stand-in: `timing.py`
    imports it under `TYPE_CHECKING` only, so a field renamed on one side of that
    line would never be caught by the type checker. Building the genuine article
    here means these tests fail the day the two modules stop agreeing.
    """
    piece = board.piece_at(move.from_square)
    return MoveChoice(
        move=move,
        san=board.san(move),
        bucket=bucket,
        swing=swing,
        is_capture=board.is_capture(move),
        is_check=board.gives_check(move),
        is_castle=board.is_castling(move),
        is_promotion=move.promotion is not None,
        piece=piece.symbol().upper() if piece else "",
    )


def san_choice(board: chess.Board, san: str, **kwargs) -> MoveChoice:
    return choice_for(board, board.parse_san(san), **kwargs)


def recapture_board() -> chess.Board:
    """A live board — move stack and all — where the reply on f4 takes back."""
    board = chess.Board()
    for san in RECAPTURE_LINE:
        board.push_san(san)
    return board


def delays(board: chess.Board, choice: MoveChoice, count: int = 600) -> List[float]:
    """`count` draws from the same position, one per seed, sorted."""
    return sorted(
        think_plan(board, choice, rng=random.Random(seed)).delay
        for seed in range(count)
    )


def percentile(sorted_values: List[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def wandered_positions(count: int, *, rng: random.Random) -> List[chess.Board]:
    """
    Positions reached by playing random legal moves out of the opening.

    Random walks rather than a fixture list because the guarantees below are
    supposed to hold for *any* position Rau can be handed, including the ugly
    ones nobody would think to write down: bare kings, eight-queen promotions,
    positions where every piece is pinned.
    """
    boards: List[chess.Board] = []
    while len(boards) < count:
        board = chess.Board()
        for _ in range(rng.randrange(0, 70)):
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(rng.choice(legal))
        if board.legal_moves.count() == 0:
            continue  # nothing to move means nothing to time
        boards.append(board)
    return boards


class Predictable(random.Random):
    """
    An rng that always makes the same call, so anything that still varies in the
    output is the code deciding rather than the dice.

    `random()` answers high, which takes every "did he look somewhere else"
    branch; `choice` always takes the first option; `uniform` always takes the
    top of the range. That drives two consecutive steps onto the same square,
    which is exactly the case the de-duplication pass exists to clean up.
    """

    def random(self) -> float:
        return 0.99

    def uniform(self, a: float, b: float) -> float:
        return b

    def lognormvariate(self, mu: float, sigma: float) -> float:
        return 1.0

    def choice(self, seq):
        return seq[0]


def isolate_memory(case: unittest.TestCase) -> Path:
    """
    Point the memories tree at a temporary directory for the duration.

    Nothing in `timing.py` should go anywhere near disk, and that is asserted
    outright further down. This is the belt to that test's braces: if a future
    edit gives the module a cache file or a log, it lands in a tmpdir instead of
    on top of the real running record of games.
    """
    import rau.paths as paths_mod

    tmp = Path(tempfile.mkdtemp(prefix="rau-chess-timing-"))
    saved = {
        name: getattr(paths_mod, name)
        for name in ("MEMORIES_DIR", "GAMES_FILE", "GAMES_DIR")
    }
    paths_mod.MEMORIES_DIR = tmp
    paths_mod.GAMES_FILE = tmp / "games.json"
    paths_mod.GAMES_DIR = tmp / "games"

    def restore() -> None:
        for name, value in saved.items():
            setattr(paths_mod, name, value)
        shutil.rmtree(tmp, ignore_errors=True)

    case.addCleanup(restore)
    return tmp


class TimingCase(unittest.TestCase):
    """Every test in this file runs with the memories tree redirected."""

    def setUp(self) -> None:
        self.tmp = isolate_memory(self)


class Bands(TimingCase):
    """The contract's table of cases, checked as behaviour rather than as code."""

    def test_a_position_with_one_legal_move_is_answered_almost_at_once(self):
        """
        Nothing to decide is the one case where a long pause is a tell in the
        other direction: a man who stares at a forced recapture is a man who did
        not see it, and Rau is supposed to have seen it.
        """
        board = chess.Board(FORCED_FEN)
        self.assertEqual(board.legal_moves.count(), 1, "the fixture must stay forced")
        sample = delays(board, san_choice(board, "Kxg2"))
        self.assertLessEqual(statistics.median(sample), 1.0)
        self.assertLess(percentile(sample, 0.9), 1.5)

    def test_a_crowded_quiet_middlegame_is_answered_slowly(self):
        """
        Forty-seven legal moves and nothing forcing: this is the position where
        taking a while is not only credible but expected, and the band is where
        most of the feature's perceived thinking actually happens.
        """
        board = chess.Board(CROWDED_FEN)
        self.assertGreater(board.legal_moves.count(), timing.CROWDED_MOVES)
        sample = delays(board, san_choice(board, "Ne5"))
        self.assertGreaterEqual(statistics.median(sample), BAND_CROWDED[0])
        self.assertGreater(percentile(sample, 0.1), 3.0)

    def test_the_fast_band_and_the_slow_band_do_not_overlap(self):
        """
        The bands are only worth having if they are audible. If a forced move can
        take longer than a quiet middlegame the whole shape washes out into one
        undifferentiated pause, which is the thing this module was written to
        avoid — so the tails are checked, not just the medians.
        """
        forced = delays(chess.Board(FORCED_FEN), san_choice(chess.Board(FORCED_FEN), "Kxg2"))
        crowded = delays(chess.Board(CROWDED_FEN), san_choice(chess.Board(CROWDED_FEN), "Ne5"))
        self.assertLess(
            percentile(forced, 0.9),
            percentile(crowded, 0.1),
            "his quickest quiet middlegame must still beat his slowest forced move",
        )

    def test_a_big_swing_earns_the_long_stare(self):
        """
        Something just changed by more than a pawn and a half. Answering that at
        middlegame speed says he had already seen it, which — since Stockfish
        found it in four milliseconds — is exactly the truth he is hiding.
        """
        board = chess.Board(CROWDED_FEN)
        quiet = delays(board, san_choice(board, "Ne5", swing=0.2))
        stared = delays(board, san_choice(board, "Ne5", swing=3.0))
        self.assertGreater(statistics.median(stared), statistics.median(quiet))
        self.assertGreaterEqual(statistics.median(stared), BAND_STARE[0])

    def test_the_stare_does_not_care_which_way_the_swing_went(self):
        """A collapse is as worth staring at as a windfall, so `abs` is the test."""
        board = chess.Board(CROWDED_FEN)
        good = statistics.median(delays(board, san_choice(board, "Ne5", swing=3.0)))
        bad = statistics.median(delays(board, san_choice(board, "Ne5", swing=-3.0)))
        self.assertGreaterEqual(good, BAND_STARE[0])
        self.assertGreaterEqual(bad, BAND_STARE[0])

    def test_an_endgame_is_answered_faster_than_a_crowded_middlegame(self):
        """
        Eight men on the board and nine legal moves. There is less to read, and a
        long pause over a king-and-pawn ending reads as stalling rather than as
        calculating.
        """
        endgame = chess.Board(ENDGAME_FEN)
        crowded = chess.Board(CROWDED_FEN)
        quick = delays(endgame, san_choice(endgame, "g4"))
        slow = delays(crowded, san_choice(crowded, "Ne5"))
        self.assertLess(statistics.median(quick), statistics.median(slow))
        self.assertLess(percentile(quick, 0.9), percentile(slow, 0.5))

    def test_a_known_opening_move_comes_back_at_book_speed(self):
        """
        He is not calculating 1.e4, and pretending to would be the single most
        obvious lie available. The list is not a real book, which is fine: being
        wrong costs half a second of pause on a move that deserved two.
        """
        board = chess.Board()
        sample = delays(board, san_choice(board, "e4"))
        self.assertLessEqual(statistics.median(sample), BAND_BOOK[1] * 1.2)
        self.assertLess(
            statistics.median(sample),
            statistics.median(delays(chess.Board(ORDINARY_FEN),
                                     san_choice(chess.Board(ORDINARY_FEN), "Rb1"))),
        )


class BandPrecedence(TimingCase):
    """
    Which case wins when a position is several of them at once.

    A forced recapture in an endgame is three cases simultaneously, so the order
    inside `_band` is the actual design decision and the seven-line table in the
    contract is only the raw material. Each test below is one edge of that order,
    asserted against the band constants rather than against a number, so retuning
    a band cannot silently pass a precedence test.
    """

    def test_forcedness_beats_everything_including_the_stare(self):
        """
        A single legal move removes the thing he would be thinking about, and it
        removes it even when the position just fell apart. Staring at a move you
        have no choice about is not thought, it is a freeze.
        """
        board = chess.Board(FORCED_FEN)
        choice = san_choice(board, "Kxg2", swing=-6.0)
        self.assertEqual(timing._band(board, choice), BAND_FORCED)

    def test_a_surprise_in_the_opening_beats_the_book(self):
        """
        This is the one place the module deliberately departs from the order the
        contract's table is written in, and the module docstring says why: a
        swing that size inside eight plies means the opening stopped being an
        opening. Somebody gambited or somebody hung a piece, and answering a real
        surprise at book speed is the precise tell everything here exists to
        avoid. So the stare is tested *above* book, not below it.
        """
        board = chess.Board()
        self.assertLess(board.ply(), timing.BOOK_PLY)
        self.assertIn("e4", timing.BOOK_MOVES)
        self.assertEqual(timing._band(board, san_choice(board, "e4", swing=2.0)), BAND_STARE)
        self.assertEqual(timing._band(board, san_choice(board, "e4", swing=0.1)), BAND_BOOK)

    def test_book_beats_recapture(self):
        """
        1.e4 d5 2.exd5 is both a recapture on the square she just moved to and a
        move nobody has ever thought about. The book is the better description.
        """
        board = chess.Board()
        board.push_san("e4")
        board.push_san("d5")
        choice = san_choice(board, "exd5")
        self.assertTrue(choice.is_capture)
        self.assertEqual(timing._last_move_target(board), chess.D5)
        self.assertEqual(timing._band(board, choice), BAND_BOOK)

    def test_recapture_beats_crowded(self):
        """
        Forty-seven legal moves, but only one of them is the answer to being
        taken on f4. Deliberating over a recapture reads as not having seen it
        coming, and the crowd on the board is irrelevant to that.
        """
        board = recapture_board()
        self.assertGreater(board.legal_moves.count(), timing.CROWDED_MOVES)
        self.assertGreaterEqual(board.ply(), timing.BOOK_PLY)
        choice = san_choice(board, "Bxf4")
        self.assertEqual(timing._band(board, choice), BAND_RECAPTURE)

    def test_a_capture_that_is_not_on_the_last_moved_square_is_not_a_recapture(self):
        """
        The recapture band is about the square, not about the capture. Taking
        somewhere else is an ordinary decision and gets ordinary time.
        """
        board = recapture_board()
        board.push_san("Bxf4")
        board.push_san("Nc6")
        self.assertEqual(timing._last_move_target(board), chess.C6)
        choice = san_choice(board, "Bxd6")
        self.assertTrue(choice.is_capture)
        self.assertNotEqual(timing._band(board, choice), BAND_RECAPTURE)

    def test_crowded_beats_endgame(self):
        """
        Two queens against a bare king is four men — an endgame by the head count
        — and thirty-six legal moves. The count of men was only ever a proxy for
        how much there is to look at, and here the proxy is wrong, so the thing
        it was standing in for wins.
        """
        board = chess.Board(CROWDED_ENDGAME_FEN)
        self.assertLess(len(board.piece_map()), timing.ENDGAME_MEN)
        self.assertGreater(board.legal_moves.count(), timing.CROWDED_MOVES)
        self.assertEqual(timing._band(board, san_choice(board, "Qc7")), BAND_CROWDED)

    def test_endgame_beats_ordinary(self):
        board = chess.Board(ENDGAME_FEN)
        self.assertLess(len(board.piece_map()), timing.ENDGAME_MEN)
        self.assertLessEqual(board.legal_moves.count(), timing.CROWDED_MOVES)
        self.assertEqual(timing._band(board, san_choice(board, "g4")), BAND_ENDGAME)

    def test_a_middlegame_that_is_none_of_the_above_falls_through_to_ordinary(self):
        board = chess.Board(ORDINARY_FEN)
        self.assertGreaterEqual(len(board.piece_map()), timing.ENDGAME_MEN)
        self.assertLessEqual(board.legal_moves.count(), timing.CROWDED_MOVES)
        self.assertEqual(timing._band(board, san_choice(board, "Rb1")), BAND_ORDINARY)


class DelayBounds(TimingCase):
    """
    The one hard guarantee. `pump.py` sleeps for this number.

    The jitter is lognormal and unbounded on the upside, so the ceiling is not
    decoration — it fires regularly on the stare band, where the top of the range
    is already eighteen seconds. Checked over several hundred positions crossed
    with several hundred seeds rather than over a fixture, because the failure
    mode is a tail.
    """

    def test_the_delay_never_leaves_the_bounds_over_hundreds_of_positions(self):
        rng = random.Random(20260728)
        boards = wandered_positions(240, rng=rng)
        seen = 0
        for board in boards:
            for _ in range(3):
                move = rng.choice(list(board.legal_moves))
                # Swings well past the stare threshold in both directions, so the
                # widest band gets the most draws rather than the fewest.
                choice = choice_for(board, move, swing=rng.uniform(-9.0, 9.0))
                plan = think_plan(board, choice, rng=random.Random(rng.randrange(10**9)))
                self.assertGreaterEqual(plan.delay, FLOOR_SEC, board.fen())
                self.assertLessEqual(plan.delay, CEIL_SEC, board.fen())
                seen += 1
        self.assertGreater(seen, 500, "the sweep must actually be a sweep")

    def test_the_ceiling_is_reached_and_not_merely_declared(self):
        """
        If nothing ever hit twenty seconds the bound would be untested in
        practice and could be wrong by a factor of ten without anyone noticing.
        The stare band's own top is eighteen, so the tail is where the clamp
        earns its place.
        """
        board = chess.Board(CROWDED_FEN)
        sample = delays(board, san_choice(board, "Ne5", swing=4.0), count=1500)
        self.assertEqual(max(sample), CEIL_SEC)

    def test_the_floor_is_reached_on_a_forced_move(self):
        board = chess.Board(FORCED_FEN)
        sample = delays(board, san_choice(board, "Kxg2"), count=1500)
        self.assertEqual(min(sample), FLOOR_SEC)

    def test_the_delay_is_rounded_to_something_a_person_could_read(self):
        """Two decimals. A delay of 4.7318102 is a number nobody chose."""
        board = chess.Board(CROWDED_FEN)
        for seed in range(200):
            delay = think_plan(board, san_choice(board, "Ne5"), rng=random.Random(seed)).delay
            self.assertEqual(delay, round(delay, 2))


class Determinism(TimingCase):
    """
    Same seed, same theatre.

    Everything else in this file depends on it, and so does any future replay of
    a recorded game: a pause that came out differently on the way back would make
    the recording a different performance from the one that happened.
    """

    def test_the_same_seed_gives_the_same_plan_twice(self):
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        first = think_plan(board, choice, rng=random.Random(7))
        second = think_plan(board, choice, rng=random.Random(7))
        self.assertEqual(first, second)
        self.assertEqual(first.hovers, second.hovers)

    def test_different_seeds_give_different_plans(self):
        """
        Determinism is only worth having if it is determinism about something. A
        module that returned the same pause for every seed would pass the test
        above and fail the entire premise.
        """
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        plans = [
            think_plan(board, choice, rng=random.Random(seed))
            for seed in range(40)
        ]
        distinct = {repr(plan) for plan in plans}
        self.assertGreater(len(distinct), 30, "forty seeds should not agree")

    def test_a_plan_is_a_value_and_not_a_view_of_the_rng(self):
        """Frozen dataclasses all the way down, so a plan can be stored and
        compared rather than merely consumed."""
        board = chess.Board(CROWDED_FEN)
        plan = think_plan(board, san_choice(board, "Ne5"), rng=random.Random(3))
        self.assertIsInstance(plan, ThinkPlan)
        self.assertTrue(all(isinstance(step, HoverStep) for step in plan.hovers))
        with self.assertRaises(Exception):
            plan.hovers[0].dwell = 9.0  # type: ignore[misc]


class HoverScript(TimingCase):
    """The visible half of the lie: where the claw goes while the pause runs."""

    def test_the_script_never_outlasts_the_pause(self):
        """
        The dwells are played out beat by beat inside the delay. A script longer
        than the pause means the claw is still reaching for a square after the
        piece it was reaching for has already moved, which is not a subtle tell.
        """
        rng = random.Random(11)
        for board in wandered_positions(200, rng=rng):
            move = rng.choice(list(board.legal_moves))
            choice = choice_for(board, move, swing=rng.uniform(-4.0, 4.0))
            plan = think_plan(board, choice, rng=random.Random(rng.randrange(10**9)))
            self.assertLessEqual(
                round(sum(step.dwell for step in plan.hovers), 6),
                plan.delay,
                f"script overran the pause in {board.fen()}",
            )

    def test_the_script_leaves_a_beat_of_stillness_before_the_move(self):
        """
        `HOVER_FILL` caps the script well short of the whole pause on purpose.
        The remainder is the stillness that makes the move land rather than
        merely continue — without it the piece moves out of the middle of a
        gesture and the whole thing reads as a machine.
        """
        board = chess.Board(CROWDED_FEN)
        for seed in range(200):
            plan = think_plan(board, san_choice(board, "Ne5"), rng=random.Random(seed))
            filled = sum(step.dwell for step in plan.hovers) / plan.delay
            self.assertLessEqual(filled, HOVER_FILL[1] + 0.02)

    def test_there_is_always_at_least_one_look_and_never_a_crowd_of_them(self):
        """One to three steps. Zero is a claw that never moved; four is a twitch."""
        rng = random.Random(5)
        for board in wandered_positions(120, rng=rng):
            move = rng.choice(list(board.legal_moves))
            plan = think_plan(board, choice_for(board, move), rng=random.Random(rng.randrange(10**9)))
            self.assertGreaterEqual(len(plan.hovers), 1)
            self.assertLessEqual(len(plan.hovers), 3)

    def test_a_short_pause_gets_a_single_look(self):
        board = chess.Board(FORCED_FEN)
        for seed in range(120):
            plan = think_plan(board, san_choice(board, "Kxg2"), rng=random.Random(seed))
            if plan.delay < 1.2:
                self.assertEqual(len(plan.hovers), 1)

    def test_every_dwell_is_long_enough_to_read_as_a_look(self):
        """Below `MIN_DWELL` the claw arrives and leaves inside one animation
        frame, which the eye reads as a glitch rather than as attention."""
        rng = random.Random(13)
        for board in wandered_positions(120, rng=rng):
            move = rng.choice(list(board.legal_moves))
            plan = think_plan(board, choice_for(board, move), rng=random.Random(rng.randrange(10**9)))
            for step in plan.hovers:
                self.assertGreaterEqual(step.dwell, MIN_DWELL)

    def test_every_square_he_looks_at_is_one_he_could_actually_move_from(self):
        """
        The claw is drawn over a real board. A hover on an empty square, on a
        piece that cannot move, or on the user's side of the position is a
        visible impossibility — and `None`, which reads as sitting back, is the
        only non-square the script is allowed to contain.
        """
        rng = random.Random(17)
        for board in wandered_positions(200, rng=rng):
            origins = {chess.square_name(m.from_square) for m in board.legal_moves}
            move = rng.choice(list(board.legal_moves))
            choice = choice_for(board, move, swing=rng.uniform(-3.0, 3.0))
            plan = think_plan(board, choice, rng=random.Random(rng.randrange(10**9)))
            for step in plan.hovers:
                if step.square is None:
                    continue
                self.assertIn(step.square, origins, board.fen())

    def test_two_identical_looks_in_a_row_never_survive(self):
        """
        The claw sitting on one square across two beats is a dropped frame, not a
        decision — there is no visible difference between "he looked at d4 twice"
        and "the animation stalled".
        """
        rng = random.Random(23)
        for board in wandered_positions(200, rng=rng):
            move = rng.choice(list(board.legal_moves))
            plan = think_plan(board, choice_for(board, move), rng=random.Random(rng.randrange(10**9)))
            squares = [step.square for step in plan.hovers]
            for before, after in zip(squares, squares[1:]):
                if after is None:
                    continue  # two beats of sitting back is stillness, not a stall
                self.assertNotEqual(before, after, board.fen())

    def test_the_repeat_is_broken_by_blanking_the_earlier_look(self):
        """
        Which of the two duplicated beats gets removed matters. Blanking the
        *earlier* one leaves the commit on the square he plays from, so the claw
        still lands on the piece a beat before it moves; blanking the later one
        would take that away. Driven with an rng that makes every choice
        identically, so the only thing left to vary the script is the fix itself.
        """
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        home = chess.square_name(choice.move.from_square)
        others = sorted(
            {chess.square_name(m.from_square) for m in board.legal_moves} - {home}
        )
        plan = think_plan(board, choice, rng=Predictable())
        self.assertEqual(len(plan.hovers), 2)
        self.assertIsNone(plan.hovers[0].square, "the earlier look is the one that goes")
        self.assertEqual(plan.hovers[1].square, others[0])


class TheCommit(TimingCase):
    """
    How often the last thing he looks at is the piece he plays.

    Always would be a machine reaching for its answer. Never would be nonsense.
    Roughly three times in four is a man who mostly knows what he is doing and
    occasionally does not, and that ratio is the single cheapest thing in the
    module that makes the pause look occupied rather than merely long — so it is
    asserted as a rate over hundreds of seeds, not as one draw that happened to
    come out right.
    """

    def _last_squares(self, board: chess.Board, choice: MoveChoice, count: int) -> List[Optional[str]]:
        return [
            think_plan(board, choice, rng=random.Random(seed)).hovers[-1].square
            for seed in range(count)
        ]

    def test_he_usually_ends_on_the_piece_he_plays(self):
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        home = chess.square_name(choice.move.from_square)
        lasts = self._last_squares(board, choice, 2000)
        rate = sum(1 for square in lasts if square == home) / len(lasts)
        self.assertAlmostEqual(rate, COMMIT_CHANCE, delta=0.05)

    def test_but_sometimes_he_was_looking_at_something_else_entirely(self):
        """
        He considered something else and played anyway. If this never happened
        the pause would be an announcement rather than a deliberation.
        """
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        home = chess.square_name(choice.move.from_square)
        lasts = self._last_squares(board, choice, 2000)
        elsewhere = [square for square in lasts if square != home]
        self.assertGreater(len(elsewhere), 300)
        self.assertNotIn(None, elsewhere, "the last beat is never sitting back")
        self.assertGreater(len(set(elsewhere)), 5, "and not always the same wrong square")

    def test_the_last_look_is_the_longest_one(self):
        """
        He commits during that beat, so it carries the extra weight. A script
        that tapers off at the end reads as losing interest.
        """
        board = chess.Board(CROWDED_FEN)
        for seed in range(300):
            plan = think_plan(board, san_choice(board, "Ne5", swing=3.0), rng=random.Random(seed))
            if len(plan.hovers) < 2:
                continue
            self.assertGreaterEqual(
                plan.hovers[-1].dwell,
                max(step.dwell for step in plan.hovers[:-1]),
            )

    def test_when_there_is_nowhere_else_to_look_he_looks_at_the_piece(self):
        """
        A forced move has exactly one origin square, so `others` is empty and
        every branch that would have picked a different square has to fall back
        rather than crash or produce a `None` at the commit.
        """
        board = chess.Board(FORCED_FEN)
        choice = san_choice(board, "Kxg2")
        home = chess.square_name(choice.move.from_square)
        for seed in range(200):
            plan = think_plan(board, choice, rng=random.Random(seed))
            self.assertEqual(plan.hovers[-1].square, home)


class TheTrim(TimingCase):
    """
    What happens when the dwell floor and the delay disagree.

    Every dwell is floored at `MIN_DWELL` and the whole script is then trimmed
    back to fit inside the delay. Those two rules can pull in opposite
    directions, and the module resolves it by trimming the last step — the one
    with the most to give. This is the corner nobody reaches by playing, which is
    exactly why it needs a test rather than a comment.
    """

    def _forced_counts(self) -> Dict[int, float]:
        """The shortest delay at which each step count can occur."""
        shortest: Dict[int, float] = {}
        for step in range(int(FLOOR_SEC * 100), int(CEIL_SEC * 100) + 1, 1):
            delay = step / 100.0
            for seed in range(4):
                count = timing._step_count(delay, random.Random(seed))
                shortest.setdefault(count, delay)
        return shortest

    def test_the_dwell_floor_can_never_bind_on_a_delay_he_can_actually_produce(self):
        """
        This is why the guarantee holds rather than merely usually holding. For
        every step count, the shortest delay that can produce it still leaves the
        smallest weighted share above `MIN_DWELL`, so the floor never inflates a
        real script and the trim below never has to fight it. Change `FLOOR_SEC`,
        `MIN_DWELL`, `HOVER_FILL` or the step-count thresholds and this is the
        test that notices.
        """
        for count, delay in sorted(self._forced_counts().items()):
            weights = [1.0] * (count - 1) + [1.6]
            share = delay * HOVER_FILL[0] / sum(weights)
            self.assertGreaterEqual(
                min(weights) * share,
                MIN_DWELL,
                f"{count} steps at {delay}s would be floored into overrunning",
            )

    def test_the_trim_pulls_an_overlong_script_back_inside_the_pause(self):
        """
        Forced into the corner by hand: three steps over a fifth of a second,
        which the real step-count rule would never ask for. The floors inflate
        the script past the delay, the trim takes the overflow off the last step,
        and the result is inside the pause again wherever the floor leaves room
        for it to be — and pinned at exactly the sum of the floors where it does
        not, since `MIN_DWELL` is the harder of the two rules.
        """
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        count = 3
        floor_total = round(count * MIN_DWELL, 2)
        rescued = 0
        with patch.object(timing, "_step_count", lambda delay, rng: count):
            for hundredths in range(10, 50):
                delay = hundredths / 100.0
                for seed in range(120):
                    steps = timing._hovers(board, choice, delay, rng=random.Random(seed))
                    self.assertEqual(len(steps), count)
                    total = round(sum(step.dwell for step in steps), 2)
                    self.assertLessEqual(
                        total,
                        max(delay, floor_total) + 1e-9,
                        f"trim gave up at delay={delay}",
                    )
                    if floor_total < total <= delay:
                        rescued += 1
        self.assertGreater(
            rescued,
            0,
            "the sweep never actually exercised the trim, so it proved nothing",
        )

    def test_the_trim_never_shortens_a_dwell_below_the_floor(self):
        board = chess.Board(CROWDED_FEN)
        choice = san_choice(board, "Ne5")
        with patch.object(timing, "_step_count", lambda delay, rng: 3):
            for hundredths in range(10, 60):
                for seed in range(40):
                    steps = timing._hovers(board, choice, hundredths / 100.0, rng=random.Random(seed))
                    for step in steps:
                        self.assertGreaterEqual(step.dwell, MIN_DWELL)


class RestoredBoards(TimingCase):
    """
    A board rebuilt from a FEN has no move stack.

    That is the state Rau comes back in after a restart, and it is his first turn
    back — the worst possible moment for an `IndexError` out of a module whose
    entire job is to look unhurried.
    """

    def test_a_board_with_no_history_has_no_last_move(self):
        board = chess.Board(CROWDED_FEN)
        self.assertEqual(len(board.move_stack), 0)
        self.assertIsNone(timing._last_move_target(board))

    def test_the_starting_position_has_no_last_move(self):
        self.assertIsNone(timing._last_move_target(chess.Board()))

    def test_planning_from_a_restored_position_does_not_raise(self):
        """
        A capture is the dangerous case: it is the branch that asks what the
        last move was, and on a restored board there is no answer.
        """
        board = recapture_board()
        restored = chess.Board(board.fen())
        choice = san_choice(restored, "Bxf4")
        self.assertTrue(choice.is_capture)
        plan = think_plan(restored, choice, rng=random.Random(2))
        self.assertGreaterEqual(plan.delay, FLOOR_SEC)
        self.assertNotEqual(timing._band(restored, choice), BAND_RECAPTURE)

    def test_a_restored_board_still_gets_a_legal_hover_script(self):
        board = chess.Board(ENDGAME_FEN)
        origins = {chess.square_name(m.from_square) for m in board.legal_moves}
        for seed in range(100):
            plan = think_plan(board, san_choice(board, "g4"), rng=random.Random(seed))
            for step in plan.hovers:
                self.assertTrue(step.square is None or step.square in origins)


class Purity(TimingCase):
    """
    The module claims to be pure, and the claim is worth an assertion.

    It is what makes every test above cheap enough to run in bulk, and it is what
    keeps the performance layer from acquiring a dependency on Stockfish by
    accident.
    """

    def test_planning_writes_nothing_to_the_memories_tree(self):
        rng = random.Random(31)
        for board in wandered_positions(60, rng=rng):
            move = rng.choice(list(board.legal_moves))
            think_plan(board, choice_for(board, move), rng=random.Random(1))
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()),
            [],
            "timing.py has no business on disk",
        )

    def test_planning_leaves_the_position_exactly_as_it_found_it(self):
        """
        `board` is the position before the move, and the caller still needs it —
        `session.py` pushes the move itself once the pause is over. A plan that
        consumed the board would leave the game a ply ahead of the performance.
        """
        board = recapture_board()
        before_fen = board.fen()
        before_stack = list(board.move_stack)
        think_plan(board, san_choice(board, "Bxf4", swing=1.9), rng=random.Random(4))
        self.assertEqual(board.fen(), before_fen)
        self.assertEqual(board.move_stack, before_stack)

    def test_the_module_does_not_import_the_engine_at_runtime(self):
        """
        `MoveChoice` is imported under `TYPE_CHECKING` for exactly this reason. A
        real import would drag `chess.engine` and the Stockfish wrapper into a
        module that is supposed to be runnable on a machine with no engine at
        all.
        """
        source = Path(timing.__file__).read_text(encoding="utf-8")
        runtime_lines = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from "))
        ]
        for line in runtime_lines:
            self.assertNotIn("rau.games.chess.engine", line)
            self.assertNotIn("chess.engine", line)


if __name__ == "__main__":
    unittest.main()

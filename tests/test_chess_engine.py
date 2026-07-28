"""
The wall between Stockfish and the man at the table.

`engine.py` is the only module in the chess layer that knows a number. Everything
downstream of it — the pause, the line said across the table, the face — is
written against `bucket` and `swing`, and the whole illusion depends on the
translation being right at this one boundary. A Rau who can tell you he is +1.4
after twelve ply is visibly a program. A Rau who knows he is *better*, and that
things just *swung his way*, is a man.

Two things in here are easy to get wrong and expensive to get wrong quietly.

The first is whose point of view the bucket is from. Stockfish reports from
White's side; Rau is Black in half the games. An inverted bucket does not crash,
does not log, and does not look like a bug — it looks like Rau cheerfully
gloating while being mated, which is a thing you only discover by playing him as
White. So the buckets are tested from both colours, twice: once against a stubbed
score where the arithmetic is visible, and once against the real binary where it
is not.

The second is the swing memory. It is keyed by `game_id` precisely so that the
first move of a new game cannot inherit the last evaluation of the old one, which
would open every game with Rau reacting to something that happened yesterday.

Everything except a handful of shallow integration checks runs against a stubbed
`_play`, so no subprocess is started and nothing here touches the network. The
integration checks skip rather than fail when there is no Stockfish installed —
a machine without one is not a broken machine, it is a machine where Rau declines
the game.

Run: python -m unittest tests.test_chess_engine -v
"""
from __future__ import annotations

import dataclasses
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.chess import binary  # noqa: E402
from rau.games.chess import engine as engine_mod  # noqa: E402
from rau.games.chess.engine import (  # noqa: E402
    BETTER,
    LEVEL,
    MATE_PAWNS,
    WINNING,
    WORSE,
    MoveChoice,
    best_move,
    forget,
)

#: Elo inside the band `level.py` clamps to. Only the integration tests care.
TEST_ELO = 1500

#: The same material with the side to move flipped, so the only thing that
#: differs between the two is whose turn it is. White has an extra queen in both.
QUEEN_UP_WHITE_TO_MOVE = "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"
QUEEN_UP_BLACK_TO_MOVE = "3qk3/8/8/8/8/8/8/4K3 b - - 0 1"
QUEEN_DOWN_WHITE_TO_MOVE = "3qk3/8/8/8/8/8/8/4K3 w - - 0 1"

#: Every field the contract says `MoveChoice` carries, and no other.
CONTRACT_FIELDS = {
    "move",
    "san",
    "bucket",
    "swing",
    "is_capture",
    "is_check",
    "is_castle",
    "is_promotion",
    "piece",
    # The temperament's two signals. Booleans, not numbers — `hopeless` is "a
    # person would resign here" and `dead_level` is "a person would offer the
    # draw here", and both were added precisely so the pump never has to be
    # handed the evaluation those judgements were made from.
    "hopeless",
    "dead_level",
}

#: Words that would mean a number escaped. Checked against the field names, so a
#: future `cp` or `depth` bolted onto the dataclass trips this file rather than
#: quietly reaching `banter.py`.
LEAKY_WORDS = ("cp", "centipawn", "score", "depth", "pv", "nodes", "eval", "info", "elo")


def play_result(move: chess.Move, score: Optional[chess.engine.PovScore]) -> chess.engine.PlayResult:
    """What a `SimpleEngine.play` call looks like from the outside."""
    info = {} if score is None else {"score": score}
    return chess.engine.PlayResult(move, None, info)


def white_cp(centipawns: int) -> chess.engine.PovScore:
    """A score as Stockfish reports it: always relative to White."""
    return chess.engine.PovScore(chess.engine.Cp(centipawns), chess.WHITE)


def white_mate(moves: int) -> chess.engine.PovScore:
    return chess.engine.PovScore(chess.engine.Mate(moves), chess.WHITE)


def isolate_memory(case: unittest.TestCase) -> Path:
    """
    Point the memories tree at a temporary directory for the duration.

    `engine.py` should never write anything — its only state is an in-process
    dict and a subprocess — but `memories/games.json` and `memories/games/` are
    the real running record on this machine, and a test suite that can destroy
    them on a bad refactor is a worse risk than the bug it would have caught.
    """
    import rau.paths as paths_mod

    tmp = Path(tempfile.mkdtemp(prefix="rau-chess-engine-"))
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


class EngineCase(unittest.TestCase):
    """
    A case with the memories tree redirected and the swing memory swept up.

    The swing memory is module-global and outlives any one test, which is the
    point of it in production and a cross-contamination hazard here. Every test
    gets its own game id and drops it on the way out.
    """

    def setUp(self) -> None:
        self.tmp = isolate_memory(self)
        self.game_id = f"test-{self.id()}"
        self.addCleanup(forget, self.game_id)


class StubbedEngineCase(EngineCase):
    """A case where `_play` is replaced, so no Stockfish is ever started."""

    def given(self, *results: chess.engine.PlayResult) -> List[chess.Board]:
        """
        Queue the answers `_play` will give, in order.

        Returns the list the stub records boards into, so a test can check what
        the engine was actually asked as well as what it did with the reply.
        """
        seen: List[chess.Board] = []
        queue: List[chess.engine.PlayResult] = list(results)

        def fake_play(board: chess.Board, elo: int) -> chess.engine.PlayResult:
            seen.append(board.copy())
            return queue.pop(0) if len(queue) > 1 else queue[0]

        patcher = patch.object(engine_mod, "_play", fake_play)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen


class Buckets(StubbedEngineCase):
    """
    The five words Rau is allowed to know about his own position.

    Tested against the boundary constants rather than against literals, so
    retuning a boundary moves the test with it — but the *shape* of the ladder,
    which floor is inclusive and which is not, is pinned here on purpose.
    """

    def test_the_ladder_is_read_top_down(self):
        table = [
            (12.0, "winning"),
            (WINNING, "winning"),
            (WINNING - 0.01, "better"),
            (1.5, "better"),
            (BETTER, "better"),
            (BETTER - 0.01, "level"),
            (0.0, "level"),
            (LEVEL + 0.01, "level"),
            (LEVEL, "worse"),
            (-1.5, "worse"),
            (WORSE + 0.01, "worse"),
            (WORSE, "losing"),
            (-12.0, "losing"),
        ]
        for pawns, expected in table:
            self.assertEqual(engine_mod._bucket(pawns), expected, f"{pawns} pawns")

    def test_level_is_the_only_band_that_straddles_zero(self):
        """
        A dead-drawn position and a position half a pawn either way are the same
        thing to a person at a table, and a Rau who announced he was "better" for
        being up a tenth of a pawn would be reading a number out loud.
        """
        self.assertEqual(engine_mod._bucket(0.0), "level")
        self.assertEqual(engine_mod._bucket(0.7), "level")
        self.assertEqual(engine_mod._bucket(-0.7), "level")

    def test_the_boundaries_are_exactly_the_contract(self):
        """The numbers themselves, so a stray edit to a constant is loud."""
        self.assertEqual((WINNING, BETTER, LEVEL, WORSE), (3.0, 0.8, -0.8, -3.0))


class PointOfView(StubbedEngineCase):
    """
    Whose side the bucket is read from. The single easiest thing here to invert.

    Stockfish always reports relative to White. `best_move` takes `board.turn` as
    Rau's side, because it is his move, and flips the score onto it. Getting that
    backwards produces a Rau who congratulates himself while being mated, which
    no test of White-to-move positions would ever catch.
    """

    def _choice(self, fen: str, score: chess.engine.PovScore) -> MoveChoice:
        board = chess.Board(fen)
        move = next(iter(board.legal_moves))
        self.given(play_result(move, score))
        return best_move(board, elo=TEST_ELO, game_id=self.game_id, previous=0.0)

    def test_a_score_for_white_is_winning_when_rau_is_white(self):
        choice = self._choice(chess.STARTING_FEN, white_cp(320))
        self.assertEqual(choice.bucket, "winning")
        self.assertAlmostEqual(choice.swing, 3.2, places=2)

    def test_the_same_score_is_losing_when_rau_is_black(self):
        """
        Identical centipawns, identical everything, black to move. If this comes
        back "winning" the buckets are being read from White's chair.
        """
        black_to_move = chess.STARTING_FEN.replace(" w ", " b ")
        choice = self._choice(black_to_move, white_cp(320))
        self.assertEqual(choice.bucket, "losing")
        self.assertAlmostEqual(choice.swing, -3.2, places=2)

    def test_a_score_against_white_is_winning_when_rau_is_black(self):
        black_to_move = chess.STARTING_FEN.replace(" w ", " b ")
        choice = self._choice(black_to_move, white_cp(-150))
        self.assertEqual(choice.bucket, "better")

    def test_both_colours_agree_on_level(self):
        """Nought is nought from either chair, which is the sanity check that
        catches a sign flip applied twice."""
        white = self._choice(chess.STARTING_FEN, white_cp(0))
        self.assertEqual(white.bucket, "level")
        forget(self.game_id)
        black = self._choice(chess.STARTING_FEN.replace(" w ", " b "), white_cp(0))
        self.assertEqual(black.bucket, "level")


class MateScores(StubbedEngineCase):
    """
    A mate is not a number on the same scale as everything else.

    Left alone, python-chess hands back tens of thousands of centipawns for a
    forced mate. That is not "winning by three hundred pawns", it is a sentinel,
    and letting it through would give `swing` a value that drags every band in
    `timing.py` off its hinges — the long stare fires on `abs(swing) > 1.5`, and a
    swing of 290 is not more of a surprise than a swing of 3.
    """

    def _pawns(self, fen: str, score: chess.engine.PovScore) -> float:
        board = chess.Board(fen)
        move = next(iter(board.legal_moves))
        self.given(play_result(move, score))
        # `previous=0.0` makes `swing` equal the evaluation itself, which is the
        # only window the contract leaves onto the number.
        return best_move(board, elo=TEST_ELO, game_id=self.game_id, previous=0.0).swing

    def test_a_mate_for_rau_clamps_to_ten_pawns(self):
        pawns = self._pawns(chess.STARTING_FEN, white_mate(3))
        self.assertLessEqual(pawns, MATE_PAWNS)
        self.assertGreater(pawns, MATE_PAWNS - 1.0)
        self.assertNotAlmostEqual(pawns, 300.0, places=1, msg="30000cp arrived raw")

    def test_a_mate_against_rau_clamps_to_minus_ten_pawns(self):
        pawns = self._pawns(chess.STARTING_FEN, white_mate(-2))
        self.assertGreaterEqual(pawns, -MATE_PAWNS)
        self.assertLess(pawns, -(MATE_PAWNS - 1.0))

    def test_a_mate_is_still_unambiguously_winning_or_losing(self):
        """
        The clamp has to leave the score clear of the `winning` floor, or it
        would trade an explosion for a Rau who is calm about being mated.
        """
        board = chess.Board(chess.STARTING_FEN)
        move = next(iter(board.legal_moves))
        self.given(play_result(move, white_mate(1)))
        self.assertEqual(
            best_move(board, elo=TEST_ELO, game_id=self.game_id).bucket, "winning"
        )
        self.assertGreater(MATE_PAWNS, WINNING)

    def test_an_enormous_ordinary_score_is_clamped_too(self):
        """A crushing position and a forced mate should not be different orders of
        magnitude to anything downstream."""
        pawns = self._pawns(chess.STARTING_FEN, white_cp(4200))
        self.assertEqual(pawns, MATE_PAWNS)


class SwingMemory(StubbedEngineCase):
    """
    What "things just changed" means, and why it is keyed by game.

    `swing` is the difference against the last time Rau looked at this board,
    which is a whole exchange ago in table time. It is the input to the long
    stare and to half of what `banter.py` has to say, so a stale value from a
    finished game does not fail loudly — it just makes him react to nothing.
    """

    def _look(self, centipawns: int, *, game_id: Optional[str] = None, **kwargs) -> MoveChoice:
        board = chess.Board()
        move = next(iter(board.legal_moves))
        self.given(play_result(move, white_cp(centipawns)))
        return best_move(
            board,
            elo=TEST_ELO,
            game_id=self.game_id if game_id is None else game_id,
            **kwargs,
        )

    def test_the_first_look_at_a_new_game_never_swung(self):
        """
        There is no previous position to have swung from. Reporting the
        evaluation itself as the swing would open every game with Rau staring at
        the board as though something had just happened.
        """
        self.assertEqual(self._look(250).swing, 0.0)

    def test_the_second_look_measures_the_difference(self):
        self._look(250)
        self.assertAlmostEqual(self._look(-90).swing, -3.4, places=2)

    def test_the_swing_is_rounded_to_hundredths_of_a_pawn(self):
        """Two decimals is already more precision than anything downstream can
        use; the raw subtraction of two floats is not a number anyone chose."""
        self._look(37)
        swing = self._look(-114).swing
        self.assertEqual(swing, -1.51)
        self.assertEqual(swing, round(swing, 2))

    def test_forgetting_a_game_stops_the_next_one_inheriting_its_swing(self):
        """
        `session.py` calls `forget` when a game ends. Without it the first move of
        the next game would carry the difference between two unrelated positions,
        which is the largest swing the system can produce and would fire the long
        stare on move one of every game after the first.
        """
        self._look(600)
        forget(self.game_id)
        self.assertEqual(self._look(-600).swing, 0.0)

    def test_two_games_in_one_run_do_not_see_each_others_evaluations(self):
        other = f"{self.game_id}-other"
        self.addCleanup(forget, other)
        self._look(500)
        self.assertEqual(self._look(-500, game_id=other).swing, 0.0)
        self.assertAlmostEqual(self._look(-500).swing, -10.0, places=2)

    def test_an_explicit_previous_overrides_what_was_remembered(self):
        """
        A restored or replayed game has nothing remembered for it, so the caller
        supplies the number. When it does, it wins — otherwise a restart would
        make him react to the difference between the position he came back to and
        the position he left, which is zero moves of chess.
        """
        self._look(0)
        self.assertAlmostEqual(self._look(100, previous=3.0).swing, -2.0, places=2)

    def test_a_game_with_no_id_remembers_nothing(self):
        """
        The default empty id is the throwaway path — a one-off evaluation that
        must not write itself into the memory of whatever game is actually being
        played.
        """
        before = dict(engine_mod._last_eval)
        self.assertEqual(self._look(400, game_id="").swing, 0.0)
        self.assertEqual(self._look(-400, game_id="").swing, 0.0)
        self.assertEqual(engine_mod._last_eval, before)

    def test_a_search_that_came_back_without_a_score_invents_nothing(self):
        """
        Depth-limited searches occasionally return no score line. Treating that
        as zero would read as the position having collapsed to level; the module
        reuses the last thing it knew instead, so the swing is nought and nobody
        reacts to a missing line as though it were news.
        """
        self._look(250)
        board = chess.Board()
        move = next(iter(board.legal_moves))
        self.given(play_result(move, None))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertEqual(choice.swing, 0.0)
        self.assertEqual(choice.bucket, "better", "it kept the last thing it knew")


class TheContract(StubbedEngineCase):
    """
    What is allowed out of this module, checked as a shape.

    `banter.py` and `timing.py` are written against exactly these fields. A tenth
    field is not a small addition — it is a number reaching the half of Rau that
    is supposed to be performing rather than calculating.
    """

    def test_move_choice_carries_exactly_the_contract_fields(self):
        names = {field.name for field in dataclasses.fields(MoveChoice)}
        self.assertEqual(names, CONTRACT_FIELDS)

    def test_no_field_is_named_after_a_number_that_should_have_stopped_here(self):
        for field in dataclasses.fields(MoveChoice):
            lowered = field.name.lower()
            for word in LEAKY_WORDS:
                self.assertNotIn(word, lowered.split("_"), f"{field.name} leaks {word}")

    def test_a_choice_is_frozen(self):
        """It is handed to three modules and pushed through an event bus. Nobody
        downstream gets to rewrite what the engine decided."""
        board = chess.Board()
        move = next(iter(board.legal_moves))
        self.given(play_result(move, white_cp(0)))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            choice.bucket = "winning"  # type: ignore[misc]

    def test_the_san_is_the_one_from_the_position_before_the_move(self):
        """
        SAN is only computable in the position the move is legal in, and the
        caller has already been handed a board it is about to push onto. Getting
        this a ply late produces plausible-looking nonsense in the move list.
        """
        board = chess.Board()
        board.push_san("e4")
        board.push_san("e5")
        move = board.parse_san("Nf3")
        self.given(play_result(move, white_cp(20)))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertEqual(choice.san, "Nf3")
        self.assertEqual(choice.piece, "N")

    def test_the_flags_describe_the_move_and_not_the_evaluation(self):
        board = chess.Board("r3k2r/pppq1ppp/2np1n2/2b1p1B1/2B1P1b1/2NP1N2/PPPQ1PPP/R3K2R w KQkq - 0 9")
        castles = board.parse_san("O-O")
        self.given(play_result(castles, white_cp(15)))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertTrue(choice.is_castle)
        self.assertFalse(choice.is_capture)
        self.assertFalse(choice.is_promotion)
        self.assertEqual(choice.piece, "K")

    def test_a_promotion_and_a_check_are_both_reported(self):
        board = chess.Board("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
        move = board.parse_san("b8=Q+")
        self.given(play_result(move, white_mate(4)))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertTrue(choice.is_promotion)
        self.assertTrue(choice.is_check)
        self.assertEqual(choice.piece, "P", "the piece is the one that left, not the one that arrived")

    def test_a_capture_is_reported_as_one(self):
        board = chess.Board()
        board.push_san("e4")
        board.push_san("d5")
        move = board.parse_san("exd5")
        self.given(play_result(move, white_cp(30)))
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertTrue(choice.is_capture)


class WhenThingsGoWrong(StubbedEngineCase):
    """The two failures a caller has to live with, and the one it does not."""

    def test_a_dead_engine_is_reopened_once_and_the_move_still_lands(self):
        """
        Stockfish gets killed by the OS, or the machine sleeps with the pipe
        open. That is recoverable and the user should never learn it happened —
        it arrives as one slightly longer pause, which is a thing Rau does anyway.
        """
        board = chess.Board()
        move = next(iter(board.legal_moves))
        calls: List[int] = []

        def flaky(inner_board: chess.Board, elo: int) -> chess.engine.PlayResult:
            calls.append(elo)
            if len(calls) == 1:
                raise chess.engine.EngineTerminatedError("engine process died")
            return play_result(move, white_cp(10))

        with patch.object(engine_mod, "_play", flaky), \
                patch.object(engine_mod, "_shutdown") as shutdown:
            choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)

        self.assertEqual(len(calls), 2, "exactly one retry, not a ladder")
        self.assertEqual(shutdown.call_count, 1, "the corpse is cleared before retrying")
        self.assertEqual(choice.san, board.san(move))

    def test_a_second_failure_belongs_to_the_caller(self):
        """
        One retry, then stop. A loop here would hang the pump on a machine where
        the binary has genuinely gone away, and the caller has a real answer for
        that: Rau declines the game.
        """

        def always_dead(board: chess.Board, elo: int) -> chess.engine.PlayResult:
            raise chess.engine.EngineTerminatedError("still dead")

        with patch.object(engine_mod, "_play", always_dead), \
                patch.object(engine_mod, "_shutdown"):
            with self.assertRaises(chess.engine.EngineTerminatedError):
                best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)

    def test_an_engine_that_returns_no_move_is_an_error_not_a_none(self):
        """
        A `MoveChoice` with `move=None` would travel three modules before failing
        somewhere that has no idea what happened.
        """
        self.given(play_result(None, white_cp(0)))
        with self.assertRaises(RuntimeError):
            best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)

    def test_asking_for_a_move_with_no_binary_installed_raises(self):
        """
        `available()` is how callers are supposed to find out, and it answers
        without spawning anything. If they ask anyway they get one clear
        exception rather than a traceback out of the subprocess module.
        """
        engine_mod.close()
        with patch.object(binary, "found", lambda **kwargs: None):
            self.assertFalse(engine_mod.available())
            with self.assertRaises(RuntimeError):
                best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)


class Housekeeping(StubbedEngineCase):
    def test_closing_forgets_every_game(self):
        """
        `close` runs at exit and on the doctor's request. Leaving evaluations
        behind after the process has let go of the engine would be state with
        nothing to be state about.
        """
        board = chess.Board()
        move = next(iter(board.legal_moves))
        self.given(play_result(move, white_cp(400)))
        best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertIn(self.game_id, engine_mod._last_eval)
        engine_mod.close()
        self.assertEqual(engine_mod._last_eval, {})

    def test_closing_twice_is_harmless(self):
        engine_mod.close()
        engine_mod.close()

    def test_forgetting_a_game_that_was_never_played_is_harmless(self):
        forget("no-such-game")

    def test_choosing_a_move_writes_nothing_to_the_memories_tree(self):
        """
        The elo lives in `level.py` and the position lives in `journal.py`. This
        module owns a subprocess and a dict, and nothing on disk.
        """
        board = chess.Board()
        move = next(iter(board.legal_moves))
        self.given(play_result(move, white_cp(0)))
        best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertEqual(list(self.tmp.iterdir()), [])


@unittest.skipUnless(binary.found(), "no stockfish on this machine")
class AgainstTheRealBinary(EngineCase):
    """
    A handful of shallow checks against the actual engine.

    Everything above proves the arithmetic. These prove the arithmetic is wired
    to a real Stockfish that really answers, because a stub cannot tell you that
    `INFO_SCORE` still comes back on a depth-limited search, or that the score is
    reported from White's side rather than the mover's — which is the assumption
    the entire point-of-view flip rests on and is a property of the protocol, not
    of this file.

    Deliberately few and deliberately shallow: search depth is eight, so the
    whole class costs well under a second.
    """

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(engine_mod.close)

    def test_he_answers_the_starting_position_with_a_legal_move(self):
        board = chess.Board()
        choice = best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertIn(choice.move, board.legal_moves)
        self.assertEqual(choice.san, board.san(choice.move))
        self.assertEqual(choice.swing, 0.0, "nothing to have swung from yet")
        self.assertEqual(choice.bucket, "level", "the start of a game is level")
        self.assertIn(choice.piece, {"P", "N"}, "and it is an opening move")
        self.assertFalse(choice.is_capture)

    def test_the_board_comes_back_untouched(self):
        """
        `best_move` is asked in the position before the move and the caller still
        needs that position — it is what `timing.py` reads and what `session.py`
        pushes onto.
        """
        board = chess.Board()
        board.push_san("e4")
        before = board.fen()
        best_move(board, elo=TEST_ELO, game_id=self.game_id)
        self.assertEqual(board.fen(), before)

    def test_a_queen_up_is_winning_from_either_colour(self):
        """
        The same material, once with Rau as White and once with Rau as Black. A
        point-of-view bug would make exactly one of these say "losing", and it is
        the kind of bug that survives every test written by somebody who only
        ever played him as Black.
        """
        as_white = best_move(
            chess.Board(QUEEN_UP_WHITE_TO_MOVE), elo=TEST_ELO, game_id=self.game_id
        )
        forget(self.game_id)
        as_black = best_move(
            chess.Board(QUEEN_UP_BLACK_TO_MOVE), elo=TEST_ELO, game_id=self.game_id
        )
        self.assertEqual(as_white.bucket, "winning")
        self.assertEqual(as_black.bucket, "winning")

    def test_a_queen_down_is_losing_and_not_merely_the_mirror_image(self):
        """
        The same FEN as the black-to-move case above with the turn flipped, so
        the position is identical and only the chair changed. Reading White's
        score straight through would call this one winning too.
        """
        choice = best_move(
            chess.Board(QUEEN_DOWN_WHITE_TO_MOVE), elo=TEST_ELO, game_id=self.game_id
        )
        self.assertEqual(choice.bucket, "losing")

    def test_a_real_swing_is_measured_across_two_looks_at_one_game(self):
        """
        Two positions a queen apart, evaluated in sequence under one game id.
        This is the whole mechanism end to end: the memory, the point of view and
        the subtraction, with a real search on both sides of it.
        """
        best_move(chess.Board(QUEEN_UP_WHITE_TO_MOVE), elo=TEST_ELO, game_id=self.game_id)
        collapsed = best_move(
            chess.Board(QUEEN_DOWN_WHITE_TO_MOVE), elo=TEST_ELO, game_id=self.game_id
        )
        self.assertLess(collapsed.swing, -1.5, "that is worth a long stare")
        self.assertGreaterEqual(collapsed.swing, -2 * MATE_PAWNS)

    def test_no_centipawn_ever_reaches_the_choice(self):
        """
        The bound the whole module exists to hold, checked against real scores
        rather than against ones this file made up. Anything outside the clamp
        would mean the mate sentinel or a raw centipawn count got through.
        """
        for fen in (chess.STARTING_FEN, QUEEN_UP_WHITE_TO_MOVE, QUEEN_DOWN_WHITE_TO_MOVE):
            forget(self.game_id)
            first = best_move(chess.Board(fen), elo=TEST_ELO, game_id=self.game_id, previous=0.0)
            self.assertLessEqual(abs(first.swing), MATE_PAWNS)
            self.assertIn(
                first.bucket, {"winning", "better", "level", "worse", "losing"}
            )

    def test_the_engine_is_opened_once_and_reused(self):
        """
        A fork, a UCI handshake and a hash allocation per move would put a
        visible hiccup in front of every one of his turns — landing in exactly
        the place `timing.py` is shaping by hand.
        """
        engine_mod.close()
        best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)
        first = engine_mod._engine
        self.assertIsNotNone(first)
        best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)
        self.assertIs(engine_mod._engine, first)

    def test_the_elo_is_only_sent_when_it_changes(self):
        """
        `configure` is a round trip to the engine and the elo moves once a game,
        not once a move.
        """
        engine_mod.close()
        best_move(chess.Board(), elo=TEST_ELO, game_id=self.game_id)
        self.assertEqual(engine_mod._configured_elo, TEST_ELO)
        best_move(chess.Board(), elo=TEST_ELO + 100, game_id=self.game_id)
        self.assertEqual(engine_mod._configured_elo, TEST_ELO + 100)


class TheBinaryItself(unittest.TestCase):
    """
    The only module allowed to find out there is no Stockfish.

    It answers `None` rather than raising, because a machine without one is not
    broken — Rau just declines the game — and a raise here would surface in
    whichever of the three callers happened to ask first.
    """

    def test_a_missing_binary_is_an_answer_and_not_an_exception(self):
        with patch.dict("os.environ", {binary.ENV_VAR: "/nonexistent/stockfish"}), \
                patch("shutil.which", lambda name: None), \
                patch.object(binary, "FALLBACKS", ("/nonexistent/stockfish",)):
            self.addCleanup(binary.forget)
            binary.forget()
            self.assertIsNone(binary.found(refresh=True))
        binary.forget()

    def test_availability_is_cheap_and_starts_nothing(self):
        """`available()` is called on hot paths, including from the websocket
        handler. It must never spawn a process to answer."""
        with patch("subprocess.run", side_effect=AssertionError("spawned a process")):
            engine_mod.available()


if __name__ == "__main__":
    unittest.main()

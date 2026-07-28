"""
The rules of chess as this table plays them, and the sentences it says when it
says no.

`board.py` is the only module in the package allowed to move a piece, so it is
the only one that can be wrong about whether a game is over. Most of that is
python-chess doing the work and does not need defending. What needs defending is
everything laid on top of the library:

**Which draws end a game and which ones merely offer to.** Stalemate,
insufficient material and the seventy-five-move rule are the arbiter stepping in;
threefold and fifty moves are a right the player holds and may decline to use.
The board honours that distinction — `_settle` asks the library with
`claim_draw=False` — and it is a real product decision rather than an accident of
the API. A board that quietly draws a game the moment a position repeats takes
away a perfectly good winning attempt, and nobody would ever be shown why. So the
tests here check both halves: that a claimable draw leaves the game running, and
that claiming it ends it.

**That a refusal is dialogue.** `session.py` hands `error` straight to
`player.table_talk` and Rau says it out loud across the table. `"Invalid move:
E2E9"` spoken by a text-to-speech voice is not a bug report, it is a person
having a stroke. So every refusal string in this module is asserted to read as
somebody talking: lowercase, a sentence, no identifiers, no punctuation fuss. The
`code` beside it is the part the client is allowed to be mechanical about.

Nothing here touches the network or Stockfish. Stockfish picks moves in this
game, but it never decides whether one is legal — that is this file's subject and
it is pure.

Run: python -m unittest tests.test_chess_board -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess  # noqa: E402

from rau.games.chess import board as board_mod  # noqa: E402
from rau.games.chess.board import (  # noqa: E402
    BLACK,
    PHASE_OVER,
    PHASE_PLAYING,
    RAU,
    USER,
    WHITE,
    ChessGame,
    IllegalMove,
)

#: The complete refusal vocabulary from the contract. A code outside this set is
#: a client that cannot branch on it, which is the whole reason codes exist
#: alongside the spoken line.
CODES = {
    "no_game",
    "not_your_turn",
    "illegal_move",
    "no_engine",
    "bad_square",
    "no_offer",
    "malformed",
}

#: Things that belong in a log line and never in a sentence said out loud.
NOT_DIALOGUE = ("_", "(", ")", "{", "}", "[", "]", "invalid", "error", "illegal", "traceback")

#: Every string `over_reason` is allowed to hold. `web/src/games/chess/meta.ts`
#: keys its result copy off these exactly, so a rewording here is a game that ends
#: with the raw reason printed at the user instead of a sentence.
REASONS = {
    "checkmate",
    "stalemate",
    "insufficient material",
    "fifty-move rule",
    "threefold repetition",
    "resignation",
    "draw agreed",
}

#: 1.e3 d5 2.Bb5+ — black to move and in check, from a real opening rather than a
#: constructed one, so the refusals below are the ones a beginner actually meets.
CHECKED = "rnbqkbnr/ppp1pppp/8/1B1p4/8/4P3/PPPP1PPP/RNBQK1NR b KQkq - 1 2"


def isolate_games(case: unittest.TestCase) -> Path:
    """
    Point `memories/games/` and `memories/games.json` at a throwaway directory.

    `memories/` on this machine holds a real chess position and a real running
    record of who has beaten whom. A test that starts a session writes over both
    within a second of importing. Registered as a cleanup so it unwinds even when
    the test fails, and it returns the directory so a test can look at what was
    written.
    """
    import rau.paths as paths_mod
    from rau.memory import store as memory_store

    tmp = Path(tempfile.mkdtemp(prefix="rau-chess-"))
    real_dir = paths_mod.GAMES_DIR
    real_file = paths_mod.GAMES_FILE
    real_diary = memory_store.append_diary
    real_trace = memory_store.append_trace
    paths_mod.GAMES_DIR = tmp / "games"
    paths_mod.GAMES_FILE = tmp / "games.json"
    # The diary is prose Rau reads back to himself later. A test run must not put
    # imaginary chess games into it.
    memory_store.append_diary = lambda *a, **k: tmp / "diary"
    memory_store.append_trace = lambda *a, **k: tmp / "trace"

    def restore() -> None:
        paths_mod.GAMES_DIR = real_dir
        paths_mod.GAMES_FILE = real_file
        memory_store.append_diary = real_diary
        memory_store.append_trace = real_trace
        shutil.rmtree(tmp, ignore_errors=True)

    case.addCleanup(restore)
    return tmp / "games"


def stub_the_performance(case: unittest.TestCase) -> List[str]:
    """
    Take Stockfish and the model half out of the session, leaving the lifecycle.

    `pump` is the daemon that starts a chess engine and then spends up to twenty
    seconds pretending to think about it; `player.refuse` is a provider call. A
    test about moves and files wants neither, and neither has an opinion about
    what is under test. Returns the list the refusal lines land in instead of
    being spoken.
    """
    from rau.games.chess import player, pump

    spoken: List[str] = []
    for module, name, replacement in (
        (pump, "ensure", lambda: None),
        (pump, "wake", lambda: None),
        (pump, "stop", lambda: None),
        (pump, "reset_for_game", lambda **kw: None),
        (player, "reset", lambda: None),
        (player, "refuse", spoken.append),
    ):
        patcher = patch.object(module, name, replacement)
        patcher.start()
        case.addCleanup(patcher.stop)
    return spoken


def at(fen: str, *, rau_color: str = BLACK) -> ChessGame:
    """
    A game standing in a given position.

    Playing sixty real moves to reach a fifty-move draw would make the test about
    the sixty moves. The position is dropped in instead; the move stack starts
    empty, which is exactly the situation the repetition tests deliberately do
    *not* use.
    """
    game = ChessGame(rau_color=rau_color)
    game.board = chess.Board(fen)
    return game


def run(game: ChessGame, *moves: str) -> str:
    """Play a run of `e2e4`-style moves, each by whoever is to move. Last SAN."""
    san = ""
    for move in moves:
        san = game.play(game.turn_seat(), move[:2], move[2:4], move[4:] or None)
    return san


def refusal(case: unittest.TestCase, call: Callable[[], Any]) -> IllegalMove:
    """Run something that must be refused and hand back the refusal itself."""
    with case.assertRaises(IllegalMove) as caught:
        call()
    return caught.exception


class Endings(unittest.TestCase):
    """Games the arbiter ends, with nobody having to ask."""

    def test_scholars_mate_ends_the_game_and_names_the_winner(self):
        """The commonest four-move mate, checked end to end.

        Result, winner and reason are three separate fields on the wire and the
        client shows all three. Getting the seat right matters most: Rau takes
        black by default, so the mating side here is the user, and a sign error
        would congratulate the wrong person.
        """
        game = ChessGame(rau_color=BLACK)
        self.assertEqual(
            run(game, "e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"), "Qxf7#"
        )
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.result, "1-0")
        self.assertEqual(game.winner, USER)
        self.assertEqual(game.over_reason, "checkmate")
        self.assertEqual(game.snapshot()["your_turn"], False)

    def test_the_same_mate_from_the_other_side_reads_one_nil_to_him(self):
        """`result` is derived from the winner's colour, never stored twice.

        Two fields that must agree are two fields that can disagree, so the
        derivation is checked from the side where a copy-paste would survive the
        previous test.
        """
        game = ChessGame(rau_color=WHITE)
        run(game, "e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7")
        self.assertEqual(game.winner, RAU)
        self.assertEqual(game.result, "1-0")

    def test_a_finished_game_refuses_everything_that_comes_after(self):
        """Nothing goes on a board that has been decided.

        A checkmated position still has legal-looking moves in it, and a client
        that lost the `game_over` event will happily send one. Every door is shut,
        not just the move door, and they all answer `no_game`.
        """
        game = ChessGame()
        run(game, "e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7")
        after: List[Callable[[], Any]] = [
            lambda: game.play(RAU, "b8", "c6"),
            lambda: game.resign(USER),
            lambda: game.offer_draw(USER),
            lambda: game.accept_draw(USER),
            lambda: game.decline_draw(USER),
            lambda: game.claim_draw(USER),
        ]
        for call in after:
            with self.subTest(call=call):
                self.assertEqual(refusal(self, call).code, "no_game")
        self.assertEqual(game.result, "1-0", "a refusal changed the outcome")

    def test_stalemate_is_a_draw_with_nobody_winning(self):
        """No moves and no check is half a point each, not a loss.

        `winner` must be None rather than the stalemating side; the UI reads
        `winner` to decide whose face to draw, and a draw shown as a win is the
        cruellest possible bug in a game he was losing.
        """
        game = at("7k/8/5QK1/8/8/8/8/8 w - - 0 1", rau_color=WHITE)
        self.assertEqual(run(game, "f6f7"), "Qf7")
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.result, "1/2-1/2")
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "stalemate")

    def test_taking_the_last_piece_draws_on_insufficient_material(self):
        """King against king cannot be won, so it ends the moment it arrives."""
        game = at("8/8/8/8/8/1k6/8/Kn6 w - - 0 1", rau_color=WHITE)
        self.assertEqual(run(game, "a1b1"), "Kxb1")
        self.assertEqual(game.result, "1/2-1/2")
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "insufficient material")

    def test_seventy_five_moves_ends_the_game_without_anybody_asking(self):
        """The arbiter's version of the fifty-move rule, which nobody may decline.

        The contract's vocabulary has no separate word for it, and it is right
        that it does not: at the table nobody cares which counter tripped, only
        that the game is a draw and roughly why. So it reports as the fifty-move
        rule, the same as the claimed version does.
        """
        game = at("8/8/8/4k3/8/8/4K3/7R w - - 149 100", rau_color=WHITE)
        self.assertEqual(run(game, "h1h2"), "Rh2")
        self.assertEqual(game.result, "1/2-1/2")
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "fifty-move rule")


    def test_the_reason_a_game_ended_comes_from_a_closed_vocabulary(self):
        """The client turns `over_reason` into a sentence by looking it up.

        `meta.ts` holds a table keyed on these strings and falls back to printing
        the reason itself when it misses, so a new termination spelled a new way
        does not crash anything — it just shows the user the internal wording. A
        closed set here is what keeps the two sides spelling it the same.
        """
        produced = set(board_mod._REASONS.values())  # noqa: SLF001 — the whole point
        self.assertTrue(
            produced <= REASONS, f"the board can say {produced - REASONS}"
        )
        for reason in ("resignation", "draw agreed"):
            with self.subTest(reason=reason):
                self.assertIn(reason, REASONS)


class ClaimableDraws(unittest.TestCase):
    """Draws that are a right rather than a verdict.

    This is the distinction the whole module is built around. A repeated
    position does not end a game; it puts a button on the screen. Somebody
    grinding a won endgame may repeat twice to gain time and has every reason not
    to claim, and a board that draws for them has taken the game away.
    """

    def shuffle(self) -> ChessGame:
        """Knights out and back twice, so the opening position stands for a third time.

        Eight plies rather than seven, which leaves the user to move: the claim
        button belongs to whoever is sitting there looking at it, and a
        repetition that arrives on Rau's turn is a different screen.
        """
        game = ChessGame()
        run(game, "g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1", "f6g8")
        return game

    def test_threefold_is_offered_and_not_imposed(self):
        """Repetition makes the draw claimable and leaves the game running."""
        game = self.shuffle()
        self.assertTrue(game.can_claim_draw())
        self.assertIsNone(game.result)
        self.assertEqual(game.phase, PHASE_PLAYING)
        view = game.snapshot()
        self.assertTrue(view["can_claim_draw"])
        self.assertIsNone(view["result"])
        self.assertTrue(view["your_turn"], "a claimable draw must not freeze the board")

    def test_a_game_can_be_played_on_out_of_a_claimable_repetition(self):
        """Declining to claim is done by moving, and it must be allowed."""
        game = self.shuffle()
        self.assertTrue(game.can_claim_draw())
        self.assertEqual(run(game, "e2e4"), "e4")
        self.assertIsNone(game.result)
        self.assertFalse(game.can_claim_draw(), "a new position is not a repetition")

    def test_claiming_the_threefold_draw_ends_the_game(self):
        """The other half of the same decision: asked for, it is granted."""
        game = self.shuffle()
        game.claim_draw(USER)
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.result, "1/2-1/2")
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "threefold repetition")

    def test_fifty_moves_is_claimable_and_the_claim_names_the_rule(self):
        """A hundred half-moves without a pawn or a capture, claimed not enforced.

        `over_reason` has to say which rule was used, because the two claimable
        draws look identical in the move list and the PGN header is generated
        from this string.
        """
        game = at("8/8/8/4k3/8/8/4K3/7R w - - 99 60", rau_color=WHITE)
        run(game, "h1h2")
        self.assertIsNone(game.result, "fifty moves is a right, not a verdict")
        self.assertTrue(game.can_claim_draw())
        game.claim_draw(USER)
        self.assertEqual(game.result, "1/2-1/2")
        self.assertEqual(game.over_reason, "fifty-move rule")

    def test_claiming_with_nothing_to_claim_is_refused(self):
        """A button pressed in a fresh position must not draw the game."""
        game = ChessGame()
        exc = refusal(self, lambda: game.claim_draw(USER))
        self.assertEqual(exc.code, "no_offer")
        self.assertIsNone(game.result)

    def test_claimability_is_recomputed_when_the_position_moves_on(self):
        """The cached answer is keyed to the ply, so it must not outlive it.

        `can_claim_draw` replays the move stack and the wire view asks for it on
        a hundred-millisecond heartbeat, so the answer is cached. A cache that
        forgets to expire would leave the claim button lit for the rest of the
        game.
        """
        game = self.shuffle()
        self.assertTrue(game.can_claim_draw())
        run(game, "d2d4")
        self.assertFalse(game.can_claim_draw())


class SpecialMoves(unittest.TestCase):
    """The four moves that are not one piece walking to one square."""

    def test_castling_is_a_two_square_king_move(self):
        """The client sends e1 and g1; nobody anywhere sends "O-O".

        The board is a grid of squares the user drags across. Castling has to
        arrive as the king's journey and come back as castling notation, or the
        rook never moves on screen.
        """
        game = ChessGame()
        self.assertEqual(
            run(game, "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "e1g1"), "O-O"
        )
        self.assertEqual(game.last_move, {"from": "e1", "to": "g1", "san": "O-O"})
        self.assertEqual(game.board.piece_at(chess.F1), chess.Piece(chess.ROOK, chess.WHITE))

    def test_en_passant_takes_the_pawn_that_just_passed(self):
        """A capture whose victim is not on the target square.

        Worth its own test because the naive implementation — move the piece,
        clear the destination — leaves the captured pawn standing.
        """
        game = ChessGame()
        self.assertEqual(run(game, "e2e4", "a7a6", "e4e5", "d7d5", "e5d6"), "exd6")
        self.assertIsNone(game.board.piece_at(chess.D5), "the passed pawn survived")
        self.assertEqual(game.board.piece_at(chess.D6), chess.Piece(chess.PAWN, chess.WHITE))

    def test_a_promotion_with_no_piece_named_is_a_queen(self):
        """Silence means a queen, because the client only asks when it is not one.

        Refusing a promotion for want of a field would mean a dragged pawn
        bouncing back off the last rank, which reads as a broken board rather
        than as a question.
        """
        game = at("7k/P7/8/8/8/8/8/K7 w - - 0 1", rau_color=WHITE)
        self.assertEqual(run(game, "a7a8"), "a8=Q+")
        self.assertEqual(game.board.piece_at(chess.A8), chess.Piece(chess.QUEEN, chess.WHITE))

    def test_underpromotion_is_honoured(self):
        """When a piece is named it is the piece that appears, queen or not."""
        for letter, kind in (("n", chess.KNIGHT), ("r", chess.ROOK), ("b", chess.BISHOP)):
            with self.subTest(promotion=letter):
                game = at("7k/P7/8/8/8/8/8/K7 w - - 0 1", rau_color=WHITE)
                game.play(RAU, "a7", "a8", letter)
                self.assertEqual(
                    game.board.piece_at(chess.A8), chess.Piece(kind, chess.WHITE)
                )

    def test_a_promotion_field_on_an_ordinary_move_is_ignored(self):
        """A stale field from the client must not turn a knight into a queen."""
        game = ChessGame()
        self.assertEqual(run(game, "e2e4q"), "e4")
        self.assertEqual(game.board.piece_at(chess.E4), chess.Piece(chess.PAWN, chess.WHITE))


class OffersAndResignation(unittest.TestCase):
    """The half of chess that is two people agreeing rather than the rules."""

    def test_resigning_hands_the_game_to_the_other_seat(self):
        """Resignation is invisible in the move list, so the seat is everything."""
        game = ChessGame(rau_color=BLACK)
        run(game, "e2e4", "e7e5")
        game.resign(USER)
        self.assertEqual(game.phase, PHASE_OVER)
        self.assertEqual(game.winner, RAU)
        self.assertEqual(game.result, "0-1", "he had black, so black won")
        self.assertEqual(game.over_reason, "resignation")

    def test_an_offer_shows_up_on_the_wire_with_who_made_it(self):
        """The client draws a different thing depending on which side offered."""
        game = ChessGame()
        game.offer_draw(USER)
        self.assertEqual(game.snapshot()["offer"], {"by": USER, "kind": "draw"})
        self.assertIsNone(game.result, "an offer is not a draw")

    def test_a_draw_offer_accepted_is_a_draw(self):
        game = ChessGame()
        game.offer_draw(USER)
        game.accept_draw(RAU)
        self.assertEqual(game.result, "1/2-1/2")
        self.assertIsNone(game.winner)
        self.assertEqual(game.over_reason, "draw agreed")
        self.assertIsNone(game.snapshot()["offer"], "a settled offer must be cleared")

    def test_a_declined_offer_leaves_the_game_exactly_where_it_was(self):
        game = ChessGame()
        run(game, "e2e4")
        game.offer_draw(RAU)
        game.decline_draw(USER)
        self.assertIsNone(game.offer)
        self.assertIsNone(game.result)
        self.assertEqual(game.turn_seat(), RAU)

    def test_offering_back_into_an_open_offer_is_agreement(self):
        """Two people both saying "draw?" are not two people waiting.

        Without this the pair deadlock: his offer stands, hers replaces it, and
        each is holding out for an acceptance the other has already effectively
        given.
        """
        game = ChessGame()
        game.offer_draw(USER)
        game.offer_draw(RAU)
        self.assertEqual(game.result, "1/2-1/2")
        self.assertEqual(game.over_reason, "draw agreed")

    def test_answering_an_offer_nobody_made_is_refused(self):
        """Accepting your own offer is the obvious way to draw a lost game."""
        game = ChessGame()
        self.assertEqual(refusal(self, lambda: game.accept_draw(USER)).code, "no_offer")
        self.assertEqual(refusal(self, lambda: game.decline_draw(USER)).code, "no_offer")
        game.offer_draw(USER)
        self.assertEqual(refusal(self, lambda: game.accept_draw(USER)).code, "no_offer")
        self.assertIsNone(game.result)

    def test_making_a_move_silently_answers_an_outstanding_offer(self):
        """Playing on is how a draw is declined over a real board.

        Nobody says "no thank you" and then moves. The offer has to be gone
        afterwards or it sits on screen for the rest of the game, and a stray
        `accept_draw` an hour later would draw a game that was long since a
        different conversation.
        """
        game = ChessGame()
        game.offer_draw(RAU)
        self.assertIsNotNone(game.offer)
        run(game, "e2e4")
        self.assertIsNone(game.offer)
        self.assertIsNone(game.snapshot()["offer"])
        self.assertEqual(refusal(self, lambda: game.accept_draw(USER)).code, "no_offer")


class Refusals(unittest.TestCase):
    """Being told no, in a code the client reads and a sentence he says."""

    def test_the_four_wrong_ways_to_move_are_told_apart(self):
        """Out of turn, their piece, an empty square, a square that is not one.

        Each is a different mistake and each gets a different sentence. Two of
        them share the `bad_square` code because the contract's vocabulary has
        exactly one code for a square that cannot be moved from — so the code is
        the client's coarse branch and the line is what tells the user which of
        the two happened.
        """
        game = ChessGame(rau_color=BLACK)
        out_of_turn = refusal(self, lambda: game.play(RAU, "e7", "e5"))
        theirs = refusal(self, lambda: game.play(USER, "e7", "e5"))
        empty = refusal(self, lambda: game.play(USER, "e4", "e5"))
        nonsense = refusal(self, lambda: game.play(USER, "e9", "e5"))

        self.assertEqual(out_of_turn.code, "not_your_turn")
        self.assertEqual(theirs.code, "illegal_move")
        self.assertEqual(empty.code, "bad_square")
        self.assertEqual(nonsense.code, "bad_square")

        messages = [out_of_turn.message, theirs.message, empty.message, nonsense.message]
        self.assertEqual(len(set(messages)), 4, "four mistakes, four things to say")
        self.assertIn("e4", empty.message, "say which square was empty")

    def test_a_move_that_would_hang_the_king_says_so(self):
        """The commonest refusal in real play deserves the clearest line."""
        game = at(CHECKED, rau_color=WHITE)
        exc = refusal(self, lambda: game.play(USER, "a7", "a6"))
        self.assertEqual(exc.code, "illegal_move")
        self.assertIn("check", exc.message)

    def test_being_in_check_is_explained_rather_than_just_denied(self):
        """A move that is not even pseudo-legal, played while in check.

        The generic "that one doesn't go there" is true and useless here — the
        reason is the check, and a beginner who cannot see it is exactly the
        person being refused.
        """
        game = at(CHECKED, rau_color=WHITE)
        exc = refusal(self, lambda: game.play(USER, "a7", "a4"))
        self.assertEqual(exc.code, "illegal_move")
        self.assertIn("check", exc.message)

    def test_a_refused_move_leaves_the_position_untouched(self):
        """Refusals raise before anything is pushed, and nothing is half-applied."""
        game = ChessGame()
        run(game, "e2e4", "e7e5")
        before = game.board.fen()
        moves = list(game.moves)
        last = dict(game.last_move or {})
        for call in (
            lambda: game.play(USER, "e4", "e6"),
            lambda: game.play(RAU, "e2", "e4"),
            lambda: game.play(USER, "zz", "e4"),
        ):
            with self.subTest(call=call):
                refusal(self, call)
        self.assertEqual(game.board.fen(), before)
        self.assertEqual(game.moves, moves)
        self.assertEqual(game.last_move, last)
        self.assertEqual(len(game.log), len(moves) + 1, "a refusal is not a log line")

    def test_every_refusal_carries_a_code_from_the_contract(self):
        """An undocumented code is a client that cannot branch on it."""
        for label, message, code in self.every_refusal():
            with self.subTest(refusal=label):
                self.assertIn(code, CODES, f"{label} answered with {code!r}")
                self.assertTrue(message.strip(), f"{label} refused without saying why")

    def test_every_refusal_reads_as_somebody_speaking(self):
        """These strings go to a text-to-speech voice, so their register is load-bearing.

        Rau says the refusal out loud across the table. That rules out capitals,
        identifiers, brackets and the word "invalid" — anything that sounds like
        a program apologising rather than a person disagreeing.
        """
        for label, message, _code in self.every_refusal():
            with self.subTest(refusal=label):
                self.assertEqual(
                    message, message.lower(), f"{label} shouts: {message!r}"
                )
                self.assertTrue(
                    message[0].isalpha(), f"{label} does not start on a word: {message!r}"
                )
                self.assertIn(" ", message, f"{label} is a token, not a sentence")
                self.assertFalse(
                    message.endswith("."), f"{label} ends in punctuation fuss"
                )
                for banned in NOT_DIALOGUE:
                    self.assertNotIn(
                        banned, message, f"{label} says {banned!r} out loud"
                    )

    def every_refusal(self) -> List[Tuple[str, str, str]]:
        """One of each refusal the board can produce, as (label, line, code).

        Gathered by provoking them rather than by listing them, so a refusal
        added later without a spoken line fails these tests instead of quietly
        going out to the voice.

        `malformed` is missing on purpose: it is raised by the session, not the
        board, and it is the one refusal Rau never says out loud — a client
        sending nonsense is nobody at the table's fault. `RefusalWireShape`
        covers it.
        """
        found: List[Tuple[str, str, str]] = []

        def take(label: str, call: Callable[[], Any]) -> None:
            exc = refusal(self, call)
            found.append((label, exc.message, exc.code))

        game = ChessGame(rau_color=BLACK)
        take("out of turn", lambda: game.play(RAU, "e7", "e5"))
        take("their piece", lambda: game.play(USER, "e7", "e5"))
        take("empty square", lambda: game.play(USER, "e4", "e5"))
        take("not a square", lambda: game.play(USER, "e9", "e5"))
        take("does not go there", lambda: game.play(USER, "e2", "e5"))
        take("no offer to accept", lambda: game.accept_draw(USER))
        take("no offer to decline", lambda: game.decline_draw(USER))
        take("nothing to claim", lambda: game.claim_draw(USER))

        checked = at(CHECKED, rau_color=WHITE)
        take("into check", lambda: checked.play(USER, "a7", "a6"))
        take("already in check", lambda: checked.play(USER, "a7", "a4"))

        over = ChessGame()
        run(over, "e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7")
        take("game already over", lambda: over.play(RAU, "b8", "c6"))
        return found


class RefusalWireShape(unittest.TestCase):
    """What a refused move actually looks like coming back out of the session.

    The board raises; the session is what turns that into the three keys the
    client reads. Stockfish and the model half are stubbed out — this is about
    the envelope, and neither of them has an opinion about it.
    """

    def setUp(self) -> None:
        isolate_games(self)
        from rau.games.chess import session

        self.session = session
        # The refusal is normally spoken aloud. Collecting it instead keeps a
        # provider out of the test without hiding the string, which is asserted.
        self.spoken = stub_the_performance(self)
        # Registered after the patchers so it runs before them: taking the board
        # away must not be the one call that reaches the real pump.
        self.addCleanup(lambda: session.end("test over"))
        session.start(rau_color="black")

    def send(self, move: Dict[str, Any]) -> Dict[str, Any]:
        return self.session.apply_move(USER, move)

    def test_a_refusal_is_ok_false_an_error_and_a_code_and_nothing_else(self):
        """Three keys exactly. There is deliberately no legal-move list here.

        Kittens sends the legal moves back with a refusal. Chess does not, and it
        is not an oversight: the user chose a board with no move hints, and a
        refusal quietly carrying every legal move would hand the client the
        hint list through the back door.
        """
        answer = self.send({"move": "move", "from": "e2", "to": "e5"})
        self.assertEqual(set(answer), {"ok", "error", "code"})
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["code"], "illegal_move")
        self.assertIsInstance(answer["error"], str)

    def test_an_accepted_move_comes_back_with_the_whole_board(self):
        answer = self.send({"move": "move", "from": "e2", "to": "e4"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["state"]["moves"], ["e4"])
        self.assertNotIn("error", answer)

    def test_a_move_the_client_invented_is_malformed_and_is_not_said_out_loud(self):
        """A broken client is not a wrong move, so nobody is told off for it."""
        answer = self.send({"move": "wobble"})
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["code"], "malformed")
        self.assertEqual(self.spoken, [], "a client bug must not become dialogue")

    def test_a_refused_move_is_spoken_and_the_line_is_the_error_string(self):
        """One string, two destinations: the client's toast and Rau's mouth."""
        answer = self.send({"move": "move", "from": "e9", "to": "e4"})
        self.assertEqual(answer["code"], "bad_square")
        self.assertEqual(self.spoken, [answer["error"]])

    def test_moving_with_no_board_out_answers_no_game(self):
        self.session.end("cleared")
        answer = self.send({"move": "move", "from": "e2", "to": "e4"})
        self.assertEqual(answer["code"], "no_game")
        self.assertEqual(answer["error"], answer["error"].lower())


if __name__ == "__main__":
    unittest.main()

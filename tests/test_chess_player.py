"""
The performance layer — the pause, the claw, and the line across the table.

This is the file that defends the inversion. In Exploding Kittens the player half
picks the move, so `kittens/player.py` has to carry a retry, a correction prompt
and a fallback ladder, because a model that chooses will eventually choose
something impossible. Here Stockfish chose. There is nothing to recover from, and
the machinery that would recover from it must never be reintroduced — a fallback
in this file would mean Rau's model half quietly picking moves again, which is
the one thing the whole feature exists to prevent.

So the first section of this file is structural. It reads `player.py` as source
and asserts things about its shape rather than its behaviour, because the
regression being guarded is a helpful contributor adding a `legal_moves` lookup
"just in case", and that lands as a passing test suite and a silently different
product.

The rest is timing and speech: the hover script arriving as it plays, a move that
never lands because the board went away mid-think, a refusal said once rather
than once per click, and banter that stays quiet when it would be his second
voice. Every delay used here is a tenth of a second — a suite that sits through
real think-times is a suite nobody runs.

No provider is reached. `player._ask` and `banter._ask` are replaced everywhere,
and the pump's turn thread is a no-op so no Stockfish is opened.

Run: python -m unittest tests.test_chess_player -v
"""
from __future__ import annotations

import ast
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.chess import banter, journal, player, session  # noqa: E402
from rau.games.chess import view as view_mod  # noqa: E402
from rau.games.chess.board import PHASE_PLAYING, RAU, USER, ChessGame  # noqa: E402
from rau.games.chess.engine import MoveChoice  # noqa: E402
from rau.games.chess.timing import HoverStep, ThinkPlan  # noqa: E402
from tests.test_chess_session import (  # noqa: E402
    Recorder,
    isolate_memory,
    park_the_pump,
    quicken_the_pump,
    quiesce,
    silence_the_engine,
    silence_the_providers,
)

PLAYER_SOURCE = Path(player.__file__).read_text(encoding="utf-8")
PLAYER_TREE = ast.parse(PLAYER_SOURCE)


def function_named(name: str) -> ast.FunctionDef:
    return next(
        node
        for node in PLAYER_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def choice_for(board: chess.Board, move: chess.Move, **overrides: Any) -> MoveChoice:
    """A `MoveChoice` for a move that is already legal, the way the engine hands one over."""
    piece = board.piece_at(move.from_square)
    fields: Dict[str, Any] = {
        "move": move,
        "san": board.san(move),
        "bucket": "level",
        "swing": 0.0,
        "is_capture": board.is_capture(move),
        "is_check": board.gives_check(move),
        "is_castle": board.is_castling(move),
        "is_promotion": move.promotion is not None,
        "piece": piece.symbol().upper() if piece else "",
    }
    fields.update(overrides)
    return MoveChoice(**fields)


# ------------------------------------------------------------------ structure


class TheInversion(unittest.TestCase):
    """
    `player.py` performs a move. It does not choose one, check one, or retry one.

    Every assertion here is about the shape of the module, because a behavioural
    test cannot tell the difference between "Stockfish picked this move" and
    "Stockfish picked this move and the player half agreed with it". Only the
    absence of the machinery can, and absence is what is asserted.
    """

    def test_the_player_half_never_asks_what_is_legal(self):
        names = {
            node.attr for node in ast.walk(PLAYER_TREE) if isinstance(node, ast.Attribute)
        } | {node.id for node in ast.walk(PLAYER_TREE) if isinstance(node, ast.Name)}
        for forbidden in (
            "legal_moves",
            "generate_legal_moves",
            "pseudo_legal_moves",
            "is_legal",
        ):
            self.assertNotIn(
                forbidden,
                names,
                f"player.py consults {forbidden} — the choosing is Stockfish's",
            )

    def test_the_module_never_imports_the_engine_or_a_move_generator(self):
        imported = set()
        for node in ast.walk(PLAYER_TREE):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        self.assertNotIn("rau.games.chess.engine", imported)
        self.assertNotIn("rau.games.chess.timing", imported)

    def test_there_is_exactly_one_place_a_move_reaches_the_board(self):
        calls = [
            node
            for node in ast.walk(PLAYER_TREE)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "apply_move"
        ]
        self.assertEqual(
            len(calls),
            1,
            "more than one call to apply_move is a retry ladder growing back",
        )

    def test_perform_move_has_no_loop_and_no_recovery_around_the_move(self):
        """
        A retry is a loop or a `try` in this function and nothing else. `_run_delay`
        is allowed both — it walks the hover script and has to unwind the claw —
        so the assertion is scoped to the function that actually plays the move.
        """
        fn = function_named("perform_move")
        offenders = [
            type(node).__name__
            for node in ast.walk(fn)
            if isinstance(node, (ast.For, ast.While, ast.Try, ast.ExceptHandler))
        ]
        self.assertEqual(offenders, [], "perform_move grew a retry")

    def test_the_payload_is_built_from_the_move_it_was_handed_and_nothing_else(self):
        """
        `_payload` may read `choice.move` and the `chess` module's square names.
        Anything else in there — a board, a session lookup, a legality check — is
        the player half deciding something.
        """
        fn = function_named("_payload")
        roots = {
            node.id
            for statement in fn.body
            for node in ast.walk(statement)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        self.assertEqual(roots, {"choice", "move", "chess"})

    def test_the_docstring_still_says_why_the_machinery_is_absent(self):
        """
        The absence is only self-documenting while it is documented. If this
        fails, somebody rewrote the module docstring and the next contributor has
        no idea why there is no fallback here.
        """
        docstring = ast.get_docstring(PLAYER_TREE) or ""
        self.assertIn("fallback", docstring)
        self.assertIn("Stockfish has already picked", docstring)


class TheMoveHeIsHanded(unittest.TestCase):
    """The move that lands is the move Stockfish chose, square for square."""

    def test_every_legal_move_survives_the_trip_through_the_payload(self):
        board = chess.Board()
        for move in board.legal_moves:
            payload = player._payload(choice_for(board, move))  # noqa: SLF001
            self.assertEqual(payload["move"], "move")
            self.assertEqual(payload["from"], chess.square_name(move.from_square))
            self.assertEqual(payload["to"], chess.square_name(move.to_square))
            self.assertIsNone(payload["promotion"])
            rebuilt = chess.Move(
                chess.parse_square(payload["from"]), chess.parse_square(payload["to"])
            )
            self.assertEqual(rebuilt, move)

    def test_an_underpromotion_is_not_quietly_turned_into_a_queen(self):
        board = chess.Board("8/P6k/8/8/8/8/8/7K w - - 0 1")
        for symbol, piece in (("q", chess.QUEEN), ("n", chess.KNIGHT), ("r", chess.ROOK)):
            move = chess.Move(chess.A7, chess.A8, promotion=piece)
            payload = player._payload(choice_for(board, move))  # noqa: SLF001
            self.assertEqual(payload["promotion"], symbol)


class PerformanceCase(unittest.TestCase):
    """A live board, a silenced pump, and no model anywhere behind it."""

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_engine(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)

    def board(self, colour: str = "white") -> ChessGame:
        """White by default: `perform_move` needs it to be his turn."""
        session.start(rau_color=colour)
        game = session.current()
        assert game is not None
        return game

    def plan(self, delay: float, *hovers: HoverStep) -> ThinkPlan:
        return ThinkPlan(delay=delay, hovers=list(hovers))


class TheHoverScript(PerformanceCase):
    """
    The claw is the only part of the pause the browser can see happening, so
    every step of it has to reach the socket while it is still true.
    """

    def test_the_thinking_phase_is_not_on_the_board_until_he_starts(self):
        game = self.board()
        view = view_mod.browser_view(game)
        self.assertEqual(view["phase"], PHASE_PLAYING)
        self.assertIsNone(view["thinking"])
        self.assertFalse(player.thinking_on(game))

    def test_the_script_is_broadcast_as_it_plays_and_the_move_lands_after_it(self):
        rec = Recorder(self, "game_state")
        game = self.board()
        move = chess.Move(chess.E2, chess.E4)
        choice = choice_for(game.board, move)
        plan = self.plan(0.6, HoverStep("g1", 0.2), HoverStep("e2", 0.2))

        began = time.monotonic()
        player.perform_move(game, choice, plan)
        elapsed = time.monotonic() - began

        self.assertGreaterEqual(
            elapsed, plan.delay - 0.05, "he played before he finished thinking"
        )
        self.assertEqual(game.moves, ["e4"])

        frames = [e["state"] for e in rec.of("game_state")]
        self.assertTrue(
            any(f["phase"] == "thinking" for f in frames),
            "the page was never told he was thinking",
        )
        hovers = [f["thinking"]["hover"] for f in frames if f["thinking"] is not None]
        squeezed = [h for i, h in enumerate(hovers) if i == 0 or h != hovers[i - 1]]
        self.assertEqual(
            squeezed,
            [None, "g1", "e2"],
            "the claw did not walk the script it was handed",
        )

    def test_the_move_reaches_the_page_only_after_the_delay(self):
        rec = Recorder(self, "game_state")
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.D2, chess.D4))
        plan = self.plan(0.5, HoverStep("d2", 0.3))

        began = time.time()
        player.perform_move(game, choice, plan)

        landed = [e for e in rec.of("game_state") if e["state"]["moves"] == ["d4"]]
        self.assertTrue(landed, "the move never reached the page at all")
        self.assertGreaterEqual(
            landed[0]["ts"] - began,
            plan.delay - 0.05,
            "a frame carrying the move went out before he had finished pausing",
        )

    def test_the_claw_is_put_away_once_the_move_is_made(self):
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.G1, chess.F3))
        player.perform_move(game, choice, self.plan(0.2, HoverStep("g1", 0.1)))
        self.assertFalse(player.thinking_on(game))
        self.assertIsNone(player.current_hover())
        self.assertEqual(view_mod.browser_view(game)["phase"], PHASE_PLAYING)

    def test_thinking_belongs_to_this_game_and_not_to_the_next_one(self):
        game = self.board()
        other = ChessGame(rau_color="white")
        started = threading.Event()

        def watch() -> None:
            deadline = time.time() + 3
            while time.time() < deadline and not player.thinking_on(game):
                time.sleep(0.01)
            started.set()

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        worker = threading.Thread(
            target=player.perform_move,
            args=(
                game,
                choice_for(game.board, chess.Move(chess.E2, chess.E4)),
                self.plan(0.6, HoverStep("e2", 0.5)),
            ),
            daemon=True,
        )
        worker.start()
        started.wait(3)
        self.assertTrue(player.thinking_on(game))
        self.assertFalse(player.thinking_on(other), "the stare leaked onto another board")
        worker.join(3)


class AbandonedMidThink(PerformanceCase):
    """
    Twenty seconds of pause is twenty seconds in which the game can end.

    A move that lands on a board the user resigned at second nineteen is the one
    failure this whole delay is arranged around, and it is invisible in testing
    unless somebody sits there and resigns at the right moment. So it is done
    here, on purpose, every run.
    """

    def test_a_board_swept_away_mid_think_never_receives_the_move(self):
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4))
        worker = threading.Thread(
            target=player.perform_move,
            args=(game, choice, self.plan(3.0, HoverStep("e2", 2.5))),
            daemon=True,
        )
        worker.start()
        time.sleep(0.3)
        session.end("they walked away")
        worker.join(3)
        self.assertFalse(worker.is_alive(), "the think never noticed the board had gone")
        self.assertEqual(game.moves, [], "a move landed on a game that was over")
        self.assertEqual(game.board.fen(), chess.Board().fen())
        self.assertIsNone(player.current_hover())

    def test_a_game_that_ended_mid_think_never_receives_the_move(self):
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4))
        worker = threading.Thread(
            target=player.perform_move,
            args=(game, choice, self.plan(3.0, HoverStep("e2", 2.5))),
            daemon=True,
        )
        worker.start()
        time.sleep(0.3)
        session.apply_move(USER, {"move": "resign"})
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(game.moves, [])
        self.assertEqual(game.over_reason, "resignation")

    def test_a_board_replaced_mid_think_does_not_inherit_the_move(self):
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4))
        worker = threading.Thread(
            target=player.perform_move,
            args=(game, choice, self.plan(3.0, HoverStep("e2", 2.5))),
            daemon=True,
        )
        worker.start()
        time.sleep(0.3)
        session.start(rau_color="white")  # a second board, set up over the first
        worker.join(3)
        fresh = session.current()
        assert fresh is not None
        self.assertNotEqual(fresh.game_id, game.game_id)
        self.assertEqual(fresh.moves, [], "the old think played onto the new board")
        self.assertEqual(game.moves, [])


class NoSecondAttempt(PerformanceCase):
    """A refused move is surfaced, never played again a different way."""

    def test_a_refusal_from_the_board_is_shouted_about_rather_than_retried(self):
        rec = Recorder(self, "game_error")
        game = self.board()
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4))
        refusal = {"ok": False, "error": "it's my move", "code": "not_your_turn"}
        with patch.object(session, "apply_move", return_value=refusal) as applied:
            player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(applied.call_count, 1, "he tried again after being refused")
        self.assertEqual(len(rec.of("game_error")), 1)
        self.assertIn("it's my move", rec.of("game_error")[0]["error"])
        self.assertEqual(rec.of("game_error")[0]["game"], "chess")

    def test_the_move_handed_over_is_the_move_that_reaches_the_board(self):
        game = self.board()
        move = chess.Move(chess.B1, chess.C3)
        choice = choice_for(game.board, move)
        with patch.object(
            session, "apply_move", return_value={"ok": True, "state": {}}
        ) as applied:
            player.perform_move(game, choice, self.plan(0.15, HoverStep("b1", 0.1)))
        applied.assert_called_once_with(
            RAU, {"move": "move", "from": "b1", "to": "c3", "promotion": None}
        )


class Refusals(PerformanceCase):
    """
    A piece that snaps back in silence reads as a broken board rather than as him
    saying no. So the refusal is spoken — and spoken once, because a user
    clicking at a pinned knight deserves one answer, not one per click.
    """

    def setUp(self) -> None:
        super().setUp()
        self.spoken: List[str] = []
        control = patch("rau.state.push_control", self.spoken.append)
        control.start()
        self.addCleanup(control.stop)
        journal.clear()
        player.reset()

    def spoken_lines(self) -> List[str]:
        return [c["text"] for c in self.spoken if c.get("action") == "speak"]

    def test_a_refusal_goes_to_the_bubble_the_journal_and_the_speaker(self):
        rec = Recorder(self, "chat_done")
        player.refuse("can't — that leaves your king in check")
        self.assertEqual(self.spoken_lines(), ["can't — that leaves your king in check"])
        self.assertIn("that leaves your king in check", journal.tail())
        self.assertEqual(
            [e["text"] for e in rec.of("chat_done")],
            ["can't — that leaves your king in check"],
        )

    def test_a_second_refusal_inside_the_cooldown_is_not_said_twice(self):
        player.refuse("can't — that one doesn't go there")
        player.refuse("can't — that one doesn't go there")
        player.refuse("wrong colour, that one's mine")
        self.assertEqual(
            self.spoken_lines(),
            ["can't — that one doesn't go there"],
            "he lectured them once per click",
        )

    def test_a_refusal_after_the_cooldown_is_said_again(self):
        with patch.object(player, "REFUSAL_GAP_SEC", 0.05):
            player.refuse("can't — that one doesn't go there")
            time.sleep(0.08)
            player.refuse("you're in check, you have to deal with that")
        self.assertEqual(len(self.spoken_lines()), 2)

    def test_an_empty_refusal_is_not_a_line(self):
        player.refuse("   ")
        self.assertEqual(self.spoken_lines(), [])

    def test_the_boards_own_refusal_reaches_him_through_the_session(self):
        """End to end: an illegal move from the browser is a thing he says."""
        self.board(colour="black")  # the user has white and opens
        result = session.apply_move(USER, {"move": "move", "from": "e2", "to": "e5"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.spoken_lines(), [result["error"]])

    def test_a_malformed_move_is_a_broken_client_and_not_worth_saying(self):
        self.board(colour="black")
        result = session.apply_move(USER, {"move": "flip_the_board"})
        self.assertEqual(result["code"], "malformed")
        self.assertEqual(self.spoken_lines(), [], "he blamed them for a client bug")


class TheLineAfterTheMove(PerformanceCase):
    """He is asked for a line only once the move is on the board."""

    def setUp(self) -> None:
        super().setUp()
        self.said: List[str] = []
        talk = patch.object(player, "table_talk", self.said.append)
        talk.start()
        self.addCleanup(talk.stop)

    def test_skip_means_he_says_nothing(self):
        game = self.board()
        player._ask = lambda prompt: "SKIP"  # noqa: SLF001
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4), swing=2.0)
        player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(self.said, [])

    def test_a_loud_move_gets_a_line_and_it_is_one_line(self):
        game = self.board()
        player._ask = lambda prompt: '"there it is.\nAnd here is why."'  # noqa: SLF001
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4), swing=2.0)
        player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(self.said, ["there it is."])

    def test_he_is_only_asked_once_the_move_is_already_on_the_board(self):
        game = self.board()
        seen: List[List[str]] = []

        def ask(prompt: str) -> str:
            seen.append(list(game.moves))
            return "SKIP"

        player._ask = ask  # noqa: SLF001
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4), swing=2.0)
        player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(seen, [["e4"]], "he was asked about a move he had not made")

    def test_no_number_from_the_evaluation_reaches_the_prompt(self):
        """
        The read he is handed is bucket, swing-in-English, material and stage. A
        centipawn arriving here is a Rau who can read his own evaluation back
        across the table.
        """
        game = self.board()
        session.note_read(SimpleNamespace(bucket="better", swing=1.7))
        read = view_mod.coarse_read(game, session.last_read())
        self.assertIn("you are better here", read)
        self.assertNotIn("1.7", read)
        self.assertNotIn("swing", read.lower())
        self.assertNotIn("cp", read.lower().split())

    def test_check_is_announced_even_when_the_model_had_nothing(self):
        """Announcing check is a courtesy of the game, not banter — no provider needed."""
        game = self.board()

        def dead(prompt: str) -> str:
            raise RuntimeError("provider down")

        player._ask = dead  # noqa: SLF001
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4))
        choice = MoveChoice(**{**choice.__dict__, "is_check": True})
        player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(len(self.said), 1)
        self.assertIn("check", self.said[0].lower())

    def test_a_line_that_arrives_after_the_board_is_gone_is_dropped(self):
        game = self.board()

        def slow(prompt: str) -> str:
            session.end("they walked away")
            return "still your move."

        player._ask = slow  # noqa: SLF001
        choice = choice_for(game.board, chess.Move(chess.E2, chess.E4), swing=2.0)
        player.perform_move(game, choice, self.plan(0.15, HoverStep("e2", 0.1)))
        self.assertEqual(self.said, [])


# --------------------------------------------------------------------- banter


def wait_for_banter(limit: float = 5.0) -> None:
    """Block until the in-flight line has landed, or give up on it."""
    deadline = time.time() + limit
    while banter.busy().is_set() and time.time() < deadline:
        time.sleep(0.01)


class BanterCase(PerformanceCase):
    """
    A live board with Rau on white, his move already played, the user on the
    clock — which is the only state `consider` will speak in.

    The pump looks at this board on its own schedule and would race every
    assertion below over the same cooldowns, so it is put away first and every
    move here is pushed straight onto the game object rather than through
    `session.apply_move`, which would start it up again.
    """

    def setUp(self) -> None:
        super().setUp()
        self.said: List[str] = []
        talk = patch.object(player, "table_talk", self.said.append)
        talk.start()
        self.addCleanup(talk.stop)

        self.game = self.board(colour="white")
        # Put the pump away and wait for the thread rather than for a couple of
        # poll intervals: it calls `consider` too, over these same cooldowns, and
        # a tick still in flight when `reset` lands below is the one thing that
        # would make this class flap.
        park_the_pump()
        wait_for_banter()
        banter.reset()
        player.reset()
        self.addCleanup(wait_for_banter)

    def answer(self, text: str) -> None:
        banter._ask = lambda prompt: text  # noqa: SLF001

    def rau_moved(self, frm: str, to: str, *, swing: float = 2.0) -> None:
        """He plays, the read updates, and the user is on the clock."""
        session.note_read(SimpleNamespace(bucket="better", swing=swing))
        self.game.play(RAU, frm, to)

    def look(self, **kwargs: Any) -> None:
        """One pump tick's worth of looking at the board."""
        banter.consider(self.game, **kwargs)
        wait_for_banter()


class WhenHeSpeaks(BanterCase):
    def test_a_swing_in_his_favour_earns_a_line(self):
        self.answer("that was careless of you.")
        self.look()  # the first look only takes the fingerprint
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, ["that was careless of you."])

    def test_skip_produces_no_speech_at_all(self):
        self.answer("SKIP")
        self.look()
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, [])

    def test_arriving_mid_game_is_not_something_that_just_happened(self):
        self.answer("welcome back.")
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, [], "he reacted to a move made before he looked")


class WhenHeStaysQuiet(BanterCase):
    def test_he_never_speaks_when_it_is_his_own_turn(self):
        self.answer("my move, and I like it.")
        self.look()
        self.rau_moved("e2", "e4")
        self.game.play(USER, "e7", "e5")  # back to him
        self.look()
        self.assertEqual(self.said, [], "he talked over his own move")

    def test_he_never_speaks_while_a_move_of_his_is_in_flight(self):
        self.answer("thinking out loud.")
        self.look()
        self.rau_moved("e2", "e4")
        self.look(thinking=True)
        self.assertEqual(self.said, [])

    def test_he_never_speaks_while_his_own_move_line_is_still_going_out(self):
        """Two lines about one move is a stutter, and his move line is the better one."""
        self.answer("and another thing.")
        self.look()
        self.rau_moved("e2", "e4")
        player.speaking().set()
        self.addCleanup(player.speaking().clear)
        self.look()
        self.assertEqual(self.said, [])

    def test_a_move_line_he_just_said_holds_the_next_one_back(self):
        self.answer("piling on.")
        self.look()
        self.rau_moved("e2", "e4")
        with player._lock:  # noqa: SLF001 — standing in for a line just delivered
            player._spoke_at = time.monotonic()  # noqa: SLF001
        self.look()
        self.assertEqual(self.said, [])

    def test_the_cooldown_floors_the_rate(self):
        self.answer("one.")
        self.look()
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, ["one."])
        # `table_talk` is stubbed here, so his own cooldown never moved — the
        # only thing holding the second line back is banter's own floor.
        self.game.play(USER, "e7", "e5")
        self.rau_moved("g1", "f3")
        self.look()
        self.assertEqual(self.said, ["one."], "he said two things in twenty seconds")

    def test_a_declined_line_still_costs_a_wait(self):
        """A dead provider or a quiet board must not become a call every tick."""
        self.answer("SKIP")
        self.look()
        self.rau_moved("e2", "e4")
        began = time.monotonic()
        self.look()
        self.assertGreaterEqual(banter._next_ok_at, began + banter.SKIP_GAP_SEC - 0.5)  # noqa: SLF001

    def test_a_real_reply_of_his_holds_the_next_line_back(self):
        self.answer("I would have said something.")
        self.look()
        banter.note_user_chat()
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, [])

    def test_nothing_is_said_once_the_game_is_over(self):
        self.answer("too late.")
        self.look()
        self.rau_moved("e2", "e4")
        self.game.resign(USER)
        self.look()
        self.assertEqual(self.said, [])

    def test_a_line_that_arrives_after_the_board_is_gone_is_dropped(self):
        def slow(prompt: str) -> str:
            session.end("test over")
            return "still your move."

        banter._ask = slow  # noqa: SLF001
        self.look()
        self.rau_moved("e2", "e4")
        self.look()
        self.assertEqual(self.said, [])


class TheIdleProd(BanterCase):
    def test_a_move_sat_on_for_a_long_time_earns_a_needle(self):
        # A quiet move first, so nothing else is worth remarking on and the only
        # thing that can make him speak on the third look is the wait itself.
        self.answer("any day now.")
        self.look()
        self.rau_moved("e2", "e4", swing=0.0)
        self.look()
        self.assertEqual(self.said, [])
        banter._turn_since = time.monotonic() - banter.IDLE_PROD_SEC - 1  # noqa: SLF001
        self.look()
        self.assertEqual(self.said, ["any day now."])

    def test_a_move_sat_on_briefly_does_not(self):
        self.answer("any day now.")
        self.look()
        self.rau_moved("e2", "e4", swing=0.0)
        self.look()
        banter._turn_since = time.monotonic() - 1  # noqa: SLF001
        self.look()
        self.assertEqual(self.said, [])


if __name__ == "__main__":
    unittest.main()

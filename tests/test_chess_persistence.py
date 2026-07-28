"""
What survives the process dying, and what one game is allowed to do to another's
record.

A half-finished hand of Exploding Kittens is worth nothing after a restart — the
state that matters is hidden and dealing again costs nothing. A half-finished
chess position is the entire game. Somebody forty moves into a good one, whose
Mac decided to install an update, has lost something real, and there is no way to
apologise for it afterwards. So this file is unusually paranoid about three
things.

**That the saved file is the position and not a photograph of it.** A FEN is the
pieces minus their history, and two rules of chess live entirely in that history:
threefold repetition and the fifty-move claim. Restore from a FEN and a game that
was one repetition from a claimable draw comes back unable to claim it, silently,
with the button simply not there. `resume()` replays the SAN list for exactly
this reason, and the test that defends it also shows what a FEN-only restore
would have answered — the two disagree, which is the whole point.

**That a bad file is a missing file and never an exception.** `resume()` runs on
the boot path. A truncated JSON document, a move list from a version of the code
that spelt something differently, a game that had already ended before the crash
— each of them has to end with Rau sitting at an empty table rather than with a
runtime that will not start.

**That `memories/games.json` belongs to two games now.** `kittens/session.py`
used to write `{"kittens": record}` over the whole document, which was harmless
while it was the only game in the house and became silent data loss the day chess
arrived: every finished hand of kittens erased the chess record, elo included,
and every finished chess game would have erased the kittens one. That bug is
named in the contract and it is the kind that nobody notices for a month, so it
gets an explicit test in both directions.

Every test here points the module-level paths at a temporary directory first.
`memories/` on this machine holds a real game and a real record of who has been
winning, and this file's whole subject is writing over things.

Run: python -m unittest tests.test_chess_persistence -v
"""
from __future__ import annotations

import json
import sys
import time
import types
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess  # noqa: E402

from rau.games.chess import board as board_mod  # noqa: E402
from rau.games.chess.board import (  # noqa: E402
    BLACK,
    RAU,
    USER,
    WHITE,
    ChessGame,
)
from tests.test_chess_board import (  # noqa: E402
    at,
    isolate_games,
    run,
    stub_the_performance,
)

#: The contract fixes this. Anything extra is state the client never asked for
#: being smuggled through the boot path; anything missing is a game that comes
#: back wrong.
SAVED_KEYS = {"fen", "moves", "rau_color", "started_at", "elo", "game_id"}

#: The four moves of Scholar's Mate, as the client sends them.
SCHOLARS = ("e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7")


def saved(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SavedPosition(unittest.TestCase):
    """`memories/games/chess_current.json`, written after every move."""

    def setUp(self) -> None:
        self.games_dir = isolate_games(self)

    def test_the_saved_file_carries_exactly_the_keys_the_contract_names(self):
        """Six keys, no more and no fewer.

        The elo travels with the position rather than being looked up again on
        resume, because the band drifts with time: a game picked up a week later
        must be finished at the strength it was started at, not at whatever the
        ladder has drifted to since.
        """
        game = ChessGame(rau_color=WHITE, elo=1730)
        run(game, "d2d4", "d7d5")
        game.save()

        data = saved(board_mod.current_path())
        self.assertEqual(set(data), SAVED_KEYS)
        self.assertEqual(data["moves"], ["d4", "d5"])
        self.assertEqual(data["rau_color"], WHITE)
        self.assertEqual(data["elo"], 1730)
        self.assertEqual(data["game_id"], game.game_id)
        self.assertEqual(data["fen"], game.board.fen())
        self.assertIsInstance(data["started_at"], float)

    def test_the_position_is_written_after_every_move(self):
        """Not on a timer and not at the end — after each move, or it is not a save.

        The failure this prevents is the specific one that makes people stop
        playing: the crash lands between the interesting move and whatever the
        autosave interval was, and the position that comes back is the one before
        the sacrifice.
        """
        from rau.games.chess import session

        stub_the_performance(self)
        self.addCleanup(lambda: session.end("test over"))
        session.start(rau_color="black")

        seats = (USER, RAU, USER, RAU)
        for index, (seat, move) in enumerate(zip(seats, SCHOLARS), start=1):
            answer = session.apply_move(
                seat, {"move": "move", "from": move[:2], "to": move[2:4]}
            )
            self.assertTrue(answer["ok"], answer)
            with self.subTest(ply=index):
                self.assertEqual(len(saved(board_mod.current_path())["moves"]), index)

    def test_the_write_goes_through_a_temp_file_and_leaves_none_behind(self):
        """A save that half-lands is worse than no save at all.

        `chess_current.json` is read on the boot path with no second copy
        anywhere, so a truncated one is a lost game. The write goes to a sibling
        `.tmp` — same directory, so the rename is atomic on the same filesystem —
        and the directory is left holding one file.
        """
        game = ChessGame()
        run(game, "e2e4")
        game.save()
        game.save()
        self.assertEqual(
            sorted(p.name for p in self.games_dir.iterdir()), ["chess_current.json"]
        )

    def test_an_interrupted_write_leaves_the_previous_position_intact(self):
        """The proof that the target is never written to directly.

        The rename is made to fail, which is as close as a test gets to the power
        going out between two syscalls. If the position were serialised straight
        into `chess_current.json` the old game would now be a fragment; because it
        goes through the temp file, the previous move is still there and still
        parses.
        """
        game = ChessGame()
        run(game, "e2e4")
        game.save()
        before = board_mod.current_path().read_text(encoding="utf-8")

        run(game, "e7e5")
        with patch.object(Path, "replace", side_effect=OSError("disk went away")):
            game.save()  # swallowed on purpose: a lost autosave must not stop play

        self.assertEqual(board_mod.current_path().read_text(encoding="utf-8"), before)
        self.assertEqual(saved(board_mod.current_path())["moves"], ["e4"])
        self.assertIsNone(game.result, "a failed save must not touch the game")


class Resuming(unittest.TestCase):
    """Picking the board back up, including when the file is nonsense."""

    def setUp(self) -> None:
        self.games_dir = isolate_games(self)

    def test_nothing_saved_resumes_nothing(self):
        """The common case, and it must not be an error."""
        self.assertIsNone(board_mod.resume())

    def test_a_resumed_game_is_the_same_game(self):
        """Same history, same position, same colours, same identity.

        The move stack length is checked separately from the FEN because they can
        agree by accident: a FEN-only restore matches the position exactly and
        has an empty stack, which is the bug the next test is about.
        """
        game = ChessGame(rau_color=WHITE, elo=1660)
        run(game, "e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4")
        game.save()

        back = board_mod.resume()
        assert back is not None
        self.assertEqual(len(back.board.move_stack), len(game.board.move_stack))
        self.assertEqual(back.board.fen(), game.board.fen())
        self.assertEqual(back.moves, game.moves)
        self.assertEqual(back.rau_color, WHITE)
        self.assertEqual(back.user_color, BLACK)
        self.assertEqual(back.turn_seat(), game.turn_seat())
        self.assertEqual(back.elo, 1660)
        self.assertEqual(back.game_id, game.game_id)
        self.assertEqual(back.started_at, game.started_at)
        self.assertEqual(back.last_move, {"from": "c5", "to": "d4", "san": "cxd4"})

    def test_a_claimable_repetition_survives_a_restart(self):
        """The reason the move list is stored at all.

        A board rebuilt from the FEN is in the same position and has no idea it
        has been there before, so the claim button vanishes across a restart and
        the user is never told why. Both halves are asserted: what the replay
        knows, and what the FEN alone does not.
        """
        game = ChessGame()
        run(game, "g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1", "f6g8")
        self.assertTrue(game.can_claim_draw())
        game.save()

        fen_only = chess.Board(saved(board_mod.current_path())["fen"])
        self.assertFalse(
            fen_only.can_claim_threefold_repetition(),
            "a FEN that remembered the repetition would make this test vacuous",
        )

        back = board_mod.resume()
        assert back is not None
        self.assertTrue(back.can_claim_draw(), "the repetition was thrown away")
        self.assertEqual(len(back.board.move_stack), 8)
        self.assertTrue(back.snapshot()["can_claim_draw"])

    def test_a_claimable_fifty_move_count_survives_a_restart(self):
        """The halfmove clock lives in the FEN, so this one comes back either way.

        Kept anyway, because it is the other claimable draw and a replay that
        reset the counter would be just as invisible as one that lost the
        repetition.
        """
        game = at("8/8/8/4k3/8/8/4K3/7R w - - 99 60", rau_color=WHITE)
        run(game, "h1h2")
        self.assertTrue(game.can_claim_draw())
        game.save()

        back = board_mod.resume()
        assert back is not None
        self.assertTrue(back.can_claim_draw())

    def test_corrupt_json_is_no_game_rather_than_a_crash(self):
        """`resume()` runs on the boot path; it is not allowed to stop the boot."""
        self.games_dir.mkdir(parents=True, exist_ok=True)
        for bad in ('{"fen": "8/8/8', "", "[1, 2, 3]", '"a string"', "null"):
            with self.subTest(content=bad):
                board_mod.current_path().write_text(bad, encoding="utf-8")
                self.assertIsNone(board_mod.resume())

    def test_a_move_list_that_will_not_replay_falls_back_to_the_stored_fen(self):
        """The FEN is the check on the replay, and it wins when they disagree.

        A hand-edited file, or a save from a version of this code that spelt a
        move differently, must still come back as the position that was actually
        on the board rather than as nothing.
        """
        self.games_dir.mkdir(parents=True, exist_ok=True)
        fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 5 4"
        board_mod.current_path().write_text(
            json.dumps(
                {
                    "fen": fen,
                    "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4", "wobble"],
                    "rau_color": WHITE,
                    "started_at": 1_700_000_000.0,
                    "elo": 1420,
                    "game_id": "c-abcdef0123",
                }
            ),
            encoding="utf-8",
        )

        back = board_mod.resume()
        assert back is not None
        self.assertEqual(back.board.fen(), fen)
        self.assertEqual(back.game_id, "c-abcdef0123")
        self.assertEqual(back.elo, 1420)
        self.assertEqual(
            back.moves,
            ["e4", "e5", "Nf3", "Nc6", "Bc4", "wobble"],
            "the six stored moves, not the five that replayed — this is the fallback",
        )
        self.assertIsNone(
            back.last_move, "no move was replayed, so nothing may be lit up as the last one"
        )

    def test_a_finished_game_on_disk_is_thrown_away_rather_than_resumed(self):
        """A decided position is not a game to come back to.

        It can be on disk perfectly legitimately — the crash landed between the
        mating move's save and the tidy-up. Leaving the file would make the same
        finished game reappear on every boot from now on, so `resume` discards it
        as well as declining it.
        """
        game = ChessGame()
        run(game, *SCHOLARS)
        self.assertEqual(game.result, "1-0")
        game.save()
        self.assertTrue(board_mod.current_path().exists())

        self.assertIsNone(board_mod.resume())
        self.assertFalse(
            board_mod.current_path().exists(), "the finished game would come back forever"
        )

    def test_discard_saved_clears_the_table_and_is_safe_on_an_empty_one(self):
        """Called when the board is put away, and when it already has been."""
        game = ChessGame()
        run(game, "e2e4")
        game.save()
        self.assertTrue(board_mod.current_path().exists())

        board_mod.discard_saved()
        self.assertFalse(board_mod.current_path().exists())
        board_mod.discard_saved()  # must not raise the second time
        self.assertIsNone(board_mod.resume())


class ThePgnPile(unittest.TestCase):
    """`memories/games/chess.pgn` — every finished game, in the order they ended."""

    def setUp(self) -> None:
        self.games_dir = isolate_games(self)

    def played_out(self) -> ChessGame:
        game = ChessGame(rau_color=BLACK)
        run(game, *SCHOLARS)
        return game

    def resigned(self) -> ChessGame:
        game = ChessGame(rau_color=WHITE)
        run(game, "d2d4", "d7d5")
        game.resign(RAU)
        return game

    def test_two_finished_games_both_end_up_in_the_file(self):
        """Appended, never rewritten.

        This is the only lasting record of a game once `chess_current.json` has
        been discarded. A second game truncating the file would quietly delete
        the first, and nobody would look until they went to find it.
        """
        first = self.played_out()
        second = self.resigned()
        board_mod.append_pgn(first)
        board_mod.append_pgn(second)

        text = board_mod.pgn_path().read_text(encoding="utf-8")
        self.assertEqual(text.count('[Event "Chess at Rau\'s table"]'), 2)
        self.assertIn("Qxf7#", text, "the first game was overwritten")
        self.assertIn('[Termination "checkmate"]', text)
        self.assertIn('[Termination "resignation"]', text)

        games = [line for line in text.splitlines() if line.startswith("1.")]
        self.assertEqual(len(games), 2)

    def test_the_headers_say_who_had_which_colour_and_how_it_ended(self):
        """A resignation is invisible in the move list, so the headers carry it.

        Without the `Termination` header the second game reads as an unfinished
        one that stopped after two moves, which is not what happened.
        """
        board_mod.append_pgn(self.resigned())
        text = board_mod.pgn_path().read_text(encoding="utf-8")
        self.assertIn('[White "Rau"]', text)
        self.assertIn('[Black "Them"]', text)
        self.assertIn('[Result "0-1"]', text)
        self.assertIn('[Termination "resignation"]', text)

    def test_a_game_he_played_black_in_names_him_on_the_black_side(self):
        board_mod.append_pgn(self.played_out())
        text = board_mod.pgn_path().read_text(encoding="utf-8")
        self.assertIn('[White "Them"]', text)
        self.assertIn('[Black "Rau"]', text)
        self.assertIn('[Result "1-0"]', text)


class TheSharedTally(unittest.TestCase):
    """
    `memories/games.json` has two owners now, and neither may flatten the other.

    This is the bug named in the contract. `kittens/session.py` wrote
    `{"kittens": record}` over the whole document, which was correct for exactly
    as long as kittens was the only game in the house. Chess keeps its elo in the
    same file, so from the day both existed every finished hand of one game
    silently deleted the other's history — including the rating band that makes
    him a fair opponent, which would reset to 1500 with nothing in any log to say
    it had.

    Both directions are tested because fixing one and forgetting the other looks
    exactly like fixing it.
    """

    def setUp(self) -> None:
        isolate_games(self)
        import rau.paths as paths_mod

        self.games_file = paths_mod.GAMES_FILE

    def seed(self, document: Dict[str, Any]) -> None:
        self.games_file.parent.mkdir(parents=True, exist_ok=True)
        self.games_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def document(self) -> Dict[str, Any]:
        return json.loads(self.games_file.read_text(encoding="utf-8"))

    def finished_hand(self, winner: str) -> Any:
        """The little of a kittens `Game` that `_record_tally` actually reads."""
        return types.SimpleNamespace(winner=winner, game_id="k-test", log=[])

    def test_recording_a_chess_result_leaves_the_kittens_record_alone(self):
        from rau.games.chess import level

        self.seed(
            {
                "kittens": {"wins": 4, "losses": 9, "last_played": 1_700_000_000.0},
                "somebody_elses_key": {"kept": True},
            }
        )
        level.record_result(USER)

        document = self.document()
        self.assertEqual(
            document["kittens"], {"wins": 4, "losses": 9, "last_played": 1_700_000_000.0}
        )
        self.assertEqual(document["somebody_elses_key"], {"kept": True})
        self.assertEqual(document["chess"]["losses"], 1)
        self.assertIn("elo", document["chess"])

    def test_recording_a_kittens_result_leaves_the_chess_record_alone(self):
        """The direction the bug was originally written in.

        The elo is the part that hurts: it is never shown, so a reset one is not
        a visible failure. He simply plays like a different person and there is
        nothing anywhere that says why.
        """
        from rau.games.kittens import session as kittens_session

        self.seed(
            {
                "chess": {"wins": 2, "losses": 5, "draws": 1, "elo": 1780},
                "somebody_elses_key": {"kept": True},
            }
        )
        kittens_session._record_tally(self.finished_hand(RAU))

        document = self.document()
        self.assertEqual(
            document["chess"], {"wins": 2, "losses": 5, "draws": 1, "elo": 1780}
        )
        self.assertEqual(document["somebody_elses_key"], {"kept": True})
        self.assertEqual(document["kittens"]["wins"], 1)

    def test_the_two_games_can_be_recorded_alternately_without_either_thinning(self):
        """Four games at one table and four at the other, interleaved.

        The one-shot tests above would both pass against an implementation that
        read the file once at import. This one only passes if every write is its
        own read-modify-write.
        """
        from rau.games.chess import level
        from rau.games.kittens import session as kittens_session

        for _ in range(4):
            level.record_result(RAU)
            kittens_session._record_tally(self.finished_hand(RAU))

        document = self.document()
        self.assertEqual(document["chess"]["wins"], 4)
        self.assertEqual(document["kittens"]["wins"], 4)
        self.assertEqual(sorted(document), ["chess", "kittens"])

    def test_a_tally_written_over_a_broken_document_starts_again_rather_than_raising(self):
        """A file somebody edited by hand must not take the scoreboard with it."""
        from rau.games.chess import level

        self.games_file.parent.mkdir(parents=True, exist_ok=True)
        self.games_file.write_text("{ this is not json", encoding="utf-8")

        level.record_result(None)
        self.assertEqual(self.document()["chess"]["draws"], 1)

    def test_neither_writer_leaves_a_temp_file_behind(self):
        """Both go through `games.json.tmp`, and both finish the rename."""
        from rau.games.chess import level
        from rau.games.kittens import session as kittens_session

        level.record_result(USER)
        kittens_session._record_tally(self.finished_hand(USER))
        self.assertEqual(
            sorted(p.name for p in self.games_file.parent.iterdir()), ["games.json"]
        )

    def test_the_chess_record_read_back_is_the_one_that_was_written(self):
        """Both readers see the same record under the same key."""
        from rau.games.chess import level, session

        level.record_result(USER, now=time.time())
        public = session.tally()
        internal = level.tally()
        self.assertEqual(public, {k: v for k, v in internal.items() if k != "elo"})
        self.assertEqual(public["losses"], 1)

    def test_the_elo_never_leaves_the_process(self):
        """
        `session.tally()` is the door the record leaves by — into a tool result
        that becomes his own context, into the `game_over` frame, and into the
        browser on load. The elo must not be on the other side of it.

        The whole adaptive-strength mechanism only works while it is invisible.
        A Rau who can read his own rating in his prompt is a Rau who can mention
        it, and then the opponent stops being a person and becomes a slider.
        """
        from rau.games.chess import level, session

        level.record_result(USER, now=time.time())
        self.assertIn("elo", level.tally(), "the elo stopped being tracked at all")
        self.assertNotIn("elo", session.tally())
        # It still moved, and the code can still ask.
        self.assertEqual(level.current(), 1560)


if __name__ == "__main__":
    unittest.main()

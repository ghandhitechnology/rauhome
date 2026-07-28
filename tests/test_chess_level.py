"""
The handicap nobody can see, and the reason it needs a file of its own.

`level.py` is the one part of this feature with no visible failure mode. A board
that draws wrong is obvious in a second; an elo that moves the wrong way, or
saturates at a number the binary refuses, or forgets to drift, produces an
opponent who is simply a bit off — and "a bit off" is indistinguishable from
"chess is hard" for as long as anybody is willing to keep playing. Nothing here
ever reaches the screen, so nothing here is ever noticed. That is the whole
argument for testing it exhaustively rather than incidentally.

Three properties carry the feature and each has its own class below.

* **Direction.** Beating him makes him stronger. Inverted, he still feels like an
  opponent — he just gets easier forever, and the person at the table slowly
  stops being able to lose. `test_chess_session.TheLadder` already plays a whole
  game to check the sign; this file checks the arithmetic underneath it, where
  the clamp and the drift live and where a whole game is too blunt an instrument.
* **The band is the reachable one.** The agreed range was 1100–1900. 1100 is not
  a number Stockfish accepts — its `UCI_Elo` is `spin min 1320 max 3190` — so
  asking for it is refused and he plays at whatever he was set to last, which is
  a silent handicap that ignores the entire ladder. The floor moved to 1320 and
  the last class here asks the installed binary whether that is still true.
* **Idle drift.** Ten points a week back toward the middle. Without it a run of
  losses from six months ago is still shaping the first game after a long gap.

`record_result` and `current` both take an injected `now`, so every clock in this
file is a number written in the test. Nothing sleeps and nothing is timing
dependent. Only the last class opens anything, and it skips itself where there is
no binary to open.

Run: python -m unittest tests.test_chess_level -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.chess import binary, level  # noqa: E402
from rau.games.chess import view as view_mod  # noqa: E402
from rau.games.chess.board import ChessGame  # noqa: E402
from rau.games.chess.level import RAU, USER  # noqa: E402
from tests.test_chess_session import isolate_memory  # noqa: E402

#: A fixed instant to hang every record off. Real seconds, so the week arithmetic
#: is the real arithmetic, but written down rather than read off a clock.
NOW = 1_785_000_000.0


class LadderCase(unittest.TestCase):
    """A games document in a temporary directory, and a clock that does not move."""

    def setUp(self) -> None:
        isolate_memory(self)

    def stored(self) -> Dict[str, Any]:
        """The chess record as it actually sits on disk."""
        if not self.tmp_games.exists():
            return {}
        return json.loads(self.tmp_games.read_text(encoding="utf-8")).get("chess") or {}

    def seed(self, **fields: Any) -> None:
        """Put a record on disk without going through a result, the way a restart finds one."""
        self.tmp_games.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_games.write_text(json.dumps({"chess": fields}), encoding="utf-8")


class TheDirection(LadderCase):
    """
    He moves against whoever has been winning.

    This is the assertion that reads backwards to everyone who meets it, which is
    exactly why it is worth spelling out twice: the number is not a reward. It is
    the thing keeping the game close, so it goes up when you win.
    """

    def test_a_game_the_user_won_makes_him_stronger(self):
        self.assertEqual(level.record_result(USER, now=NOW), level.START + level.DECISIVE)

    def test_a_game_he_won_makes_him_ease_off(self):
        self.assertEqual(level.record_result(RAU, now=NOW), level.START - level.DECISIVE)

    def test_the_step_is_big_enough_to_be_felt_within_an_evening(self):
        """Three games is the horizon that matters; a step too small is no ladder."""
        self.assertGreaterEqual(level.DECISIVE, 50)
        self.assertGreater(level.DECISIVE, level.DRAW_PULL)

    def test_the_result_and_the_running_count_are_written_in_the_same_breath(self):
        level.record_result(USER, now=NOW)
        level.record_result(RAU, now=NOW)
        level.record_result(None, now=NOW)
        record = self.stored()
        self.assertEqual(record["losses"], 1)
        self.assertEqual(record["wins"], 1)
        self.assertEqual(record["draws"], 1)
        self.assertEqual(record["last_played"], NOW)

    def test_the_number_that_comes_back_is_the_number_written_down(self):
        """The caller uses the return value; the next game reads the file. They must agree."""
        for winner in (USER, USER, RAU, None, USER):
            returned = level.record_result(winner, now=NOW)
            self.assertEqual(returned, self.stored()["elo"])
            self.assertEqual(returned, level.current(now=NOW))


class TheReachableBand(LadderCase):
    """
    A number outside the band is a number the engine throws away.

    `_apply_elo` sends `UCI_Elo` and does not look at the reply. Ask for 1100 and
    Stockfish refuses the option, and he goes on playing at whatever he was set
    to before — so the ladder appears to work, the file fills up with results,
    and none of it reaches the board. The clamp is what keeps that from happening
    and this class is what keeps the clamp honest.
    """

    def test_the_floor_is_the_one_the_binary_will_actually_take(self):
        self.assertGreaterEqual(level.FLOOR, 1320)

    def test_the_starting_point_sits_inside_the_band(self):
        self.assertLess(level.FLOOR, level.START)
        self.assertLess(level.START, level.CEIL)

    def test_a_losing_streak_stops_at_the_floor_rather_than_below_it(self):
        for _ in range(20):
            level.record_result(RAU, now=NOW)
        self.assertEqual(level.current(now=NOW), level.FLOOR)
        self.assertEqual(self.stored()["elo"], level.FLOOR)

    def test_a_winning_streak_stops_at_the_ceiling_rather_than_above_it(self):
        for _ in range(20):
            level.record_result(USER, now=NOW)
        self.assertEqual(level.current(now=NOW), level.CEIL)
        self.assertEqual(self.stored()["elo"], level.CEIL)

    def test_a_record_from_outside_the_band_is_pulled_back_into_it_on_the_way_out(self):
        """A hand-edited file, or one written by an older floor, still plays legally."""
        self.seed(elo=800)
        self.assertEqual(level.current(now=NOW), level.FLOOR)
        self.seed(elo=3000)
        self.assertEqual(level.current(now=NOW), level.CEIL)

    def test_the_elo_is_a_whole_number_because_the_engine_option_is_one(self):
        self.seed(elo=1500.5, last_played=NOW - level.WEEK_SEC / 3)
        elo = level.current(now=NOW)
        self.assertIsInstance(elo, int)
        self.assertIsInstance(level.record_result(None, now=NOW), int)
        self.assertIsInstance(self.stored()["elo"], int)


class TheDrawNudge(LadderCase):
    """
    A draw says the two of you are matched, and almost nothing else.

    So it pulls toward the middle rather than in a direction, and it pulls by a
    quarter of what a decisive game does. The failure it guards is a draw that
    overshoots: pulled fifteen points from nine points off centre, he arrives on
    the far side of 1500 and a series of draws oscillates instead of settling.
    """

    def test_a_draw_from_the_middle_leaves_him_where_he_was(self):
        self.assertEqual(level.record_result(None, now=NOW), level.START)

    def test_a_draw_from_above_the_middle_comes_down_toward_it(self):
        self.seed(elo=1700)
        self.assertEqual(level.record_result(None, now=NOW), 1700 - level.DRAW_PULL)

    def test_a_draw_from_below_the_middle_comes_up_toward_it(self):
        self.seed(elo=1400)
        self.assertEqual(level.record_result(None, now=NOW), 1400 + level.DRAW_PULL)

    def test_a_draw_from_just_off_centre_lands_on_centre_and_not_past_it(self):
        self.seed(elo=level.START + 4)
        self.assertEqual(level.record_result(None, now=NOW), level.START)
        self.seed(elo=level.START - 4)
        self.assertEqual(level.record_result(None, now=NOW), level.START)

    def test_a_run_of_draws_settles_on_the_middle_instead_of_oscillating(self):
        self.seed(elo=1660)
        seen = [level.record_result(None, now=NOW) for _ in range(40)]
        self.assertEqual(seen[-1], level.START)
        self.assertEqual(sorted(seen, reverse=True), seen, "a draw sent him back up")


class TheIdleDrift(LadderCase):
    """
    The band forgets, slowly.

    A run of losses six months ago should not still be shaping the first game
    after a long gap — you are a different player by then. Drift is computed on
    the way out rather than written back, so `current` stays a read; the tests
    below check both halves of that, because a drift that quietly writes turns
    every prompt build into a disk write.
    """

    def test_a_week_of_not_playing_moves_him_ten_points_toward_the_middle(self):
        self.seed(elo=1800, last_played=NOW - level.WEEK_SEC)
        self.assertEqual(level.current(now=NOW), 1800 - level.DRIFT_PER_WEEK)

    def test_drift_is_proportional_rather_than_a_step_at_the_week_mark(self):
        self.seed(elo=1800, last_played=NOW - level.WEEK_SEC * 2.5)
        self.assertEqual(level.current(now=NOW), 1800 - 25)

    def test_a_long_absence_settles_on_the_middle_and_does_not_sail_past_it(self):
        self.seed(elo=1800, last_played=NOW - level.WEEK_SEC * 400)
        self.assertEqual(level.current(now=NOW), level.START)
        self.seed(elo=1350, last_played=NOW - level.WEEK_SEC * 400)
        self.assertEqual(level.current(now=NOW), level.START)

    def test_a_record_that_was_never_played_does_not_drift(self):
        self.seed(elo=1800)
        self.assertEqual(level.current(now=NOW), 1800)

    def test_a_clock_that_went_backwards_is_not_a_negative_drift(self):
        """Time changes and NTP corrections must not push him further from centre."""
        self.seed(elo=1800, last_played=NOW + level.WEEK_SEC * 5)
        self.assertEqual(level.current(now=NOW), 1800)

    def test_the_drift_is_settled_before_the_game_is_scored(self):
        """Otherwise the first game back is scored against a number from months ago."""
        self.seed(elo=1800, last_played=NOW - level.WEEK_SEC)
        self.assertEqual(
            level.record_result(RAU, now=NOW),
            1800 - level.DRIFT_PER_WEEK - level.DECISIVE,
        )

    def test_reading_the_elo_writes_nothing(self):
        self.assertEqual(level.current(now=NOW), level.START)
        self.assertFalse(
            self.tmp_games.exists(),
            "asking how hard he plays created a games file out of nothing",
        )

    def test_reading_the_elo_does_not_bank_the_drift(self):
        self.seed(elo=1800, last_played=NOW - level.WEEK_SEC)
        for _ in range(5):
            level.current(now=NOW)
        self.assertEqual(self.stored()["elo"], 1800, "a read wrote the drift back")


class AGarbledRecord(LadderCase):
    """
    Whatever is in that file, he still sits down and plays.

    `memories/games.json` is hand-editable, shared with another game, and written
    by two processes over the life of the machine. Every reader here answers with
    a playable number instead of raising, because the alternative is a chess
    feature that refuses to start because of a stray comma.
    """

    def test_no_file_at_all_is_a_fresh_opponent(self):
        self.assertEqual(level.current(now=NOW), level.START)
        self.assertEqual(level.tally(), {})

    def test_a_file_that_is_not_json_is_a_fresh_opponent(self):
        self.tmp_games.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_games.write_text("{not json at all", encoding="utf-8")
        self.assertEqual(level.current(now=NOW), level.START)
        self.assertEqual(level.tally(), {})

    def test_a_document_that_is_a_list_is_a_fresh_opponent(self):
        self.tmp_games.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_games.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(level.current(now=NOW), level.START)

    def test_an_elo_that_is_not_a_number_is_a_fresh_opponent(self):
        self.seed(elo="quite strong", last_played=NOW - level.WEEK_SEC)
        self.assertEqual(level.current(now=NOW), level.START)

    def test_a_last_played_that_is_not_a_number_simply_does_not_drift(self):
        self.seed(elo=1800, last_played="yesterday")
        self.assertEqual(level.current(now=NOW), 1800)

    def test_counts_that_are_missing_start_from_zero_rather_than_raising(self):
        self.seed(elo=1600)
        level.record_result(USER, now=NOW)
        record = self.stored()
        self.assertEqual(record["wins"], 0)
        self.assertEqual(record["losses"], 1)
        self.assertEqual(record["draws"], 0)

    def test_a_broken_document_is_replaced_rather_than_appended_to(self):
        self.tmp_games.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_games.write_text("]]]", encoding="utf-8")
        level.record_result(USER, now=NOW)
        self.assertEqual(self.stored()["elo"], level.START + level.DECISIVE)


class NobodyEverSeesTheNumber(LadderCase):
    """
    The rating is not in the UI and not in his mouth.

    A visible handicap stops being an opponent adapting and starts being a
    difficulty slider, and a Rau who can read his own rating will eventually
    mention it. `browser_view`'s key set is pinned elsewhere; what is checked
    here is the rendered text of both payloads, because the leak that actually
    happens is a number inside a string rather than a new key.
    """

    def game_at(self, elo: int) -> ChessGame:
        game = ChessGame(rau_color="black", elo=elo)
        game.play("user", "e2", "e4")
        return game

    def test_the_browser_payload_never_carries_the_rating(self):
        game = self.game_at(1743)
        payload = json.dumps(view_mod.browser_view(game))
        self.assertNotIn("1743", payload)
        self.assertNotIn("elo", payload.lower())

    def test_the_talker_is_never_told_how_hard_his_other_half_is_playing(self):
        game = self.game_at(1743)
        fragment = view_mod.talker_fragment(game).lower()
        self.assertNotIn("1743", fragment)
        self.assertNotIn("elo", fragment)
        self.assertNotIn("rating", fragment)
        self.assertNotIn("difficulty", fragment)

    def test_the_finished_board_does_not_announce_the_rating_either(self):
        """The result screen is the obvious place for a number to appear."""
        game = self.game_at(1743)
        game.resign("user")
        self.assertNotIn("1743", json.dumps(view_mod.browser_view(game)))
        self.assertNotIn("1743", view_mod.talker_fragment(game))

    def test_the_saved_position_does_carry_it_because_a_restart_needs_it(self):
        """The one place it belongs: on disk, where only the next game reads it."""
        from rau.games.chess import board as board_mod

        board_mod.save(self.game_at(1743))
        saved = json.loads(board_mod.current_path().read_text(encoding="utf-8"))
        self.assertEqual(saved["elo"], 1743)
        self.assertEqual(board_mod.resume().elo, 1743, "a restart forgot the handicap")


@unittest.skipUnless(binary.found(), "no stockfish on this machine")
class AgainstTheRealBinary(unittest.TestCase):
    """
    The floor moved to 1320 because of what this binary said, so ask it again.

    The comment in `level.py` records a range read off the Stockfish installed on
    one machine on one day. That is exactly the kind of fact that rots: a newer
    build, a different vendor, someone's `$RAU_STOCKFISH` pointing at a wrapper.
    If the range moves, the clamp is wrong and every `UCI_Elo` outside it is
    silently discarded — so the range is checked against the engine that is
    actually going to be asked, rather than against the comment.

    One process, opened and closed. Nothing searches.
    """

    def setUp(self) -> None:
        path = binary.found()
        assert path is not None
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self.addCleanup(self.engine.close)

    def option(self) -> Any:
        option = self.engine.options.get("UCI_Elo")
        if option is None:
            self.skipTest("this build has no UCI_Elo to clamp against")
        return option

    def test_the_band_is_one_this_engine_will_accept_end_to_end(self):
        option = self.option()
        self.assertGreaterEqual(level.FLOOR, option.min)
        self.assertLessEqual(level.CEIL, option.max)

    def test_limit_strength_is_the_switch_that_makes_the_band_mean_anything(self):
        """`UCI_Elo` is ignored unless `UCI_LimitStrength` is on; both must exist."""
        self.assertIn("UCI_LimitStrength", self.engine.options)
        self.assertIn("UCI_Elo", self.engine.options)

    def test_every_rung_of_the_ladder_is_inside_what_it_will_take(self):
        """Walked rather than reasoned about: the clamp is the only thing between
        a long losing streak and a number the engine drops on the floor."""
        option = self.option()
        elo = level.START
        for winner in [RAU] * 12 + [USER] * 24 + [None] * 6:
            elo = level._clamp(  # noqa: SLF001
                elo + (level.DECISIVE if winner == USER else -level.DECISIVE)
                if winner
                else elo
            )
            with self.subTest(elo=elo):
                self.assertGreaterEqual(elo, option.min)
                self.assertLessEqual(elo, option.max)


if __name__ == "__main__":
    unittest.main()

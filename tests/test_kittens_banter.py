"""
Rau talking across the table without being asked.

Run: python -m unittest tests.test_kittens_banter -v

Every test here drives `banter.consider` directly with a hand-built table, so
what is under test is the decision — when he speaks, when he stays quiet, and
what happens to a line that arrives too late to be true any more — rather than
the pump's timing.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.games.kittens import banter, session, tools  # noqa: E402
from rau.games.kittens.deck import SKIP  # noqa: E402
from rau.games.kittens.engine import PHASE_PLAYING, RAU, USER  # noqa: E402
from tests.test_kittens_session import isolate_memory, quiesce  # noqa: E402


def wait_for_banter(limit: float = 5.0) -> None:
    """Block until the in-flight line has landed, or give up."""
    deadline = time.time() + limit
    while banter.busy().is_set() and time.time() < deadline:
        time.sleep(0.01)


class BanterCase(unittest.TestCase):
    """A live hand, the user to move, and no real provider anywhere."""

    def setUp(self) -> None:
        isolate_memory(self)
        import rau.games.kittens.player as player_mod

        self._player = player_mod
        self._real_take = player_mod.take_turn
        self._real_nope = player_mod.decide_nope
        player_mod.take_turn = lambda game: None
        player_mod.decide_nope = lambda game: False

        self.said: List[str] = []
        patcher = patch.object(player_mod, "table_talk", self.said.append)
        patcher.start()
        self.addCleanup(patcher.stop)

        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        self.game = game
        game.hands[RAU] = [SKIP, SKIP]
        game.hands[USER] = [SKIP, SKIP]
        game.draw = [SKIP, SKIP, SKIP]
        game.phase = PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        game.current = USER

        # The pump looks at this table on its own schedule, which would race
        # every assertion below over the same cooldowns. These tests drive
        # `consider` by hand instead, so the daemon is put away first — after
        # it has stopped, so a tick in flight cannot re-mark the log.
        from rau.games.kittens import pump

        pump.stop()
        time.sleep(pump.POLL_SEC * 2)
        banter.reset()

    def tearDown(self) -> None:
        wait_for_banter()
        quiesce()
        self._player.take_turn = self._real_take
        self._player.decide_nope = self._real_nope
        banter.reset()

    def answer(self, text: str) -> None:
        self.addCleanup(setattr, banter, "_ask", banter._ask)
        banter._ask = lambda prompt: text

    def user_moved(self, text: str = "played Skip") -> None:
        self.game._note(USER, text)  # noqa: SLF001 — the engine's own log call

    def look(self) -> None:
        """One pump tick's worth of looking at the table."""
        banter.consider(self.game)
        wait_for_banter()


class WhenHeSpeaks(BanterCase):
    def test_reacts_to_a_move_the_user_just_made(self):
        self.answer("bold, with three cards left.")
        self.look()  # first look only takes the fingerprint
        self.user_moved()
        self.look()
        self.assertEqual(self.said, ["bold, with three cards left."])

    def test_skip_means_he_says_nothing(self):
        self.answer("SKIP")
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, [])

    def test_first_look_at_a_hand_in_progress_says_nothing(self):
        # A reload, or the pump restarting mid-hand: the log is full of moves
        # nobody has just made.
        self.answer("welcome back.")
        self.user_moved()
        self.look()
        self.assertEqual(self.said, [])

    def test_quotes_are_stripped(self):
        self.answer('"that was your last Skip."')
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, ["that was your last Skip."])

    def test_only_the_first_line_survives(self):
        self.answer("nice.\nAlso here is a paragraph about strategy.")
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, ["nice."])


class WhenHeStaysQuiet(BanterCase):
    def test_silent_on_his_own_turn(self):
        # His move carries its own line; a second one is a stutter.
        self.answer("my turn, and I like it.")
        self.look()
        self.user_moved()
        self.game.current = RAU
        self.look()
        self.assertEqual(self.said, [])

    def test_silent_while_a_turn_of_his_is_in_flight(self):
        self.answer("thinking out loud.")
        self.look()
        self.user_moved()
        banter.consider(self.game, thinking=True)
        wait_for_banter()
        self.assertEqual(self.said, [])

    def test_cooldown_holds_the_second_line(self):
        self.answer("one.")
        self.look()
        self.user_moved()
        self.look()
        self.user_moved("played another Skip")
        self.look()
        self.assertEqual(self.said, ["one."])

    def test_a_real_reply_holds_the_next_line(self):
        self.answer("I would have said something.")
        self.look()
        banter.note_user_chat()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, [])

    def test_nothing_when_the_hand_is_over(self):
        self.answer("too late.")
        self.look()
        self.user_moved()
        self.game.phase = "over"
        self.look()
        self.assertEqual(self.said, [])

    def test_a_line_that_arrives_after_the_hand_is_dropped(self):
        # The provider was slow and the table moved on. Delivering now would
        # put a line about a live game over a finished one.
        def slow(prompt: str) -> str:
            session.end("test over")
            return "still your move."

        self.addCleanup(setattr, banter, "_ask", banter._ask)
        banter._ask = slow
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, [])


class IdleProd(BanterCase):
    def test_a_turn_sat_on_earns_a_line(self):
        self.answer("any day now.")
        self.look()
        # Their turn, nothing happening, long enough that it is worth saying so.
        banter._turn_since = time.monotonic() - banter.IDLE_PROD_SEC - 1
        self.look()
        self.assertEqual(self.said, ["any day now."])

    def test_a_turn_sat_on_briefly_does_not(self):
        self.answer("any day now.")
        self.look()
        banter._turn_since = time.monotonic() - 1
        self.look()
        self.assertEqual(self.said, [])


if __name__ == "__main__":
    unittest.main()

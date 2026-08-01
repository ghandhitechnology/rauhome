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

    def test_a_move_made_during_the_cooldown_still_earns_its_reaction(self):
        self.answer("one.")
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, ["one."])
        # Lands while the cooldown from "one." is still up: nothing is said
        # yet, but the move must not be fingerprinted and forgotten.
        self.user_moved("played another Skip")
        self.look()
        self.assertEqual(self.said, ["one."])
        # The cooldown expires; the move is still unseen, so it gets its
        # reaction now rather than never.
        banter._next_ok_at = 0.0
        self.answer("two.")
        self.look()
        self.assertEqual(self.said, ["one.", "two."])

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

    def test_a_dropped_line_costs_the_short_wait(self):
        # Same slow provider: the line comes back after the hand ended and is
        # dropped. Nobody heard it, so the wait it charges is the short one,
        # not the full gag a delivered line earns.
        def slow(prompt: str) -> str:
            session.end("test over")
            return "still your move."

        self.addCleanup(setattr, banter, "_ask", banter._ask)
        banter._ask = slow
        self.look()
        self.user_moved()
        before = time.monotonic()
        self.look()
        self.assertEqual(self.said, [])
        charged = banter._next_ok_at - before
        self.assertGreater(charged, 0)
        self.assertLessEqual(charged, banter.SKIP_GAP_SEC + 1)

    def test_a_line_drops_when_a_conversation_starts_mid_thought(self):
        # The face was free when he started thinking and busy by the time the
        # line came back. Delivering it would talk over the conversation, so
        # it is dropped — and charged the short wait, like any unheard line.
        talking = {"on": False}

        def slow(prompt: str) -> str:
            talking["on"] = True
            return "wait, what?"

        self.addCleanup(setattr, banter, "_ask", banter._ask)
        banter._ask = slow
        self.addCleanup(
            setattr, banter, "_face_is_talking", banter._face_is_talking
        )
        banter._face_is_talking = lambda: talking["on"]
        self.look()
        self.user_moved()
        self.look()
        self.assertEqual(self.said, [])
        self.assertLessEqual(banter._next_ok_at - time.monotonic(), banter.SKIP_GAP_SEC)

    def test_his_move_line_hushes_the_table_only_briefly(self):
        import rau.games.kittens.player as player_mod

        self.addCleanup(player_mod.reset_speech)
        self.answer("too soon.")
        self.look()
        self.user_moved()
        # His move line is going out right now: a proactive line on top of it
        # would read as a stutter.
        player_mod._spoke_at = time.monotonic()  # noqa: SLF001 — the stamp table_talk sets
        self.look()
        self.assertEqual(self.said, [])
        # That hush is the short floor, not the full gap: once it has passed,
        # the table is fair game again.
        self.answer("and we are back.")
        player_mod._spoke_at = (  # noqa: SLF001
            time.monotonic() - banter.LAST_SPOKE_GAP_SEC - 0.5
        )
        self.look()
        self.assertEqual(self.said, ["and we are back."])


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

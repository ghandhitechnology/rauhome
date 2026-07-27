"""
The table, the tools, and the loop that keeps Rau moving.

The engine is proven elsewhere. What is proven here is the wiring around it: that
a tool call deals a game, that an illegal move comes back with the legal ones
attached instead of an exception, that the state Rau is handed appears in his
system prompt only while a game is live, and that the pump actually takes his
turn for him and finishes the game.

The model is replaced with a stub that plays the first legal move. Nothing here
touches the network.

Run: python -m unittest tests.test_kittens_session -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.events import BUS  # noqa: E402
from rau.games.kittens import engine as engine_mod  # noqa: E402
from rau.games.kittens import session, tools  # noqa: E402
from rau.games.kittens.deck import EXPLODING_KITTEN  # noqa: E402
from rau.games.kittens.engine import PHASE_OVER, RAU, USER  # noqa: E402


class Recorder:
    """Collect bus events for the duration of a test."""

    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if event.get("kind") in self._kinds:
            self.events.append(event)

    def kinds(self) -> List[str]:
        return [e["kind"] for e in self.events]


def isolate_memory(case: unittest.TestCase) -> None:
    """
    Point the diary and the running tally at a temporary directory.

    Without this a test run leaves real wins in `memories/games.json` and real
    entries in the diary, and Rau spends the rest of the week telling you he is
    up seven games to nothing. Registered as a cleanup, so it unwinds even when
    the test fails.
    """
    import rau.paths as paths_mod
    from rau.memory import store as memory_store

    tmp = tempfile.mkdtemp(prefix="rau-kittens-")
    real_games = paths_mod.GAMES_FILE
    real_diary = memory_store.append_diary
    real_trace = memory_store.append_trace
    paths_mod.GAMES_FILE = Path(tmp) / "games.json"
    memory_store.append_diary = lambda *a, **k: Path(tmp) / "diary"
    memory_store.append_trace = lambda *a, **k: Path(tmp) / "trace"

    def restore() -> None:
        paths_mod.GAMES_FILE = real_games
        memory_store.append_diary = real_diary
        memory_store.append_trace = real_trace
        shutil.rmtree(tmp, ignore_errors=True)

    case.addCleanup(restore)
    case.tmp_games = paths_mod.GAMES_FILE


def deal_past_the_kitten() -> None:
    """
    Deal, then sink the Exploding Kitten to the bottom of the deck.

    One deal in thirty-seven puts the kitten on top, and drawing it parks the
    game in `awaiting_defuse` waiting on *you* — so Rau correctly never gets a
    turn. That is right behaviour and a wrong fixture for any test about whose
    turn it is, so the coin flip is removed rather than tolerated.
    """
    tools.run_tool("start_kittens", {})
    game = session.current()
    assert game is not None
    game.draw.remove(EXPLODING_KITTEN)
    game.draw.append(EXPLODING_KITTEN)


def quiesce() -> None:
    """
    Clear the table and wait for any in-flight turn to land.

    Without this a turn thread from one test is still running when the next one
    deals, and the shared pump state it touches on the way out makes unrelated
    tests fail intermittently.
    """
    session.end("test over")
    deadline = time.time() + 5
    while session._thinking.is_set() and time.time() < deadline:
        time.sleep(0.02)
    session._stalls = 0
    session._decided.clear()


class GameHarness(unittest.TestCase):
    """Base: no real model, no real waiting, no game left on the table."""

    def setUp(self) -> None:
        isolate_memory(self)
        self._window = engine_mod.NOPE_WINDOW_MS
        engine_mod.NOPE_WINDOW_MS = 1  # a window nobody has to sit through
        self.turns = 0
        import rau.face.brain as brain_mod
        import rau.games.kittens.agent as agent_mod

        self._real_chat = brain_mod.chat_streaming
        self._real_nope = agent_mod.decide_nope
        self._brain = brain_mod
        self._agent = agent_mod

        def fake_turn(user_text: str, **kwargs: Any) -> str:
            """Stand-in for a face turn: play the first thing that is legal."""
            self.turns += 1
            game = session.current()
            if not game:
                return "no game"
            seat = game.awaiting_seat or game.current
            moves = game.legal_moves(seat)
            if not moves:
                return "nothing to do"
            move = dict(moves[0])
            if move["move"] == "combo" and "named_card" in move:
                move["named_card"] = "skip"
            if move["move"] == "insert_kitten":
                move["index"] = 0
            tools.run_tool("play_kittens_card", move)
            return "your move"

        brain_mod.chat_streaming = fake_turn
        agent_mod.decide_nope = lambda game: False

    def tearDown(self) -> None:
        quiesce()
        engine_mod.NOPE_WINDOW_MS = self._window
        self._brain.chat_streaming = self._real_chat
        self._agent.decide_nope = self._real_nope

    def settle(self, seconds: float = 6.0) -> None:
        """Let the pump work until the game stops changing or ends."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            game = session.current()
            if not game or game.phase == PHASE_OVER:
                return
            if game.phase != PHASE_OVER and game.current == USER and not game.awaiting_seat:
                if game.phase == engine_mod.PHASE_PLAYING:
                    return
            time.sleep(0.05)


class Dealing(GameHarness):
    def test_the_tool_deals_and_announces(self):
        rec = Recorder("game_started", "game_state")
        result = tools.run_tool("start_kittens", {})
        self.assertTrue(result["ok"])
        self.assertIn("game_started", rec.kinds())
        state = result["state"]
        self.assertEqual(state["seat"], USER)
        self.assertEqual(len(state["hand"]), 8)
        self.assertEqual(state["hand_counts"], {USER: 8, RAU: 8})
        self.assertEqual(state["current"], USER, "you go first")

    def test_a_second_deal_is_refused_rather_than_silently_replacing(self):
        tools.run_tool("start_kittens", {})
        again = tools.run_tool("start_kittens", {})
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "game_in_progress")

    def test_no_table_means_no_moves(self):
        result = tools.run_tool("play_kittens_card", {"move": "draw"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_game")

    def test_ending_clears_the_table(self):
        tools.run_tool("start_kittens", {})
        tools.run_tool("end_kittens", {})
        self.assertFalse(session.active())
        self.assertIsNone(session.state())


class Refusals(GameHarness):
    def test_an_illegal_move_comes_back_with_the_legal_ones(self):
        tools.run_tool("start_kittens", {})
        result = session.apply_move(USER, {"move": "play", "card": "defuse"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unplayable")
        self.assertTrue(result["legal_moves"], "corrected, not just refused")
        self.assertIn({"move": "draw"}, result["legal_moves"])

    def test_an_unknown_move_is_refused_the_same_way(self):
        tools.run_tool("start_kittens", {})
        result = session.apply_move(USER, {"move": "flip_the_table"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unknown_move")

    def test_a_malformed_combo_does_not_raise(self):
        tools.run_tool("start_kittens", {})
        result = session.apply_move(USER, {"move": "combo", "cards": "not a list"})
        self.assertFalse(result["ok"])

    def test_rau_cannot_move_out_of_turn(self):
        tools.run_tool("start_kittens", {})
        result = tools.run_tool("play_kittens_card", {"move": "draw"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "not_your_turn")


class Context(GameHarness):
    def test_the_fragment_is_absent_between_games(self):
        self.assertEqual(session.prompt_fragment(), "")

    def test_the_fragment_appears_in_the_system_prompt_during_a_game(self):
        from rau.face import brain

        tools.run_tool("start_kittens", {})
        prompt = brain._system_prompt()
        self.assertIn("Exploding Kittens on the table", prompt)
        self.assertIn("Your hand", prompt)

    def test_it_disappears_again_when_the_table_is_cleared(self):
        from rau.face import brain

        tools.run_tool("start_kittens", {})
        tools.run_tool("end_kittens", {})
        self.assertNotIn("Exploding Kittens on the table", brain._system_prompt())

    def test_the_game_tools_are_reachable_on_the_first_voice_round(self):
        from rau.face import brain

        names = {
            t["function"]["name"]
            for t in brain._tools_for_turn(voice=True, round_idx=0, user_text="let's play")
        }
        self.assertTrue(tools.TOOL_NAMES <= names, "asking to play must work first time")


class ThePump(GameHarness):
    def test_rau_takes_his_own_turn(self):
        deal_past_the_kitten()
        session.apply_move(USER, {"move": "draw"})
        deadline = time.time() + 8
        while time.time() < deadline and self.turns == 0:
            time.sleep(0.05)
        self.assertGreater(self.turns, 0, "the pump never handed him the table")

    def test_a_whole_game_plays_itself_out(self):
        tools.run_tool("start_kittens", {})
        deadline = time.time() + 45
        while time.time() < deadline:
            game = session.current()
            if not game or game.phase == PHASE_OVER:
                break
            seat = game.awaiting_seat or game.current
            if seat == USER:
                moves = game.legal_moves(USER)
                if moves:
                    move = dict(moves[-1])  # the last legal move is always "draw"
                    if move["move"] == "insert_kitten":
                        move["index"] = 0
                    if move["move"] == "combo" and "named_card" in move:
                        move["named_card"] = "skip"
                    session.apply_move(USER, move)
            time.sleep(0.05)
        game = session.current()
        self.assertIsNotNone(game)
        self.assertEqual(game.phase, PHASE_OVER, "the game never finished")
        self.assertIn(game.winner, (USER, RAU))

    def test_the_result_is_broadcast_and_written_down(self):
        rec = Recorder("game_over")
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.concede(USER)
        deadline = time.time() + 5
        while time.time() < deadline and not rec.events:
            time.sleep(0.05)
        self.assertTrue(rec.events, "the table never announced the result")
        self.assertEqual(rec.events[0]["winner"], RAU)
        # Written to the harness's temporary path, never to the real diary.
        self.assertTrue(self.tmp_games.exists(), "the tally was never written")
        self.assertIn('"wins": 1', self.tmp_games.read_text(encoding="utf-8"))


class HubRoutes(GameHarness):
    """The four endpoints the page actually calls."""

    def client(self):
        from fastapi.testclient import TestClient
        from rau.hub.server import app

        # TestClient hard-codes "testserver" as the Host; the hub only answers a
        # loopback one, exactly as a browser on this machine would send.
        return TestClient(app, base_url="http://127.0.0.1:8765")

    def test_the_table_is_empty_until_it_is_dealt(self):
        client = self.client()
        body = client.get("/api/game/kittens").json()
        self.assertTrue(body["ok"])
        self.assertIsNone(body["state"])

    def test_dealing_and_reading_back_agree(self):
        client = self.client()
        dealt = client.post("/api/game/kittens").json()
        self.assertTrue(dealt["ok"])
        fetched = client.get("/api/game/kittens").json()
        self.assertEqual(fetched["state"]["game_id"], dealt["state"]["game_id"])
        self.assertEqual(len(fetched["state"]["hand"]), 8)

    def test_dealing_twice_returns_the_same_table(self):
        client = self.client()
        first = client.post("/api/game/kittens").json()
        second = client.post("/api/game/kittens").json()
        self.assertEqual(first["state"]["game_id"], second["state"]["game_id"])

    def test_a_move_comes_back_with_the_new_table(self):
        client = self.client()
        client.post("/api/game/kittens")
        response = client.post("/api/game/kittens/move", json={"move": "draw"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_an_illegal_move_is_a_400_that_explains_itself(self):
        client = self.client()
        client.post("/api/game/kittens")
        response = client.post(
            "/api/game/kittens/move", json={"move": "play", "card": "defuse"}
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "unplayable")
        self.assertTrue(body["legal_moves"])

    def test_the_response_carries_no_hidden_state(self):
        client = self.client()
        body = client.post("/api/game/kittens").json()
        raw = client.get("/api/game/kittens").text
        self.assertNotIn('"hands"', raw)
        self.assertNotIn('"draw"', raw)
        self.assertEqual(body["state"]["seat"], USER)

    def test_deleting_clears_the_table(self):
        client = self.client()
        client.post("/api/game/kittens")
        client.delete("/api/game/kittens")
        self.assertIsNone(client.get("/api/game/kittens").json()["state"])


class Stalling(unittest.TestCase):
    """A model that talks without playing must not be asked forever."""

    def setUp(self) -> None:
        isolate_memory(self)
        self._window = engine_mod.NOPE_WINDOW_MS
        engine_mod.NOPE_WINDOW_MS = 1
        self.calls = 0
        import rau.face.brain as brain_mod
        import rau.games.kittens.agent as agent_mod

        self._brain, self._agent = brain_mod, agent_mod
        self._real_chat = brain_mod.chat_streaming
        self._real_nope = agent_mod.decide_nope

        def mute_turn(user_text: str, **kwargs: Any) -> str:
            self.calls += 1
            return "hm."  # says something, touches nothing

        brain_mod.chat_streaming = mute_turn
        agent_mod.decide_nope = lambda game: False
        session._stalls = 0
        session._decided.clear()

    def tearDown(self) -> None:
        quiesce()
        engine_mod.NOPE_WINDOW_MS = self._window
        self._brain.chat_streaming = self._real_chat
        self._agent.decide_nope = self._real_nope

    def test_the_pump_gives_up_instead_of_paying_forever(self):
        rec = Recorder("game_stalled")
        deal_past_the_kitten()
        session.apply_move(USER, {"move": "draw"})
        deadline = time.time() + 8
        while time.time() < deadline and not rec.events:
            time.sleep(0.05)
        self.assertTrue(rec.events, "it never noticed he was stuck")
        settled = self.calls
        time.sleep(1.0)
        self.assertEqual(self.calls, settled, "it kept asking after giving up")
        self.assertLessEqual(settled, session.MAX_STALLS + 1)

    def test_a_human_move_wakes_him_back_up(self):
        deal_past_the_kitten()
        session.apply_move(USER, {"move": "draw"})
        deadline = time.time() + 8
        while time.time() < deadline and session._stalls < session.MAX_STALLS:
            time.sleep(0.05)
        self.assertGreaterEqual(session._stalls, session.MAX_STALLS)
        game = session.current()
        assert game is not None
        game.current = USER  # your move again
        session.apply_move(USER, {"move": "draw"})
        self.assertEqual(session._stalls, 0, "he should be given another chance")


class Redaction(GameHarness):
    def test_what_the_hub_returns_is_the_seat_view(self):
        tools.run_tool("start_kittens", {})
        state = session.state()
        assert state is not None
        self.assertNotIn("hands", state)
        self.assertNotIn("draw", state)
        self.assertEqual(state["seat"], USER)

    def test_the_broadcast_payload_is_the_seat_view_too(self):
        rec = Recorder("game_state")
        tools.run_tool("start_kittens", {})
        self.assertTrue(rec.events)
        payload = rec.events[0]["state"]
        self.assertNotIn("hands", payload)
        self.assertNotIn("draw", payload)


if __name__ == "__main__":
    unittest.main()

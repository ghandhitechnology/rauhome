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
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.events import BUS  # noqa: E402
from rau.games.kittens import engine as engine_mod  # noqa: E402
from rau.games.kittens import session, tools  # noqa: E402
from rau.games.kittens import deck as deck_mod  # noqa: E402
from rau.games.kittens import view as view_mod  # noqa: E402
from rau.games.kittens.deck import (  # noqa: E402
    ATTACK,
    EXPLODING_KITTEN,
    FAVOR,
    SEE_THE_FUTURE,
    SHUFFLE,
    SKIP,
)
from rau.games.kittens.engine import PHASE_NOPE, PHASE_OVER, RAU, USER  # noqa: E402


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
    from rau.games.kittens import pump

    session.end("test over")
    deadline = time.time() + 5
    while pump.thinking().is_set() and time.time() < deadline:
        time.sleep(0.02)
    pump.reset_for_deal()


class GameHarness(unittest.TestCase):
    """Base: no real model, no real waiting, no game left on the table."""

    def setUp(self) -> None:
        isolate_memory(self)
        self._window = engine_mod.NOPE_WINDOW_MS
        engine_mod.NOPE_WINDOW_MS = 1  # a window nobody has to sit through
        self.turns = 0
        import rau.games.kittens.player as player_mod

        self._player = player_mod
        self._real_take = player_mod.take_turn
        self._real_nope = player_mod.decide_nope

        def fake_take(game: Any) -> None:
            """Stand-in for the player half: play the first legal move."""
            self.turns += 1
            seat = game.awaiting_seat or game.current
            if seat != RAU:
                return
            moves = game.legal_moves(RAU)
            if not moves:
                return
            # Copy the move the way the model copies the prompt listing — the
            # same fill-in the view applies, never a test-only patch.
            move = view_mod._copiable(moves[0])
            if move["move"] == "give_favor" and "card" not in move and game.hands[RAU]:
                move["card"] = game.hands[RAU][0]
            if move["move"] == "take_from_discard" and "card" not in move and game.discard:
                move["card"] = game.discard[-1]
            session.apply_move(RAU, move)

        player_mod.take_turn = fake_take
        player_mod.decide_nope = lambda game: False

    def tearDown(self) -> None:
        quiesce()
        engine_mod.NOPE_WINDOW_MS = self._window
        self._player.take_turn = self._real_take
        self._player.decide_nope = self._real_nope

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
        self.assertEqual(state["seat"], RAU, "tools return Rau's seat, not the browser's")
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

    def test_ending_a_live_game_announces_it(self):
        rec = Recorder("game_ended")
        tools.run_tool("start_kittens", {})
        tools.run_tool("end_kittens", {})
        self.assertIn("game_ended", rec.kinds())

    def test_ending_a_finished_game_still_announces_it(self):
        # A tab that opened after the result was broadcast only knows the
        # finished table; clearing it must reach that tab too.
        rec = Recorder("game_ended")
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.concede(USER)
        tools.run_tool("end_kittens", {})
        self.assertIn("game_ended", rec.kinds())


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
        self.assertIn("start_kittens", names, "asking to play must work first time")
        self.assertIn("end_kittens", names)
        self.assertNotIn(
            "play_kittens_card",
            names,
            "the talker must not play cards — that is the player half",
        )

    def test_face_tools_exclude_play_kittens_card(self):
        from rau.face import brain

        names = {t["function"]["name"] for t in brain.FACE_TOOLS}
        self.assertIn("start_kittens", names)
        self.assertIn("end_kittens", names)
        self.assertNotIn("play_kittens_card", names)

    def test_talker_fragment_has_no_legal_moves_menu(self):
        from rau.games.kittens import view as view_mod

        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        text = view_mod.talker_fragment(game, RAU)
        self.assertIn("Exploding Kittens on the table", text)
        self.assertIn("player half makes the moves", text)
        self.assertNotIn("Legal moves right now", text)


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
                    # The last legal move is always "draw"; copy it the way the
                    # model copies the listing, placeholders filled by the view.
                    move = view_mod._copiable(moves[-1])
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
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"]["seat"], USER, "HTTP stays on the human seat")

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


class GuaranteedMove(unittest.TestCase):
    """A broken player reply must still advance the table — never stall forever."""

    def setUp(self) -> None:
        isolate_memory(self)
        self._window = engine_mod.NOPE_WINDOW_MS
        engine_mod.NOPE_WINDOW_MS = 1
        import rau.games.kittens.player as player_mod

        self._player = player_mod
        self._real_ask = player_mod._ask_model
        self._real_nope = player_mod.decide_nope
        player_mod.decide_nope = lambda game: False

    def tearDown(self) -> None:
        quiesce()
        engine_mod.NOPE_WINDOW_MS = self._window
        self._player._ask_model = self._real_ask
        self._player.decide_nope = self._real_nope

    def test_garbage_model_reply_still_advances_via_fallback(self):
        self._player._ask_model = lambda prompt: "hmm I like cats"
        deal_past_the_kitten()
        game = session.current()
        assert game is not None
        before_log = len(game.log)
        session.apply_move(USER, {"move": "draw"})
        deadline = time.time() + 8
        while time.time() < deadline:
            game = session.current()
            if game and (len(game.log) > before_log + 1 or game.current == USER):
                # Rau acted (log grew) or handed the turn back.
                if game.current == USER or game.phase == PHASE_OVER:
                    break
            time.sleep(0.05)
        game = session.current()
        assert game is not None
        self.assertTrue(
            game.current == USER or game.phase == PHASE_OVER,
            "fallback never advanced the turn after a garbage reply",
        )

    def test_after_user_defuses_rau_still_gets_the_turn(self):
        """Regression for the explode-handoff stall: player always moves."""
        self._player._ask_model = lambda prompt: "not json at all"
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[USER] = [deck_mod.DEFUSE, SKIP]
        game.hands[RAU] = [SKIP, SKIP]
        game.draw = [EXPLODING_KITTEN, ATTACK, FAVOR]
        game.discard = []
        game.current = USER
        game.turns_to_take = 1
        game.phase = engine_mod.PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        session.apply_move(USER, {"move": "draw"})
        self.assertEqual(game.phase, engine_mod.PHASE_DEFUSE)
        session.apply_move(USER, {"move": "insert_kitten", "index": 0})
        self.assertEqual(game.current, RAU, "defusing still ends your turn")
        deadline = time.time() + 8
        while time.time() < deadline and game.current == RAU and game.phase != PHASE_OVER:
            time.sleep(0.05)
        self.assertTrue(
            game.current == USER or game.phase == PHASE_OVER,
            "Rau never took the turn after the user defused",
        )

    def test_fallback_defuses_with_the_placeholder_index(self):
        """
        Regression for the defuse wedge: legal_moves lists insert_kitten with a
        prose range ("0..N"), not an index. With the model down, the guaranteed
        fallback copied it verbatim, int("0..N") raised, and the pump retried
        the same guaranteed failure every two seconds forever.
        """
        rec = Recorder("game_error")
        self._player._ask_model = lambda prompt: "not json at all"
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[USER] = [SKIP]
        game.hands[RAU] = [deck_mod.DEFUSE, SKIP]
        game.draw = [EXPLODING_KITTEN, ATTACK, FAVOR]
        game.discard = []
        game.current = RAU
        game.turns_to_take = 1
        game.phase = engine_mod.PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        session.apply_move(RAU, {"move": "draw"})
        self.assertEqual(game.phase, engine_mod.PHASE_DEFUSE)
        self.assertEqual(game.awaiting_seat, RAU)
        self.assertIn("0..", str(game.legal_moves(RAU)), "the placeholder is the point")
        deadline = time.time() + 8
        while time.time() < deadline and game.phase == engine_mod.PHASE_DEFUSE:
            time.sleep(0.05)
        self.assertNotEqual(
            game.phase,
            engine_mod.PHASE_DEFUSE,
            "the fallback never placed the kitten — the table wedged in awaiting_defuse",
        )
        self.assertFalse(
            [e for e in rec.events if "fallback failed" in str(e.get("error"))],
            "the guaranteed fallback failed",
        )


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

    def test_a_human_move_still_returns_the_user_seat(self):
        tools.run_tool("start_kittens", {})
        result = session.apply_move(USER, {"move": "draw"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["seat"], USER)


class ToolObservation(GameHarness):
    """
    What the model sees in tool results: his seat, his peeks, never yours.
    """

    def setUp(self) -> None:
        super().setUp()
        # Do not let the pump spend his hand while these tests drive tools directly.
        self._player.take_turn = lambda game: None

    def _rig_rau_see_the_future(self, top: List[str], *, user_hand: Optional[List[str]] = None) -> None:
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[USER] = list(user_hand) if user_hand is not None else [SKIP]
        game.hands[RAU] = [SEE_THE_FUTURE, SKIP]
        game.draw = list(top)
        game.discard = []
        game.current = RAU
        game.turns_to_take = 1
        game.phase = engine_mod.PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        game.known_top = {USER: [], RAU: []}

    def test_tool_state_never_carries_the_human_hand(self):
        import json

        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        canary = "beard_cat"
        filler = "tacocat"
        game.hands[USER] = [canary] * 8
        game.hands[RAU] = [filler] * 8
        game.draw = [c for c in game.draw if c != canary]
        refused = tools.run_tool("start_kittens", {})
        self.assertFalse(refused["ok"])
        payload = json.dumps(refused["state"])
        self.assertNotIn(canary, payload)
        self.assertEqual(refused["state"]["seat"], RAU)
        self.assertNotIn(canary, refused["state"]["hand"])

    def test_see_the_future_pending_does_not_name_the_deck(self):
        # Hold the Nope window open: the human must actually hold a Nope, or the
        # engine closes the window immediately (they could not have Noped).
        engine_mod.NOPE_WINDOW_MS = 60_000
        top = [SKIP, ATTACK, FAVOR, SHUFFLE]
        self._rig_rau_see_the_future(top, user_hand=[deck_mod.NOPE, SKIP])
        result = tools.run_tool(
            "play_kittens_card", {"move": "play", "card": SEE_THE_FUTURE}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["seat"], RAU)
        self.assertEqual(result["state"]["phase"], PHASE_NOPE)
        self.assertEqual(result["state"]["known_top"], [])
        self.assertIn("Waiting to see if they Nope it", result["summary"])
        for card in top[:3]:
            self.assertNotIn(deck_mod.label(card), result["summary"])

    def test_see_the_future_resolved_names_the_peek(self):
        # No Nope in the human hand → the window closes at once and the peek lands
        # in the same tool result that played the card.
        top = [SKIP, ATTACK, FAVOR, SHUFFLE]
        self._rig_rau_see_the_future(top, user_hand=[SKIP])
        result = tools.run_tool(
            "play_kittens_card", {"move": "play", "card": SEE_THE_FUTURE}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["seat"], RAU)
        self.assertEqual(result["state"]["known_top"], top[:3])
        for card in top[:3]:
            self.assertIn(deck_mod.label(card), result["summary"])

        # A later move still carries the peek in state and reminds in prose.
        next_move = tools.run_tool(
            "play_kittens_card", {"move": "play", "card": SKIP}
        )
        self.assertTrue(next_move["ok"])
        self.assertEqual(next_move["state"]["seat"], RAU)
        self.assertEqual(next_move["state"]["known_top"], top[:3])
        for card in top[:3]:
            self.assertIn(deck_mod.label(card), next_move["summary"])

    def test_draw_names_the_card_he_got(self):
        tools.run_tool("start_kittens", {})
        game = session.current()
        assert game is not None
        game.hands[USER] = [SKIP]
        game.hands[RAU] = [SKIP]
        game.draw = [ATTACK, FAVOR, SHUFFLE]
        game.discard = []
        game.current = RAU
        game.turns_to_take = 1
        game.phase = engine_mod.PHASE_PLAYING
        game.pending = None
        game.awaiting_seat = None
        result = tools.run_tool("play_kittens_card", {"move": "draw"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["seat"], RAU)
        self.assertIn(deck_mod.label(ATTACK), result["summary"])
        self.assertIn(ATTACK, result["state"]["hand"])


if __name__ == "__main__":
    unittest.main()

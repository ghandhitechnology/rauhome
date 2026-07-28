"""
The one board on the table: setting it up, taking it away, booking the result.

The rules are `board.py`'s problem and Stockfish's strength is `level.py`'s. What
is proven here is the wiring that sits above both of them, and every property in
this file is one that fails silently rather than loudly when it breaks.

* A finished game must be booked **once**. Two writers can reach `_finish` — the
  pump noticing the position is over, and `end()` sweeping the board away in the
  same breath — and a second booking moves the elo twice, writes a second PGN,
  and tells the page the game finished twice.
* Every event must carry `game="chess"`. There are two games live in this app
  now and one shared `game_state` channel into the browser; an event without the
  discriminator lands in the kittens store and redraws a hand of cards over a
  chessboard.
* `browser_view` must be exactly the contract's key set and must never grow a
  `legal_moves`. The user declined move hints. This test is how that decision
  survives the next person who thinks highlighting would be helpful.
* One payload must describe one position. The pump moves pieces from its own
  thread while the page is reading; a view assembled a getter at a time can hand
  the browser a FEN from before the move and a `turn` from after it.

Nothing here touches the network. Almost nothing here starts Stockfish either —
the pump's turn thread is a no-op for every test but the last class, which takes
one real turn against the local binary to prove the four layers actually meet,
and skips itself where there is no binary to take it against.

Run: python -m unittest tests.test_chess_session -v
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.events import BUS  # noqa: E402
from rau.games.chess import banter, binary, journal, level, player, pump  # noqa: E402
from rau.games.chess import session, timing  # noqa: E402
from rau.games.chess import board as board_mod  # noqa: E402
from rau.games.chess import view as view_mod  # noqa: E402
from rau.games.chess.board import (  # noqa: E402
    PHASE_OVER,
    PHASE_PLAYING,
    PHASE_THINKING,
    RAU,
    USER,
)

#: The wire format, spelled out. Set equality against this, never a subset check:
#: an extra key is exactly as much of a contract break as a missing one, and the
#: extra key everyone is tempted to add is `legal_moves`.
CONTRACT_KEYS = {
    "game_id",
    "phase",
    "fen",
    "turn",
    "rau_color",
    "user_color",
    "your_turn",
    "moves",
    "last_move",
    "check_square",
    "thinking",
    "offer",
    "result",
    "winner",
    "over_reason",
    "can_claim_draw",
    "log",
}

#: The names the page listens for. Every one of them has to say which game it is
#: about, because both games emit all five.
GAME_EVENTS = {"game_started", "game_state", "game_over", "game_ended", "game_error"}


class Recorder:
    """Collect bus events for the duration of one test, then get out of the way."""

    def __init__(self, case: unittest.TestCase, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)
        case.addCleanup(BUS.off, "*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def kinds(self) -> List[str]:
        return [e["kind"] for e in self.events]

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("kind") == kind]


def isolate_memory(case: unittest.TestCase) -> None:
    """
    Point every path this feature writes to at a temporary directory.

    `memories/games.json` holds the real elo and the real kittens record, and
    `memories/games/` holds the game that is actually on this machine's table
    right now. A test run that books a result against either of them destroys
    user data that nothing regenerates. Registered as a cleanup so it unwinds
    even when the test fails, and so does the tmpdir.
    """
    import rau.paths as paths_mod
    from rau.memory import store as memory_store

    tmp = Path(tempfile.mkdtemp(prefix="rau-chess-"))
    real_file = paths_mod.GAMES_FILE
    real_dir = paths_mod.GAMES_DIR
    real_diary = memory_store.append_diary
    real_trace = memory_store.append_trace

    paths_mod.GAMES_FILE = tmp / "games.json"
    paths_mod.GAMES_DIR = tmp / "games"
    memory_store.append_diary = lambda *a, **k: tmp / "diary"
    memory_store.append_trace = lambda *a, **k: tmp / "trace"

    def restore() -> None:
        paths_mod.GAMES_FILE = real_file
        paths_mod.GAMES_DIR = real_dir
        memory_store.append_diary = real_diary
        memory_store.append_trace = real_trace
        shutil.rmtree(tmp, ignore_errors=True)

    case.addCleanup(restore)
    case.tmp = tmp
    case.tmp_games = paths_mod.GAMES_FILE


def silence_the_engine(case: unittest.TestCase) -> None:
    """
    Leave the pump running, but never let it open a chess engine.

    The pump is load-bearing here — it is the second caller of `_finish`, and the
    idempotence tests are about it racing `end()` — so it keeps ticking. What it
    must not do is start Stockfish, so the turn thread is the one thing replaced.
    """
    real_turn = pump._run_rau_turn  # noqa: SLF001

    def no_turn() -> None:
        pump.thinking().clear()

    pump._run_rau_turn = no_turn  # noqa: SLF001
    case.addCleanup(setattr, pump, "_run_rau_turn", real_turn)


def silence_the_providers(case: unittest.TestCase) -> None:
    """
    Both halves that can reach a model answer SKIP instead.

    `player._ask` and `banter._ask` are the only two doors out of this feature
    onto the network, and the pump walks past the second one on every tick. SKIP
    is the answer that costs nothing and leaves no line behind.
    """
    for module in (player, banter):
        real = module._ask  # noqa: SLF001
        module._ask = lambda prompt: "SKIP"  # noqa: SLF001
        case.addCleanup(setattr, module, "_ask", real)


def quicken_the_pump(case: unittest.TestCase) -> None:
    """
    Run the pump's loop at fifty ticks a second rather than seven.

    Several tests below prove an *absence* — that a second `game_over` never goes
    out, that a booked game is never filed twice — and the only way to prove one
    is to give the pump a few goes at it and then look. At the shipped 150ms
    cadence that is half a second of sitting still per test and there are a dozen
    of them. `POLL_SEC` is read afresh on every pass of the loop, so shortening it
    buys each `settle()` *more* ticks in a third of the wall clock: faster and
    strictly harder to pass, which is the only sort of speed-up worth having here.
    """
    real = pump.POLL_SEC
    pump.POLL_SEC = 0.02
    case.addCleanup(setattr, pump, "POLL_SEC", real)


def park_the_pump(limit: float = 5.0) -> None:
    """
    Stop the pump and wait for the thread itself to be gone.

    A test that drives `banter` by hand is racing a pump that calls the same
    function over the same cooldowns, so it has to be put away first — and
    "sleep a couple of poll intervals and hope" is precisely the shape that flaps
    on a loaded machine. Joining the thread says the same thing exactly.
    """
    pump.stop()
    thread = pump._pump  # noqa: SLF001 — there is no public handle, and the join is the point
    if thread is not None:
        thread.join(limit)


def quiesce() -> None:
    """Clear the table and let any in-flight turn notice that it has been."""
    session.end("test over")
    deadline = time.time() + 5
    while pump.thinking().is_set() and time.time() < deadline:
        time.sleep(0.02)
    park_the_pump()
    player.reset()
    banter.reset()
    journal.clear()


class BoardHarness(unittest.TestCase):
    """A temporary memories directory, a live pump, and no engine behind it."""

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_engine(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)

    def board(self, colour: str = "black") -> Any:
        """Set the pieces up and hand back the live game object."""
        session.start(rau_color=colour)
        game = session.current()
        assert game is not None
        return game

    def settle(self, seconds: float = 0.15) -> None:
        """
        Give the pump several ticks to do whatever it was going to do.

        Seven of them at the quickened cadence `quicken_the_pump` sets, against
        the three the shipped 150ms would have fitted into half a second. Every
        caller is checking that something did *not* happen, so more ticks is a
        stronger assertion and the shorter wall clock is free.
        """
        time.sleep(seconds)


class Lifecycle(BoardHarness):
    def test_there_is_no_board_out_until_one_is_set_up(self):
        self.assertFalse(session.active())
        self.assertIsNone(session.current())
        self.assertIsNone(session.state())

    def test_setting_the_pieces_up_gives_rau_black_and_the_user_the_first_move(self):
        """Black by default: someone sitting down opposite you lets you open."""
        view = session.start()
        self.assertTrue(session.active())
        self.assertEqual(view["rau_color"], "black")
        self.assertEqual(view["user_color"], "white")
        self.assertEqual(view["turn"], "white")
        self.assertTrue(view["your_turn"])
        self.assertEqual(view["phase"], PHASE_PLAYING)
        self.assertEqual(view["moves"], [])

    def test_asking_for_white_is_honoured_and_nonsense_is_not(self):
        self.assertEqual(session.start(rau_color="white")["rau_color"], "white")
        session.end("next")
        self.assertEqual(session.start(rau_color="mauve")["rau_color"], "black")

    def test_current_and_state_agree_about_the_same_board(self):
        game = self.board()
        state = session.state()
        assert state is not None
        self.assertEqual(state["game_id"], game.game_id)

    def test_taking_the_board_away_leaves_nothing_behind(self):
        self.board()
        session.end("cleared")
        self.assertFalse(session.active())
        self.assertIsNone(session.current())
        self.assertIsNone(session.state())
        self.assertEqual(session.prompt_fragment(), "")

    def test_a_live_game_swept_away_announces_that_it_ended_not_that_it_was_won(self):
        rec = Recorder(self, "game_ended", "game_over")
        self.board()
        session.end("they walked off")
        self.assertEqual(rec.kinds(), ["game_ended"])
        self.assertEqual(rec.of("game_ended")[0]["reason"], "they walked off")

    def test_ending_an_empty_table_is_harmless(self):
        self.assertEqual(session.end("nothing there"), {"ok": True})

    def test_the_talker_fragment_appears_and_disappears_with_the_board(self):
        self.assertEqual(session.prompt_fragment(), "")
        self.board()
        self.assertIn("chess", session.prompt_fragment().lower())
        session.end("done")
        self.assertEqual(session.prompt_fragment(), "")


class BookingTheResult(BoardHarness):
    """
    A finished game is written down once, by whoever gets there first.

    `end()` and the pump both call `_finish`, and on a game that ended a
    heartbeat before the board was swept they both get there. Two bookings is
    two elo adjustments, two PGN entries and two `game_over` frames, and none of
    those is visible until the score is already wrong.
    """

    def pgn_games(self) -> int:
        path = board_mod.pgn_path()
        if not path.exists():
            return 0
        return path.read_text(encoding="utf-8").count("[Event ")

    def test_ending_an_already_over_game_books_it_exactly_once(self):
        rec = Recorder(self, "game_over")
        self.board()
        result = session.apply_move(USER, {"move": "resign"})
        self.assertTrue(result["ok"])
        # The gap the pump would otherwise book it in: put the board away in the
        # same breath, then let the pump tick several more times over the top.
        session.end("cleared right after")
        self.settle()

        self.assertEqual(len(rec.of("game_over")), 1, "the result was announced twice")
        record = level.tally()
        self.assertEqual(record["wins"], 1)
        self.assertEqual(record["losses"], 0)
        self.assertEqual(record["draws"], 0)
        self.assertEqual(self.pgn_games(), 1, "the game was filed twice")

    def test_the_pump_alone_books_a_game_that_ended_on_the_board(self):
        rec = Recorder(self, "game_over")
        self.board()
        session.apply_move(USER, {"move": "resign"})
        deadline = time.time() + 5
        while time.time() < deadline and not rec.of("game_over"):
            time.sleep(0.02)
        self.assertEqual(len(rec.of("game_over")), 1)
        self.assertEqual(rec.of("game_over")[0]["winner"], RAU)
        self.assertEqual(rec.of("game_over")[0]["result"], "0-1", "rau had black")

    def test_finish_is_idempotent_under_repeated_calls(self):
        rec = Recorder(self, "game_over")
        game = self.board()
        session.apply_move(USER, {"move": "resign"})
        for _ in range(5):
            session._finish(game)  # noqa: SLF001 — the second caller, on purpose
        self.settle()
        self.assertEqual(len(rec.of("game_over")), 1)
        self.assertEqual(level.tally()["wins"], 1)
        self.assertEqual(self.pgn_games(), 1)

    def test_finish_is_idempotent_when_two_threads_reach_it_together(self):
        """The real shape of the race: the pump's tick and the HTTP thread."""
        rec = Recorder(self, "game_over")
        game = self.board()
        session.apply_move(USER, {"move": "resign"})
        start = threading.Event()

        def book() -> None:
            start.wait()
            session._finish(game)  # noqa: SLF001

        threads = [threading.Thread(target=book) for _ in range(6)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(5)
        self.settle()
        self.assertEqual(len(rec.of("game_over")), 1)
        self.assertEqual(level.tally()["wins"], 1)

    def test_a_finished_game_is_not_left_on_disk_to_be_resumed(self):
        self.board()
        session.apply_move(USER, {"move": "resign"})
        session.end("cleared")
        self.settle()
        self.assertFalse(
            board_mod.current_path().exists(),
            "a booked game would come back on the next boot",
        )

    def test_the_kittens_record_survives_a_finished_chess_game(self):
        """One `games.json`, two games. Booking one must not flatten the other."""
        self.tmp_games.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_games.write_text(
            json.dumps({"kittens": {"wins": 4, "losses": 2}}), encoding="utf-8"
        )
        self.board()
        session.apply_move(USER, {"move": "resign"})
        session.end("cleared")
        self.settle()
        data = json.loads(self.tmp_games.read_text(encoding="utf-8"))
        self.assertEqual(data["kittens"], {"wins": 4, "losses": 2})
        self.assertEqual(data["chess"]["wins"], 1)


class TheLadder(BoardHarness):
    """
    Beating him makes him stronger. It is the one number that is easy to invert
    and impossible to notice inverted, because a Rau who eases off every time you
    win still feels like an opponent — just a worse one, forever.
    """

    def test_the_user_winning_makes_rau_stronger(self):
        self.board()
        session.apply_move(RAU, {"move": "resign"})  # he gives it up: they won
        session.end("cleared")
        self.settle()
        record = level.tally()
        self.assertEqual(record["losses"], 1)
        self.assertEqual(record["elo"], level.START + level.DECISIVE)
        self.assertGreater(
            level.current(),
            level.START,
            "you won and he got easier — the ladder is backwards",
        )

    def test_rau_winning_makes_him_ease_off(self):
        self.board()
        session.apply_move(USER, {"move": "resign"})
        session.end("cleared")
        self.settle()
        record = level.tally()
        self.assertEqual(record["wins"], 1)
        self.assertEqual(record["elo"], level.START - level.DECISIVE)
        self.assertLess(level.current(), level.START)

    def test_a_draw_barely_moves_him_at_all(self):
        game = self.board()
        session.apply_move(USER, {"move": "offer_draw"})
        session.apply_move(RAU, {"move": "accept_draw"})
        self.assertEqual(game.result, "1/2-1/2")
        session.end("cleared")
        self.settle()
        record = level.tally()
        self.assertEqual(record["draws"], 1)
        self.assertEqual(record["elo"], level.START, "a drawn game from centre stays")

    def test_the_elo_the_next_game_opens_at_is_the_one_just_recorded(self):
        self.board()
        session.apply_move(RAU, {"move": "resign"})
        session.end("cleared")
        self.settle()
        game = self.board()
        self.assertEqual(game.elo, level.START + level.DECISIVE)


class TheDiscriminator(BoardHarness):
    """
    Every frame says which game it is about.

    Both games emit `game_started`, `game_state`, `game_over`, `game_ended` and
    `game_error` on the same bus and down the same socket. A frame that arrives
    without `game` is accepted by whichever store looks at it first, which is how
    a chess move ends up redrawing a hand of cards.
    """

    def test_every_event_a_live_board_emits_names_chess(self):
        rec = Recorder(self, *GAME_EVENTS)
        game = self.board()
        session.apply_move(USER, {"move": "move", "from": "e2", "to": "e4"})
        session.apply_move(RAU, {"move": "move", "from": "e7", "to": "e5"})
        session.apply_move(USER, {"move": "resign"})
        session.end("cleared")
        self.settle()

        self.assertTrue(rec.events, "the board never said anything at all")
        for event in rec.events:
            self.assertEqual(
                event.get("game"),
                "chess",
                f"{event['kind']} went out without a game — it will cross-wire the "
                "two stores in the browser",
            )
        kinds = set(rec.kinds())
        self.assertIn("game_started", kinds)
        self.assertIn("game_state", kinds)
        self.assertIn("game_over", kinds)
        self.assertIsNotNone(game.result)

    def test_every_game_event_in_the_package_source_carries_the_discriminator(self):
        """
        The four tests above can only see the paths they walk. This one reads
        every `BUS.emit` of a `game_*` event in the package, so an emit added on
        a path nobody exercises still has to name the game.
        """
        package = Path(session.__file__).parent
        pattern = re.compile(r"BUS\.emit\(\s*\"(game_[a-z_]+)\"(.*?)\)", re.S)
        seen = 0
        for path in sorted(package.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for kind, args in pattern.findall(source):
                seen += 1
                self.assertIn(
                    'game="chess"',
                    args,
                    f"{path.name} emits {kind} without saying which game it is",
                )
        self.assertGreater(seen, 0, "the regex stopped matching the emit calls")


class TheWireFormat(BoardHarness):
    def test_the_view_is_exactly_the_contract_key_set(self):
        game = self.board()
        self.assertEqual(set(view_mod.browser_view(game).keys()), CONTRACT_KEYS)

    def test_the_key_set_does_not_change_once_the_game_is_over(self):
        game = self.board()
        session.apply_move(USER, {"move": "resign"})
        self.assertEqual(set(view_mod.browser_view(game).keys()), CONTRACT_KEYS)
        self.assertEqual(view_mod.browser_view(game)["phase"], PHASE_OVER)

    def test_the_key_set_does_not_change_while_he_is_thinking(self):
        game = self.board()
        with player._lock:  # noqa: SLF001 — standing in for a running hover script
            player._think_game = game.game_id  # noqa: SLF001
            player._hover = "d4"  # noqa: SLF001
        self.addCleanup(player.reset)
        view = view_mod.browser_view(game)
        self.assertEqual(set(view.keys()), CONTRACT_KEYS)
        self.assertEqual(view["phase"], PHASE_THINKING)
        self.assertEqual(view["thinking"], {"hover": "d4"})

    def test_there_is_no_legal_moves_key_anywhere_in_the_payload(self):
        """
        The user declined move hints. A `legal_moves` field is how they come
        back: nobody adds a highlight to the client, somebody adds a list to the
        server and the highlight follows a week later.
        """
        game = self.board()
        session.apply_move(USER, {"move": "move", "from": "e2", "to": "e4"})
        view = view_mod.browser_view(game)
        self.assertNotIn("legal_moves", view)
        self.assertNotIn("legal_moves", json.dumps(view))
        self.assertNotIn("legal", json.dumps(view).lower())

    def test_a_refused_move_carries_no_move_menu_either(self):
        """
        Kittens answers an illegal move with the legal ones attached. Chess must
        not: the refusal is a sentence he says out loud, and nothing else.
        """
        self.board()
        result = session.apply_move(USER, {"move": "move", "from": "e2", "to": "e5"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "illegal_move")
        self.assertEqual(set(result.keys()), {"ok", "error", "code"})
        self.assertNotIn("legal_moves", json.dumps(result))

    def test_the_refusal_reads_as_something_he_says_rather_than_an_error(self):
        self.board()
        refusal = session.apply_move(USER, {"move": "move", "from": "e4", "to": "e5"})
        self.assertEqual(refusal["code"], "bad_square")
        self.assertEqual(refusal["error"], refusal["error"].lower())
        self.assertNotIn("invalid", refusal["error"])

    def test_the_log_is_the_feed_beside_the_board(self):
        game = self.board()
        session.apply_move(USER, {"move": "move", "from": "d2", "to": "d4"})
        view = view_mod.browser_view(game)
        self.assertTrue(view["log"])
        self.assertEqual(set(view["log"][0].keys()), {"seat", "text", "at"})
        self.assertEqual(view["log"][-1]["text"], "d4")

    def test_the_view_says_who_moved_last_and_in_which_notation(self):
        game = self.board()
        session.apply_move(USER, {"move": "move", "from": "g1", "to": "f3"})
        view = view_mod.browser_view(game)
        self.assertEqual(view["last_move"], {"from": "g1", "to": "f3", "san": "Nf3"})
        self.assertEqual(view["moves"], ["Nf3"])
        self.assertEqual(view["turn"], "black")
        self.assertFalse(view["your_turn"])
        self.assertIsNone(view["check_square"])


class OnePayloadIsOnePosition(BoardHarness):
    """
    The view is a single locked snapshot, and this is the test that says why.

    `board.snapshot()` takes the game's lock once and reads every field under it.
    Rebuild it as a series of getters — which is the obvious refactor, and reads
    better — and a page polling during the pump's move gets a FEN from before it
    with a `turn` from after it, and draws a board where it is nobody's move.
    """

    def assert_one_position(self, payload: Dict[str, Any]) -> None:
        position = chess.Board(payload["fen"])
        turn = "white" if position.turn == chess.WHITE else "black"
        self.assertEqual(turn, payload["turn"], "the fen and the turn disagree")
        self.assertEqual(
            len(payload["moves"]) % 2 == 0,
            payload["turn"] == "white",
            "the move list and the side to move disagree",
        )
        if payload["moves"]:
            self.assertEqual(payload["last_move"]["san"], payload["moves"][-1])
        else:
            self.assertIsNone(payload["last_move"])
        if payload["phase"] == PHASE_OVER:
            self.assertIsNotNone(payload["result"])
        else:
            self.assertIsNone(payload["result"])
            self.assertEqual(
                payload["your_turn"],
                payload["turn"] == payload["user_color"]
                and payload["phase"] == PHASE_PLAYING,
            )

    def test_a_view_read_while_moves_are_landing_is_never_half_of_two_positions(self):
        game = self.board()
        stop = threading.Event()
        problems: List[str] = []
        reads = [0]

        def hammer() -> None:
            while not stop.is_set():
                payload = session.state()
                if payload is None:
                    continue
                reads[0] += 1
                try:
                    self.assert_one_position(payload)
                except AssertionError as exc:
                    problems.append(f"{exc}\n{payload}")
                    return

        readers = [
            threading.Thread(target=hammer, name=f"chess-view-{i}", daemon=True)
            for i in range(3)
        ]
        for reader in readers:
            reader.start()

        mirror = chess.Board()
        try:
            for _ in range(30):
                if game.phase == PHASE_OVER or problems:
                    break
                seat = USER if mirror.turn == chess.WHITE else RAU
                move = sorted(
                    (m for m in mirror.legal_moves if m.promotion is None),
                    key=lambda m: m.uci(),
                )[0]
                result = session.apply_move(
                    seat,
                    {
                        "move": "move",
                        "from": chess.square_name(move.from_square),
                        "to": chess.square_name(move.to_square),
                    },
                )
                self.assertTrue(result["ok"], result)
                mirror.push(move)
        finally:
            stop.set()
            for reader in readers:
                reader.join(2)

        self.assertEqual(problems, [], "a payload described two positions at once")
        self.assertGreater(reads[0], 50, "the readers never actually looked")

    def test_the_snapshot_reads_every_field_under_one_lock(self):
        """
        Structural, because the failure it guards is a timing window nobody hits
        on demand: `snapshot` must be one `with self._lock` covering the whole
        dict, not a helper that takes the lock again per field.
        """
        source = Path(board_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        klass = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ChessGame"
        )
        snapshot = next(
            node
            for node in klass.body
            if isinstance(node, ast.FunctionDef) and node.name == "snapshot"
        )
        body = [n for n in snapshot.body if not isinstance(n, ast.Expr)]
        self.assertEqual(len(body), 1, "snapshot does something outside the lock")
        self.assertIsInstance(body[0], ast.With)
        self.assertIsInstance(body[0].body[0], ast.Return)


class OneTableOnly(unittest.TestCase):
    """
    Two games, one table.

    The room has one surface and the page has one `game_state` channel, so a
    chess board and a hand of cards being live at the same time is not a fuller
    evening — it is two pumps taking his turn at once and a system prompt that
    tells him he is in the middle of both games. Whichever was asked for last
    wins, because that is the one the person at the table just chose.
    """

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_engine(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)
        from rau.games.kittens import session as kittens

        self.kittens = kittens
        self.addCleanup(kittens.end, "test over")

        import rau.games.kittens.player as kittens_player

        real_take = kittens_player.take_turn
        kittens_player.take_turn = lambda game: None
        self.addCleanup(setattr, kittens_player, "take_turn", real_take)

    def test_setting_the_board_up_puts_the_cards_away(self):
        self.kittens.start()
        self.assertTrue(self.kittens.active())
        session.start()
        self.assertTrue(session.active())
        self.assertFalse(self.kittens.active(), "he is playing both games at once")
        self.assertIsNone(self.kittens.state())

    def test_dealing_the_cards_puts_the_board_away(self):
        session.start()
        self.assertTrue(session.active())
        self.kittens.start()
        self.assertTrue(self.kittens.active())
        self.assertFalse(session.active(), "the board is still out under the cards")
        self.assertIsNone(session.state())

    def test_the_talker_is_never_told_about_two_games_at_once(self):
        """The prompt is where a second live game does its real damage."""
        self.kittens.start()
        session.start()
        self.assertEqual(self.kittens.prompt_fragment(), "")
        self.assertIn("chess", session.prompt_fragment().lower())


@unittest.skipUnless(binary.found(), "no stockfish on this machine")
class OneRealTurn(unittest.TestCase):
    """
    A single turn end to end, against the Stockfish that is actually installed.

    Every other test in this file replaces the pump's turn thread, which means
    none of them prove the four layers meet: a user move wakes the pump, the pump
    asks the engine, the engine's choice reaches `player`, and `player` puts it
    back through the same door the browser's moves come in by. That seam is worth
    one real turn and no more — the shape of the pause belongs to `timing.py`'s
    tests, so the plan is shortened to a tenth of a second here.

    Skipped rather than failed without a binary. A machine with no Stockfish is a
    machine where Rau declines the game; it is not a broken machine.
    """

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)

        from rau.games.chess import engine

        # The engine outlives games on purpose, so nothing in the lifecycle
        # closes it. A test that opened one has to.
        self.addCleanup(engine.close)

        real_plan = timing.think_plan
        timing.think_plan = lambda board, choice, *, rng: timing.ThinkPlan(
            delay=0.1, hovers=[timing.HoverStep(square=None, dwell=0.05)]
        )
        self.addCleanup(setattr, timing, "think_plan", real_plan)

    def test_a_move_from_the_user_comes_back_answered(self):
        session.start(rau_color="black")
        game = session.current()
        assert game is not None
        self.assertTrue(
            session.apply_move(USER, {"move": "move", "from": "e2", "to": "e4"})["ok"]
        )

        deadline = time.time() + 20
        while time.time() < deadline and len(game.moves) < 2:
            time.sleep(0.05)
        self.assertEqual(len(game.moves), 2, "the pump never took his turn")

        after_e4 = chess.Board()
        after_e4.push_san("e4")
        self.assertIn(
            game.moves[1],
            [after_e4.san(move) for move in after_e4.legal_moves],
            "he answered with something that was not a move in the position",
        )
        self.assertEqual(game.turn_seat(), USER, "the turn never came back")

    def test_the_only_thing_out_of_the_engine_is_a_bucket_and_a_swing(self):
        """
        Centipawns, depth and the principal variation stop at the engine layer.
        This reads what `session` kept from a real search — everything `player`
        and `banter` are ever handed — and it has to be those two fields.
        """
        session.start(rau_color="black")
        game = session.current()
        assert game is not None
        session.apply_move(USER, {"move": "move", "from": "d2", "to": "d4"})
        deadline = time.time() + 20
        while time.time() < deadline and not session.last_read():
            time.sleep(0.05)
        read = session.last_read()
        self.assertEqual(set(read.keys()), {"bucket", "swing", "at"})
        self.assertIn(read["bucket"], {"winning", "better", "level", "worse", "losing"})
        self.assertIsInstance(read["swing"], float)

    def test_the_strength_he_plays_at_stays_inside_the_reachable_band(self):
        """1100 is not a number this binary accepts; 1320 is the real floor."""
        self.assertGreaterEqual(level.current(), level.FLOOR)
        self.assertLessEqual(level.current(), level.CEIL)
        self.assertGreaterEqual(level.FLOOR, 1320)


class SweptMidMove(unittest.TestCase):
    """
    The board being taken away while a move is still being applied.

    `apply_move` runs `game.play` *without* the session lock on purpose: playing
    a move is real work, and holding the lock across it would put every read of
    the table behind the slowest one. The cost of that choice is a window, and
    three different callers can arrive in it from another thread — `end_chess`
    off the face model, `DELETE /api/game/chess` off the page, and the kittens
    handoff when someone asks for cards instead.

    Four separate things go wrong if the move simply carries on, which is why
    this is one test with four assertions rather than four tests: the transcript
    is seeded into the *next* game, a position the user never saw is written to
    disk one move ahead of anything broadcast, the pump `end` just stopped is
    started again and ticks against nothing for the rest of the run, and — worst,
    because it is the one the user sees — an `ok` reply re-inflates the cleared
    board in the browser, which then refuses every move made on it.

    Forced rather than raced. The window is narrow enough that threads and hope
    would make a flaky test; driving `end()` from inside `play` is the same
    interleaving, deterministically.
    """

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_engine(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)

    def test_a_move_that_lands_after_the_sweep_changes_nothing(self):
        session.start(rau_color="black")
        game = session.current()
        assert game is not None
        real_play = game.play

        def play_then_sweep(*args, **kwargs):
            note = real_play(*args, **kwargs)
            session.end("swept mid-move")
            return note

        game.play = play_then_sweep  # type: ignore[method-assign]
        result = session.apply_move(USER, {"move": "move", "from": "e2", "to": "e4"})

        self.assertFalse(result.get("ok"), "reported success for a board that is gone")
        self.assertEqual(result.get("code"), "no_game")

        saved = board_mod.current_path()
        if saved.exists():
            self.assertFalse(
                json.loads(saved.read_text(encoding="utf-8")).get("moves"),
                "wrote a position the user never saw",
            )
        self.assertFalse(
            [e for e in journal.snapshot() if "e4" in e.get("text", "")],
            "seeded the next game's transcript",
        )

        park_the_pump()
        self.assertIsNone(session.current())
        self.assertFalse(
            [t for t in threading.enumerate() if t.name.startswith("chess-pump") and t.is_alive()],
            "restarted the pump that end() had stopped",
        )


class PressingPlayAgain(unittest.TestCase):
    """
    The route, at the one moment it is easiest to get wrong.

    `POST /api/game/chess` has three jobs stacked in priority order: hand back a
    live game, otherwise pick an unfinished one off the disk, otherwise deal a
    new one. The middle job is the trap. `session.resume` treats *any* game
    already in memory as the thing to hand back — correct for the boot path it
    was written for, where memory is empty — and a game that has just ended is
    still in memory. So the obvious spelling of this route answers "play again?"
    by handing back the finished game, for ever, and never clears the card table
    on the way.

    Checkmate is a moment somebody presses play again from, so this is worth a
    test rather than a comment.
    """

    def setUp(self) -> None:
        isolate_memory(self)
        quicken_the_pump(self)
        silence_the_engine(self)
        silence_the_providers(self)
        self.addCleanup(quiesce)

    def client(self):
        from fastapi.testclient import TestClient
        from rau.hub.server import app

        # TestClient hard-codes "testserver" as the Host; the hub only answers a
        # loopback one, exactly as a browser on this machine would send.
        return TestClient(app, base_url="http://127.0.0.1:8765")

    def test_a_finished_game_is_replaced_rather_than_handed_back(self):
        client = self.client()
        first = client.post("/api/game/chess", json={}).json()["state"]
        session.apply_move(USER, {"move": "resign"})
        self.assertFalse(session.active())

        body = client.post("/api/game/chess", json={}).json()
        self.assertTrue(body["ok"])
        second = body["state"]
        self.assertNotEqual(
            second["game_id"], first["game_id"], "play again handed back the finished game"
        )
        self.assertEqual(second["moves"], [])
        self.assertEqual(second["phase"], PHASE_PLAYING)
        self.assertIsNone(second["result"])

    def test_a_live_game_is_never_replaced_by_pressing_play(self):
        client = self.client()
        first = client.post("/api/game/chess", json={}).json()["state"]
        session.apply_move(USER, {"move": "move", "from": "e2", "to": "e4"})
        again = client.post("/api/game/chess", json={}).json()["state"]
        self.assertEqual(again["game_id"], first["game_id"], "it dealt over a live game")
        self.assertEqual(again["moves"], ["e4"])


if __name__ == "__main__":
    unittest.main()

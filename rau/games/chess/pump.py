"""
The daemon that keeps a live board moving.

`board.py` is patient in the way a chessboard is patient: it will sit in a
position forever and it will never ask anyone to move. This module is the
somebody who asks. While a game is live it watches for Rau's turn, gets a move
out of Stockfish at the strength `level.py` currently thinks he deserves, gets a
think-plan out of `timing.py`, and hands both to `player.perform_move` to be
delivered. It also gives `banter` a look on every tick, which is how he says
anything at all during the long stretches where you are the one thinking.

It is `kittens/pump.py` with the hard part removed. There are no Nope windows to
expire on wall-clock time, so a tick is: advance the clock, notice the game is
over, offer banter a look, start a turn if one is owed. What survives from that
file is the discipline around the turn thread — one at a time, an error backoff
so a dead provider cannot spin the loop, and a `game_id` captured before the
work and checked after it.

That last one matters more here than it does there. A kittens turn is a model
call; a chess turn is an engine call plus up to twenty seconds of performance,
and the user is free to resign in the middle of it. The guard is what makes sure
a move chosen for a game that no longer exists is thrown away rather than
played.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Dict, Optional

from rau.events import BUS
from rau.games.chess.board import PHASE_OVER, PHASE_PLAYING, RAU, ChessGame

#: How often the pump looks at the board.
POLL_SEC = 0.15

#: After a failed turn — no binary, engine crash, provider dead — wait this long
#: before asking again so a broken machine cannot spin the loop.
ERROR_BACKOFF_SEC = 2.0

# ── the temperament ──────────────────────────────────────────────────────
#
# A 1500 player does not play a lost game to bare kings and does not grind a
# dead rook ending for forty moves out of spite. The engine will happily do
# both, which is exactly the kind of thing that gives the whole performance
# away — so the pump, which is the one place his turns pass through, is where
# the manners live. The signals are the two booleans `MoveChoice` carries;
# no evaluation ever reaches this module.

#: Looking at a hopeless position once is a bad afternoon; seeing it this many
#: turns running means it is not coming back. Streaks, not single readings,
#: because a depth-8 search at limited strength produces the occasional wild
#: number and resigning over a hiccup would be absurd.
RESIGN_STREAK = 3

#: He does not resign in the opening no matter what the search says — a person
#: who is down a queen on move eight plays on out of embarrassment.
RESIGN_MIN_PLY = 40

#: Dead level this many of his turns running before a draw crosses his mind.
OFFER_STREAK = 2

#: And not before the game has actually been played. An early offer reads as
#: him being bored of you, which is worse than any move he could make.
OFFER_MIN_PLY = 60

_lock = threading.RLock()
_pump: Optional[threading.Thread] = None
_pump_stop: Optional[threading.Event] = None
_thinking = threading.Event()
_next_turn_at: float = 0.0

#: Injected into `timing.think_plan` so the pauses are reproducible under test.
_rng = random.Random()

#: The temperament's memory, per game: how long the position has been hopeless,
#: how long it has been dead, and whether he has already offered once. Keyed by
#: game id so a board swept mid-think cannot hand its despair to the next one.
_mood: Dict[str, Dict[str, int]] = {}


def reset_for_game(*, seed: Optional[int] = None) -> None:
    """Fresh board — drop the error backoff, the mood, and reseed if asked."""
    global _next_turn_at, _rng
    from rau.games.chess import banter

    with _lock:
        _next_turn_at = 0.0
        _mood.clear()
        if seed is not None:
            _rng = random.Random(seed)
    banter.reset()


def wake() -> None:
    """A human just moved. Allow an immediate turn — drops the error backoff."""
    global _next_turn_at
    with _lock:
        _next_turn_at = 0.0


def stop() -> None:
    with _lock:
        if _pump_stop:
            _pump_stop.set()


def thinking() -> threading.Event:
    """Exposed for tests that need to wait for an in-flight turn."""
    return _thinking


def ensure() -> None:
    """Guarantee a live pump. Never adopts one that has already been told to stop."""
    global _pump, _pump_stop
    with _lock:
        if _pump and _pump.is_alive() and _pump_stop and not _pump_stop.is_set():
            return
        stop_flag = threading.Event()
        _pump_stop = stop_flag
        _pump = threading.Thread(
            target=_pump_loop, args=(stop_flag,), name="chess-pump", daemon=True
        )
        _pump.start()


def _rau_must_act(game: ChessGame) -> bool:
    return game.phase == PHASE_PLAYING and game.turn_seat() == RAU


def _back_off() -> None:
    global _next_turn_at
    with _lock:
        _next_turn_at = time.monotonic() + ERROR_BACKOFF_SEC


def _run_rau_turn() -> None:
    """
    One turn: ask the engine, ask the clock, perform it.

    Nothing in here decides anything about chess. The engine returns the move and
    `timing` returns how long to sit on it; this function's whole contribution is
    making sure the two arrive together and that neither is used on a board that
    has since been swept.
    """
    from rau.games.chess import engine, level, player, session, timing

    try:
        game = session.current()
        if not game or not _rau_must_act(game):
            return
        game_id = game.game_id

        # A copy, not the live board. Stockfish sits on a position for as long as
        # the search takes, and the HTTP thread is free to push a resignation onto
        # the real one while it does.
        position = game.board_copy()
        try:
            choice = engine.best_move(position, elo=level.current(), game_id=game_id)
            plan = timing.think_plan(position, choice, rng=_rng)
        except Exception as exc:
            BUS.emit("game_error", game="chess", error=f"engine: {exc}")
            _back_off()
            return

        # The guard comes first. A search takes long enough for the board to have
        # been swept and a new one set up while it ran, and the read is the one
        # thing here with a life beyond this call — `session` hands it to the
        # talker and to banter. Filed after the check, so a bucket and a swing
        # computed for a game nobody is playing any more cannot become what he
        # says about the game that replaced it.
        live = session.current()
        if live is None or live.game_id != game_id:
            return

        # The read is the only thing that survives out of the engine call, and
        # everything that talks reads it from `session` rather than from here.
        session.note_read(choice)

        # An outstanding offer of theirs is answered before anything else
        # happens. Mechanically his move would decline it silently, but a person
        # you have just offered a draw does not simply move — he says no, or he
        # takes it. He takes it when the position agrees with the offer, or when
        # he was losing anyway and it is a gift.
        offer = live.offer
        if offer and offer.get("by") != RAU:
            if choice.dead_level or choice.bucket in ("worse", "losing"):
                if session.apply_move(RAU, {"move": "accept_draw"}).get("ok"):
                    player.table_talk(player.table_line("accept_draw"))
                    return
            elif session.apply_move(RAU, {"move": "decline_draw"}).get("ok"):
                player.table_talk(player.table_line("decline_draw"))

        with _lock:
            mood = _mood.setdefault(game_id, {"hopeless": 0, "dead": 0, "offered": 0})
            mood["hopeless"] = mood["hopeless"] + 1 if choice.hopeless else 0
            mood["dead"] = mood["dead"] + 1 if choice.dead_level else 0
            resign_now = mood["hopeless"] >= RESIGN_STREAK and len(live.moves) >= RESIGN_MIN_PLY
            offer_now = (
                not mood["offered"]
                and mood["dead"] >= OFFER_STREAK
                and len(live.moves) >= OFFER_MIN_PLY
                and live.offer is None
            )

        if resign_now:
            # Through the same door as every other move, so it is journalled,
            # broadcast, and booked exactly like one. The line comes after the
            # act — a person tips the king first and explains second.
            if session.apply_move(RAU, {"move": "resign"}).get("ok"):
                player.table_talk(player.table_line("resign"))
            return

        player.perform_move(live, choice, plan)

        if offer_now:
            # After his move rather than before it: the offer arrives while you
            # are on the clock, with the position in front of you, which is when
            # a draw offer is actually made across a real board. The move can
            # have ended the game or been abandoned mid-delay, so the offer only
            # goes out if the same game is still quietly in play.
            live = session.current()
            if (
                live is not None
                and live.game_id == game_id
                and live.phase == PHASE_PLAYING
                and live.offer is None
            ):
                if session.apply_move(RAU, {"move": "offer_draw"}).get("ok"):
                    with _lock:
                        _mood.setdefault(game_id, {}).update(offered=1)
                    player.table_talk(player.table_line("offer_draw"))
    finally:
        _thinking.clear()
        session._broadcast()  # noqa: SLF001 — pump owns the refresh cadence


def _pump_loop(stop_flag: threading.Event) -> None:
    while not stop_flag.is_set():
        try:
            _tick_once(stop_flag)
        except Exception:
            # A tick that raised is a tick lost, not a pump lost. The next one is
            # 150ms away and the board has not moved.
            pass
        stop_flag.wait(POLL_SEC)


def _tick_once(stop_flag: threading.Event) -> None:
    from rau.games.chess import banter, session

    game = session.current()
    if not game:
        return

    if game.phase == PHASE_OVER:
        session._broadcast()  # noqa: SLF001
        session._finish(game)  # noqa: SLF001
        stop_flag.set()
        return

    with _lock:
        ready = time.monotonic() >= _next_turn_at

    # Between his moves he is still sitting there. `consider` is nearly free
    # unless it decides there is something to say, and it takes the model call
    # off this thread when it does.
    banter.consider(game, thinking=_thinking.is_set())

    if _rau_must_act(game) and not _thinking.is_set() and ready:
        _thinking.set()
        threading.Thread(target=_run_rau_turn, name="chess-turn", daemon=True).start()


__all__ = ["POLL_SEC", "ensure", "reset_for_game", "stop", "thinking", "wake"]

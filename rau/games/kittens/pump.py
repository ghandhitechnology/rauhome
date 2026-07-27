"""
The daemon that keeps a live hand moving.

The engine is patient: it will sit in a Nope window forever unless somebody
tells it time has passed, and it will never ask Rau to take his turn. This
module is that somebody. While a game is live it:

1. Expires Nope windows on wall-clock time
2. Asks the player half to decide Nope inside the window
3. Hands the player half ordinary turns — always ending in a legal move

It also gives `banter` a look at the table on every tick, which is how he
says anything between his own moves.

It does not talk to the face brain. Table talk from the player half is
delivered through `player.table_talk`; chatting with the user stays on the
face talker.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from rau.events import BUS
from rau.games.kittens.engine import PHASE_OVER, RAU, IllegalMove

#: How often the pump looks at the clock.
POLL_SEC = 0.15

#: After a failed player turn (provider dead), wait this long before asking again
#: so a broken model cannot spin the loop.
ERROR_BACKOFF_SEC = 2.0

_lock = threading.RLock()
_pump: Optional[threading.Thread] = None
_pump_stop: Optional[threading.Event] = None
_thinking = threading.Event()
_decided: set = set()
_next_turn_at: float = 0.0


def reset_for_deal() -> None:
    """Fresh hand — forget Nope decisions, error backoff, and table talk."""
    from rau.games.kittens import banter

    global _next_turn_at
    with _lock:
        _decided.clear()
        _next_turn_at = 0.0
    banter.reset()


def wake() -> None:
    """
    A human just touched the table. Clear Nope decisions so Rau re-evaluates,
    and allow an immediate player turn (drops error backoff).
    """
    global _next_turn_at
    with _lock:
        _decided.clear()
        _next_turn_at = 0.0


def stop() -> None:
    with _lock:
        if _pump_stop:
            _pump_stop.set()


def thinking() -> threading.Event:
    """Exposed for tests that need to wait for an in-flight player turn."""
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
            target=_pump_loop, args=(stop_flag,), name="kittens-pump", daemon=True
        )
        _pump.start()


def _rau_must_act(game) -> bool:
    from rau.games.kittens.engine import PHASE_PLAYING

    if game.phase == PHASE_OVER:
        return False
    if game.awaiting_seat is not None:
        return game.awaiting_seat == RAU
    return game.phase == PHASE_PLAYING and game.current == RAU


def _run_player_turn() -> None:
    global _next_turn_at
    from rau.games.kittens import player, session

    try:
        game = session.current()
        if not game or not _rau_must_act(game):
            return
        before = (game.phase, game.current, game.turns_to_take, len(game.log))
        game_id = game.game_id
        try:
            player.take_turn(game)
        except Exception as exc:
            BUS.emit("game_error", game="kittens", error=str(exc))
            with _lock:
                _next_turn_at = time.monotonic() + ERROR_BACKOFF_SEC
            return
        game = session.current()
        if game is None or game.game_id != game_id:
            return
        after = (game.phase, game.current, game.turns_to_take, len(game.log))
        if after == before and _rau_must_act(game):
            # Player claimed to move but the table did not change — back off.
            with _lock:
                _next_turn_at = time.monotonic() + ERROR_BACKOFF_SEC
    finally:
        _thinking.clear()
        session._broadcast()  # noqa: SLF001 — pump owns the refresh cadence


def _pump_loop(stop_flag: threading.Event) -> None:
    while not stop_flag.is_set():
        try:
            _tick_once(stop_flag)
        except Exception:
            pass
        stop_flag.wait(POLL_SEC)


def _tick_once(stop_flag: threading.Event) -> None:
    from rau.games.kittens import banter, player, session

    game = session.current()
    if not game:
        return

    if game.tick():
        session._broadcast()  # noqa: SLF001

    if game.phase == PHASE_OVER:
        session._broadcast()  # noqa: SLF001
        session._finish(game)  # noqa: SLF001
        stop_flag.set()
        return

    pending = game.pending
    window_for_rau = bool(pending and pending.waiting_on() == RAU)
    window_key = f"{pending.action_id}:{pending.nopes}" if pending else ""

    with _lock:
        already = window_key in _decided if window_key else True
        if window_for_rau and window_key and not already:
            _decided.add(window_key)
            should_decide = True
        else:
            should_decide = False

    if should_decide:
        if player.decide_nope(game):
            try:
                game.nope(RAU)
            except IllegalMove:
                pass
            session._broadcast()  # noqa: SLF001
        return

    with _lock:
        ready = time.monotonic() >= _next_turn_at

    # Between his moves, he is still at the table. `consider` is nearly free
    # unless it decides there is something to say, and it takes the model call
    # off this thread when it does, so the Nope clock above keeps running.
    banter.consider(game, thinking=_thinking.is_set())

    if _rau_must_act(game) and not _thinking.is_set() and ready:
        _thinking.set()
        threading.Thread(
            target=_run_player_turn, name="kittens-turn", daemon=True
        ).start()

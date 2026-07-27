"""
The one game currently on the table, and the thing that keeps it moving.

The engine is patient: it will sit in a Nope window forever unless somebody tells
it time has passed, and it will never ask Rau to take his turn. This module is
that somebody. One daemon thread runs while a game is live and does three jobs:

1. **Expire Nope windows.** Wall-clock time is not the engine's business, but it
   is somebody's.
2. **Answer for Rau when the clock is the point.** See `agent.decide_nope`.
3. **Hand Rau his turn as a conversation.** When it is his move, the table state
   is written into a short line and pushed through the ordinary face turn, so his
   move arrives with his voice attached — streamed to the page, spoken in voice
   mode, and remembered afterwards, all for free.

Only one game exists at a time. Starting a second replaces the first, which is
what "deal again" means at a real table.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from rau.events import BUS
from rau.games.kittens import view as view_mod
from rau.games.kittens.engine import (
    PHASE_OVER,
    PHASE_PLAYING,
    RAU,
    USER,
    Game,
    IllegalMove,
)

#: How often the pump looks at the clock. Fine enough that a five-second window
#: ends when it says it does, coarse enough to cost nothing.
POLL_SEC = 0.15

_lock = threading.RLock()
_game: Optional[Game] = None
_pump: Optional[threading.Thread] = None
#: Each pump owns its own stop flag rather than sharing a module-level one.
#: With a shared flag there is a window where a pump has been told to stop but
#: has not yet died: `is_alive()` is still true, so starting a new game reuses a
#: thread that is on its way out and the table sits there with nobody driving it.
_pump_stop: Optional[threading.Event] = None
#: Set while a face turn for this game is in flight, so the pump does not start a
#: second one on top of it.
_thinking = threading.Event()
#: Nope windows already decided, so he is asked once per window and not once per
#: poll.
_decided: set = set()
_last_broadcast: str = ""
#: Consecutive turns where he was handed the table and gave it back unchanged.
_stalls: int = 0
#: How many of those before the pump stops paying for another one. Three is
#: enough to ride out a bad generation and few enough to bound the bill.
MAX_STALLS = 3


def active() -> bool:
    with _lock:
        return _game is not None and _game.phase != PHASE_OVER


def current() -> Optional[Game]:
    with _lock:
        return _game


def state() -> Optional[Dict[str, Any]]:
    """The table as the browser is allowed to see it, or None if there is none."""
    with _lock:
        return view_mod.browser_view(_game) if _game else None


def prompt_fragment() -> str:
    """Appended to Rau's system prompt while a game is live. Empty otherwise."""
    with _lock:
        if not _game:
            return ""
        return view_mod.prompt_fragment(_game, RAU)


# --------------------------------------------------------------- broadcasting


def _broadcast(force: bool = False) -> None:
    """Push the table to the page, but only when something actually changed."""
    global _last_broadcast
    with _lock:
        if not _game:
            return
        view = view_mod.browser_view(_game)
    signature = repr(sorted(view.items(), key=lambda kv: kv[0]))
    if not force and signature == _last_broadcast:
        return
    _last_broadcast = signature
    BUS.emit("game_state", game="kittens", state=view)


def _finish(game: Game) -> None:
    """
    Record the result where he will trip over it again later, then announce it.

    Written before broadcast, not after. Anything that reacts to `game_over` by
    reading the running record — the UI, a later turn of his — would otherwise
    race the write and read the score from before this game.
    """
    try:
        from rau.memory.store import append_diary, append_trace

        won = game.winner == RAU
        append_diary(
            "game",
            f"Played Exploding Kittens. {'I won.' if won else 'They beat me.'} "
            f"{game.over_reason}",
            meta={"game": "kittens", "winner": game.winner},
        )
        append_trace(
            "game_result",
            {
                "game": "kittens",
                "game_id": game.game_id,
                "winner": game.winner,
                "reason": game.over_reason,
                "turns": len(game.log),
            },
        )
    except Exception:
        # A game that was fun and unrecorded still beats one that crashed on the
        # way to the diary.
        pass
    _record_tally(game)
    BUS.emit(
        "game_over",
        game="kittens",
        winner=game.winner,
        reason=game.over_reason,
        state=view_mod.browser_view(game),
        record=tally(),
    )


def _record_tally(game: Game) -> None:
    record = tally()
    record["wins"] = int(record.get("wins", 0)) + (1 if game.winner == RAU else 0)
    record["losses"] = int(record.get("losses", 0)) + (1 if game.winner == USER else 0)
    record["last_played"] = time.time()
    try:
        from rau.paths import GAMES_FILE

        GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GAMES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"kittens": record}, indent=2), encoding="utf-8")
        tmp.replace(GAMES_FILE)
    except Exception:
        pass


def tally() -> Dict[str, Any]:
    """Running record, for the model and for the UI."""
    try:
        from rau.paths import GAMES_FILE

        if not GAMES_FILE.exists():
            return {}
        return json.loads(GAMES_FILE.read_text(encoding="utf-8")).get("kittens") or {}
    except Exception:
        return {}


# ---------------------------------------------------------------- the pump


def _rau_must_act(game: Game) -> bool:
    if game.phase == PHASE_OVER:
        return False
    if game.awaiting_seat is not None:
        return game.awaiting_seat == RAU
    return game.phase == PHASE_PLAYING and game.current == RAU


def _nudge_text(game: Game) -> str:
    """
    The line that becomes Rau's turn.

    Deliberately thin: the full table already sits in his system prompt through
    `prompt_fragment`, so repeating it here would only spend context twice. What
    this carries is *what just happened*, which is the part with the timing in it.
    """
    recent = [entry.text for entry in game.log[-3:]]
    happened = " ".join(recent) if recent else "The table is waiting on you."
    return f"[Exploding Kittens] {happened} It is your move."


def _take_turn() -> None:
    """Run one face turn for the game, on a thread, exactly like a chat turn."""
    global _stalls
    from rau.face import brain, choreography
    from rau import state as runtime_state

    with _lock:
        game = _game
        if not game or not _rau_must_act(game):
            _thinking.clear()
            return
        text = _nudge_text(game)
        game_id = game.game_id
        before = (game.phase, game.current, game.turns_to_take, len(game.log))

    turn_id = choreography.new_turn_id()
    try:
        reply = str(brain.chat_streaming(text, on_token=lambda _t: None, turn_id=turn_id))
        if reply.strip():
            runtime_state.add_log("rau", reply, turn_id)
            runtime_state.push_control({"action": "speak", "text": reply})
    except Exception as exc:
        BUS.emit("game_error", game="kittens", error=str(exc))
    finally:
        with _lock:
            game = _game
            # The table may have been cleared or re-dealt while he was thinking.
            # Stall accounting belongs to the game that was asked, so a late
            # reply from a finished game must not hold the next one hostage.
            stale = game is None or game.game_id != game_id
            after = (
                before
                if stale
                else (game.phase, game.current, game.turns_to_take, len(game.log))
            )
            # A turn where he talked but never touched a card leaves the table
            # exactly as it was. Retrying that immediately would spend a model
            # call per poll for as long as it kept happening, so it is counted
            # and then given up on: the game is still there, it is just waiting
            # on a human to say something rather than on a clock.
            if stale:
                pass
            elif after == before:
                _stalls += 1
                if _stalls >= MAX_STALLS:
                    BUS.emit(
                        "game_stalled",
                        game="kittens",
                        reason="he did not make a move — say something to him",
                    )
            else:
                _stalls = 0
        _thinking.clear()
        _broadcast()


def _pump_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            _tick_once(stop)
        except Exception:
            pass
        stop.wait(POLL_SEC)


def _tick_once(stop: threading.Event) -> None:
    with _lock:
        game = _game
    if not game:
        return

    if game.tick():
        _broadcast()

    with _lock:
        if game.phase == PHASE_OVER:
            _broadcast()
            _finish(game)
            stop.set()
            return
        pending = game.pending
        window_for_rau = bool(pending and pending.waiting_on() == RAU)
        window_key = f"{pending.action_id}:{pending.nopes}" if pending else ""

    if window_for_rau and window_key not in _decided:
        _decided.add(window_key)
        from rau.games.kittens.agent import decide_nope

        if decide_nope(game):
            try:
                game.nope(RAU)
            except IllegalMove:
                pass
            _broadcast()
        return

    if _rau_must_act(game) and not _thinking.is_set() and _stalls < MAX_STALLS:
        _thinking.set()
        threading.Thread(target=_take_turn, name="kittens-turn", daemon=True).start()


def _ensure_pump() -> None:
    """Guarantee a live pump. Never adopts one that has already been told to stop."""
    global _pump, _pump_stop
    with _lock:
        if _pump and _pump.is_alive() and _pump_stop and not _pump_stop.is_set():
            return
        stop = threading.Event()
        _pump_stop = stop
        _pump = threading.Thread(
            target=_pump_loop, args=(stop,), name="kittens-pump", daemon=True
        )
        _pump.start()


# ------------------------------------------------------------------- moves


def start(*, seed: Optional[int] = None) -> Dict[str, Any]:
    """Deal a new game, replacing any game already on the table."""
    global _game, _last_broadcast, _stalls
    with _lock:
        _decided.clear()
        _stalls = 0
        _last_broadcast = ""
        _game = Game(seed=seed)
        view = view_mod.browser_view(_game)
    BUS.emit("game_started", game="kittens", state=view)
    _broadcast(force=True)
    _ensure_pump()
    return view


def end(reason: str = "cleared") -> Dict[str, Any]:
    """Take the table away."""
    global _game
    with _lock:
        game = _game
        _game = None
        if _pump_stop:
            _pump_stop.set()
    if game and game.phase != PHASE_OVER:
        BUS.emit("game_ended", game="kittens", reason=reason)
    return {"ok": True}


def apply_move(seat: str, move: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply one move for one seat.

    Returns `{"ok": True, "state": …}` or an error carrying the legal moves, so
    a model that guessed wrong is corrected rather than left to guess again.
    """
    global _stalls
    with _lock:
        game = _game
        if not game:
            return {"ok": False, "error": "there is no game on the table", "code": "no_game"}

    kind = str(move.get("move") or "")
    try:
        if kind == "play":
            game.play(seat, str(move.get("card") or ""))
        elif kind == "combo":
            cards = move.get("cards")
            if not isinstance(cards, list):
                raise IllegalMove("cards must be a list", "bad_cards")
            game.combo(seat, [str(c) for c in cards], named_card=move.get("named_card"))
        elif kind == "draw":
            game.draw_card(seat)
        elif kind == "nope":
            game.nope(seat)
        elif kind == "pass_nope":
            game.pass_nope(seat)
        elif kind == "give_favor":
            game.give_favor(seat, str(move.get("card") or ""))
        elif kind == "take_from_discard":
            game.take_from_discard(seat, str(move.get("card") or ""))
        elif kind == "insert_kitten":
            game.insert_kitten(seat, int(move.get("index", 0)))
        elif kind == "concede":
            game.concede(seat)
        else:
            raise IllegalMove(f"unknown move: {kind or '(none)'}", "unknown_move")
    except IllegalMove as exc:
        return {
            "ok": False,
            "error": exc.message,
            "code": exc.code,
            "legal_moves": game.legal_moves(seat),
        }
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "malformed"}

    # A Nope window the human just opened is a fresh decision for Rau, and a
    # human doing anything at all is reason enough to try him again.
    if seat == USER:
        _decided.clear()
        _stalls = 0
    _broadcast()
    _ensure_pump()
    return {"ok": True, "state": view_mod.browser_view(game)}

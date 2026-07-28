"""
The one game currently on the table.

Lifecycle only: deal, clear, apply a move, broadcast state, keep a tally.
The daemon that expires Nope windows and asks Rau's player half to move lives
in `pump.py`. The rules live in `engine.py`. Who may see what lives in `view.py`.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from rau.events import BUS
from rau.games.kittens import journal
from rau.games.kittens import pump
from rau.games.kittens import view as view_mod
from rau.games.kittens.engine import (
    PHASE_OVER,
    RAU,
    USER,
    Game,
    IllegalMove,
)

_lock = threading.RLock()
_game: Optional[Game] = None
_last_broadcast: str = ""


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
    """
    What the face talker sees while a game is live.

    Legal moves belong to the player half (`view.prompt_fragment`); the talker
    gets the table and the shared journal, not a tool menu.
    """
    with _lock:
        if not _game:
            return ""
        return view_mod.talker_fragment(_game, RAU)


def player_prompt_fragment() -> str:
    """What the player half sees — hand, peeks, and enumerated legal moves."""
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
    journal.record(
        "table",
        "event",
        f"Game over. {game.over_reason}",
    )
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
    """
    Fold this game into the running record, without flattening the file.

    `games.json` stopped belonging to this game the day chess arrived. Writing
    `{"kittens": record}` over the top of it erased the chess record — elo
    included — on every finished hand, and chess doing the same from its side
    would have erased this one. So the document is read, one key is replaced, and
    the whole thing goes back down.
    """
    record = tally()
    record["wins"] = int(record.get("wins", 0)) + (1 if game.winner == RAU else 0)
    record["losses"] = int(record.get("losses", 0)) + (1 if game.winner == USER else 0)
    record["last_played"] = time.time()
    try:
        from rau.paths import GAMES_FILE

        data: Dict[str, Any] = {}
        if GAMES_FILE.exists():
            loaded = json.loads(GAMES_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        data["kittens"] = record
        GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GAMES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
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


# ------------------------------------------------------------------- moves


def _clear_the_other_table() -> None:
    """
    Take the board away before the cards come down. There is only one table.

    The mirror of `chess/session._clear_the_other_table`, and it exists for the
    same reason: one surface in the room, one `game_state` channel to the page,
    and a talker who would otherwise be told he is playing two games at once.
    A chess game swept off like this keeps its saved position, so it is put away
    rather than lost.

    Called without this module's lock held. The chess side takes its own lock and
    reaches back here the other way round, and holding one while asking for the
    other is how those two would eventually deadlock.
    """
    try:
        from rau.games.chess import session as chess_session

        # `current`, not `active`: a finished game is still a board on the table
        # and still the thing the other store is holding. Sweeping only live ones
        # leaves a dead position under the cards.
        if chess_session.current() is not None:
            chess_session.end("the cards came out")
    except Exception:
        # A board that will not clear must not stop a hand being dealt. Broad
        # because every way this can fail has the same answer.
        pass


def start(*, seed: Optional[int] = None) -> Dict[str, Any]:
    """Deal a new game, replacing any game already on the table."""
    global _game, _last_broadcast
    _clear_the_other_table()
    with _lock:
        _last_broadcast = ""
        _game = Game(seed=seed)
        view = view_mod.browser_view(_game)
    journal.clear()
    journal.record("table", "event", "Dealt. They go first.")
    pump.reset_for_deal()
    BUS.emit("game_started", game="kittens", state=view)
    _broadcast(force=True)
    pump.ensure()
    return view


def end(reason: str = "cleared") -> Dict[str, Any]:
    """Take the table away."""
    global _game
    with _lock:
        game = _game
        _game = None
    pump.stop()
    journal.clear()
    if game:
        # Emit even when the game is already over: a tab that opened after the
        # result was broadcast only knows the finished table, and it clears on
        # this event, not on game_over.
        BUS.emit("game_ended", game="kittens", reason=reason)
    return {"ok": True}


def apply_move(seat: str, move: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply one move for one seat.

    Returns `{"ok": True, "state": …}` or an error carrying the legal moves, so
    a model that guessed wrong is corrected rather than left to guess again.
    """
    with _lock:
        game = _game
        if not game:
            return {"ok": False, "error": "there is no game on the table", "code": "no_game"}

    kind = str(move.get("move") or "")
    log_before = len(game.log)
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

    # Engine notes land in game.log; mirror the newest ones into the journal so
    # the talker and player both see what just happened. Player moves are also
    # recorded by player.take_turn — skip duplicating those here when seat is RAU
    # and the caller already journals; for USER we always journal.
    if seat == USER:
        for entry in game.log[log_before:]:
            journal.record("user", "move", entry.text)
        pump.wake()

    _broadcast()
    pump.ensure()
    # The mover's cut of the table — never the other seat. Websocket broadcast
    # above stays browser_view; only this return value is seat-scoped.
    return {"ok": True, "state": view_mod.seat_view(game, seat)}

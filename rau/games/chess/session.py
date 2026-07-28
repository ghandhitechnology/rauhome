"""
The one board currently out.

Lifecycle only: set the pieces up, take them away, apply a move, broadcast, keep
a record. The daemon that asks Stockfish for moves lives in `pump.py`, the rules
and the position live in `board.py`, and who is shown what lives in `view.py`.

Two things here are not in the kittens version of this file.

**Resuming.** A half-finished hand of Exploding Kittens is not worth restoring —
the state that matters is hidden, and dealing again costs nothing. A half-
finished chess position is the whole of the game, and losing it to a restart is
the kind of thing that stops people playing. So `board.py` writes the position
after every move and `resume()` picks it back up on boot.

**No tally of its own.** `kittens/session.py` counts its own wins into
`memories/games.json`. The chess record lives in `level.py`, because the score
and the strength move together and splitting them would mean two writers racing
over one shared file. `_finish` calls `record_result` and reads the answer back;
it never writes the scoreboard itself.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Dict, Optional

from rau.events import BUS
from rau.games.chess import board as board_mod
from rau.games.chess import journal
from rau.games.chess import player
from rau.games.chess import pump
from rau.games.chess import view as view_mod
from rau.games.chess.board import (
    PHASE_OVER,
    RAU,
    USER,
    ChessGame,
    IllegalMove,
)

_lock = threading.RLock()
_rng = random.Random()
_game: Optional[ChessGame] = None
_last_broadcast: str = ""

#: The last game whose result was folded in. `_finish` is idempotent per game.
_finished_id: Optional[str] = None

#: The whole of what escapes the engine layer: a bucket word and a swing in
#: pawns, from Rau's point of view. `player` and `banter` read this and nothing
#: else about the evaluation.
_read: Dict[str, Any] = {}


def active() -> bool:
    with _lock:
        return _game is not None and _game.phase != PHASE_OVER


def current() -> Optional[ChessGame]:
    with _lock:
        return _game


def state() -> Optional[Dict[str, Any]]:
    """The board as the browser is allowed to see it, which is all of it."""
    with _lock:
        return view_mod.browser_view(_game) if _game else None


def prompt_fragment() -> str:
    """What the face talker sees while a game is on the table."""
    with _lock:
        if not _game:
            return ""
        return view_mod.talker_fragment(_game, RAU)


def note_read(choice: Any) -> None:
    """Keep the coarse read from an engine call. Called by the pump, only."""
    with _lock:
        _read.clear()
        _read.update(
            {"bucket": choice.bucket, "swing": float(choice.swing), "at": time.time()}
        )


def last_read() -> Dict[str, Any]:
    with _lock:
        return dict(_read)


# --------------------------------------------------------------- broadcasting


def _broadcast(force: bool = False) -> None:
    """
    Push the board to the page, but only when something actually changed.

    The hover walk calls this on a hundred-millisecond heartbeat, so the
    signature comparison is doing real work here: only the steps where the claw
    moved reach the socket, not every slice of the wait.
    """
    global _last_broadcast
    with _lock:
        if not _game:
            return
        view = view_mod.browser_view(_game)
    signature = repr(sorted(view.items(), key=lambda kv: kv[0]))
    if not force and signature == _last_broadcast:
        return
    _last_broadcast = signature
    BUS.emit("game_state", game="chess", state=view)


def _finish(game: ChessGame) -> None:
    """
    Record the result where he will trip over it again later, then announce it.

    Written before broadcast, not after. Anything that reacts to `game_over` by
    reading the running record — the UI, a later turn of his — would otherwise
    race the write and read the score from before this game.

    Finishing twice would move the elo twice and write the diary twice, and it is
    one restarted pump away from happening, so the game id is remembered rather
    than trusted not to come back.
    """
    global _finished_id
    with _lock:
        if _finished_id == game.game_id:
            return
        _finished_id = game.game_id

    journal.record("table", "event", f"Game over. {game.over_reason}")

    try:
        from rau.games.chess import engine, level

        # You beat him, he gets harder. The direction is the whole point of the
        # ladder and it is easy to get backwards, so it lives on one line.
        #
        # This is also where the wins/losses/draws land: `level.record_result`
        # already read-modify-writes the whole `chess` record, so there is no
        # separate tally write here and adding one would count every game twice.
        # The colour rides along so the next game can seat him on the other side.
        level.record_result(game.winner, rau_color=game.rau_color)
        engine.forget(game.game_id)
    except Exception:
        # A rating that failed to move still beats a finish that crashed.
        pass

    try:
        from rau.memory.store import append_diary, append_trace

        if game.winner == RAU:
            said = "I won."
        elif game.winner == USER:
            said = "They beat me."
        else:
            said = "We drew."
        append_diary(
            "game",
            f"Played chess. {said} {game.over_reason}",
            meta={"game": "chess", "winner": game.winner},
        )
        append_trace(
            "game_result",
            {
                "game": "chess",
                "game_id": game.game_id,
                "winner": game.winner,
                "reason": game.over_reason,
                "result": game.result,
                "moves": len(game.moves),
            },
        )
    except Exception:
        # A game that was good and unrecorded still beats one that crashed on the
        # way to the diary.
        pass

    try:
        board_mod.append_pgn(game)
        board_mod.discard_saved()
    except OSError:
        pass

    BUS.emit(
        "game_over",
        game="chess",
        winner=game.winner,
        reason=game.over_reason,
        result=game.result,
        state=view_mod.browser_view(game),
        record=tally(),
    )


#: Kept out of every record that leaves this process. See `tally`. The elo is
#: the one that matters; the colour is merely bookkeeping for alternation, and
#: bookkeeping in a record invites somebody to render it.
_PRIVATE_RECORD_KEYS = frozenset({"elo", "last_rau_color"})


def tally() -> Dict[str, Any]:
    """
    Running record, for the model and for the UI — **without the elo**.

    On disk the elo and the win/loss count are one record, because they move
    together: folding a result in is a single read-modify-write of `games.json`
    rather than two racing ones. But this function is the door that record
    leaves by — into a tool result that becomes his context, into the websocket
    at game over, and into the browser on load — and the elo is the one number
    in it that must go nowhere.

    The whole strength mechanism only works while it is invisible. A Rau who can
    read "elo: 1740" in his own prompt is a Rau who can mention it, and the
    moment he does, the opponent stops being someone across a table and becomes
    a difficulty slider with a face. `level.current()` is how the code asks;
    there is deliberately no way for the model to.
    """
    from rau.games.chess import level

    record = level.tally()
    return {k: v for k, v in record.items() if k not in _PRIVATE_RECORD_KEYS}


# ------------------------------------------------------------------ lifecycle


def _clear_the_other_table() -> None:
    """
    Put the cards away before the pieces come out. There is only one table.

    The room has a single surface and the page has a single `game_state` channel,
    so two live games is not a fuller evening — it is two pumps taking turns for
    him at once and a talker whose system prompt tells him he is in the middle of
    both. The card game is the one that loses, because whoever asked for a board
    has just said which game they want.

    Called without this module's lock held, on purpose: the kittens side takes
    its own lock and the reverse handoff runs from there, so holding one while
    reaching for the other is how the two of them would eventually deadlock.
    """
    try:
        from rau.games.kittens import session as kittens

        # `current`, not `active`: a hand that has finished is still lying there,
        # still in the other store, still the thing the page draws. Sweeping only
        # live games leaves the last hand's cards under the board.
        if kittens.current() is not None:
            kittens.end("the chess board came out")
    except Exception:
        # A card game that will not put itself away must not stop a board being
        # set up. Broad because every way this can fail has the same answer.
        pass


def _open(game: ChessGame, note: str) -> Dict[str, Any]:
    """Shared tail of `start` and `resume`: clear the halves, announce, run."""
    global _game, _last_broadcast
    _clear_the_other_table()
    with _lock:
        previous = _game
        _last_broadcast = ""
        _read.clear()
        _game = game
        view = view_mod.browser_view(game)
    if previous is not None and previous.game_id != game.game_id:
        from rau.games.chess import engine

        # The abandoned game's last evaluation is keyed by its id and nothing
        # will ever come to collect it.
        engine.forget(previous.game_id)
    journal.clear()
    journal.record("table", "event", note)
    player.reset()
    pump.reset_for_game()
    BUS.emit("game_started", game="chess", state=view)
    _broadcast(force=True)
    pump.ensure()
    return view


def start(*, rau_color: Optional[str] = None) -> Dict[str, Any]:
    """
    Set the pieces up, replacing anything already out.

    Asked for nothing in particular, the colours alternate: whichever side he
    took in the last finished game, he takes the other one now — which is what
    two people at a real board do without discussing it. Before any game has
    finished he takes black, so the person who just sat down gets to open.
    An explicit colour is always honoured; alternation is only the default.
    """
    from rau.games.chess import level

    colour = str(rau_color or "").strip().lower()
    if colour == "random":
        colour = _rng.choice(("white", "black"))
    if colour not in ("white", "black"):
        previous = level.last_color()
        colour = "white" if previous == "black" else "black"

    game = ChessGame(rau_color=colour, elo=level.current())
    opener = "He opens." if colour == "white" else "You open."
    view = _open(game, f"New game. He has {colour}. {opener}")
    try:
        game.save()
    except OSError:
        pass
    return view


def resume() -> Optional[Dict[str, Any]]:
    """
    Put back the game that was on the table when the process last stopped.

    Returns None when there was nothing unfinished, which is the common case.
    Called once from the runtime's boot path; calling it with a game already out
    is a no-op that returns what is out.
    """
    with _lock:
        if _game is not None:
            return view_mod.browser_view(_game)
    game = board_mod.resume()
    if game is None:
        return None
    return _open(game, "Back at the board. The position is where you left it.")


def end(reason: str = "cleared") -> Dict[str, Any]:
    """
    Take the board away.

    Nulling `_game` is also how an in-flight think is cancelled: the hover walk
    checks the live game every slice and finds a different one, or none.
    """
    global _game
    with _lock:
        game = _game
        _game = None
        _read.clear()
    if game and game.phase == PHASE_OVER:
        # The pump normally notices the end and books it on its next tick, but
        # putting the board away is exactly the thing that happens in that gap —
        # and a finished game that was never recorded is a game that did not
        # count. `_finish` is idempotent, so doing it twice is free.
        _finish(game)
    if game:
        from rau.games.chess import engine

        # The remembered evaluation is keyed by game id; a board swept away and
        # set up again must not inherit the last position's swing.
        engine.forget(game.game_id)
    pump.stop()
    player.reset()
    journal.clear()
    if game and game.phase != PHASE_OVER:
        BUS.emit("game_ended", game="chess", reason=reason)
    return {"ok": True}


# ---------------------------------------------------------------------- moves


def apply_move(seat: str, move: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply one move for one seat.

    Returns `{"ok": True, "state": …}` or a refusal. The refusal carries no legal
    moves — there is no move menu anywhere in this game — and its `error` is
    written to be spoken, because when the user is the one refused he hears it.
    """
    with _lock:
        game = _game
        if not game:
            return {"ok": False, "error": "there is no board out", "code": "no_game"}

    kind = str(move.get("move") or "")
    try:
        if kind == "move":
            promotion = move.get("promotion")
            note = game.play(
                seat,
                str(move.get("from") or ""),
                str(move.get("to") or ""),
                str(promotion) if promotion else None,
            )
        elif kind == "resign":
            game.resign(seat)
            note = "resigned"
        elif kind == "offer_draw":
            game.offer_draw(seat)
            note = "offered a draw"
        elif kind == "accept_draw":
            game.accept_draw(seat)
            note = "took the draw"
        elif kind == "decline_draw":
            game.decline_draw(seat)
            note = "waved the draw off"
        elif kind == "claim_draw":
            game.claim_draw(seat)
            note = "claimed the draw"
        else:
            raise IllegalMove(f"that is not a move: {kind or '(none)'}", "malformed")
    except IllegalMove as exc:
        if seat == USER and exc.code != "malformed":
            # He is the one saying no, so he says it out loud. A piece that snaps
            # back in silence reads as a broken board. `malformed` is excluded on
            # purpose: that one is a broken client rather than a wrong move, and
            # it is not his fault or theirs.
            player.refuse(exc.message)
        return {"ok": False, "error": exc.message, "code": exc.code}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "malformed"}

    # Everything above ran without the lock, because `game.play` is real work and
    # holding the session lock across it would put every read of the table behind
    # the slowest move. The board can therefore have been taken away underneath
    # us in the meantime — `end_chess`, a DELETE, or the kittens handoff all call
    # `end()` from another thread — and what follows must not happen to a board
    # nobody is looking at any more.
    #
    # Each line below is a different way that goes wrong: journalling seeds the
    # next game's transcript, `save` writes a position that was never broadcast
    # and is one move ahead of anything the user saw, `ensure` restarts the very
    # pump `end` just stopped and leaves it ticking against nothing for the rest
    # of the run, and returning ok re-inflates the cleared board in the browser,
    # which then refuses every move after it. So this is one check, not four.
    with _lock:
        if _game is not game:
            return {"ok": False, "error": "the board went away", "code": "no_game"}

        # A move is journalled as a move so the transcript reads as notation; the
        # social ones read better as things that happened.
        journal.record(
            "rau" if seat == RAU else "user", "move" if kind == "move" else "event", note
        )
        try:
            game.save()
        except OSError:
            # A game that keeps going beats one that stopped because the disk did.
            pass
        view = view_mod.browser_view(game)

    if seat == USER:
        pump.wake()
    _broadcast()
    pump.ensure()
    return {"ok": True, "state": view}


__all__ = [
    "active",
    "apply_move",
    "current",
    "end",
    "last_read",
    "note_read",
    "prompt_fragment",
    "resume",
    "start",
    "state",
    "tally",
]

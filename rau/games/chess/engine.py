"""
The half of Rau that actually plays chess, and the wall around it.

One Stockfish process, opened the first time it is needed and kept alive for the
rest of the run. Opening a UCI engine costs a fork, a handshake and a hash-table
allocation; doing that per move would put a visible hiccup in front of every one
of his turns, and the hiccup would land in exactly the place `timing.py` is
trying to shape by hand.

## The one thing in this file that is easy to get wrong

Strength comes from `UCI_Elo`, not from search time. `Limit(depth=8)` is not a
speed compromise and raising it does not make him stronger — with limit-strength
on, Stockfish finds the best move and then deliberately chooses a worse one at a
rate set by the elo. A deeper search means he identifies the same move a second
later and then discards it just as often. So the search stays cheap, and the
knob that matters is the one `level.py` turns.

## What is allowed out of here

`MoveChoice` and nothing else. Centipawns, depth, node counts and the principal
variation stop at this line. A Rau who can tell you he is +1.4 after twelve ply
is a Rau who is visibly a program; a Rau who knows he is *better* and that things
just *swung his way* is a man at a table. `banter.py` gets the second one.

A mate score is not a number on the same scale as the rest, so it clamps to ten
pawns rather than arriving as 30000 and dragging every bucket boundary with it.
"""
from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass
from typing import Dict, Optional

import chess
import chess.engine

from rau.games.chess import binary

#: See the docstring: cheap on purpose. Strength lives in UCI_Elo.
DEPTH = 8

#: A forced mate clamps to this many pawns. Large enough to always land in
#: `winning`/`losing`, small enough that a swing into mate is a number and not
#: an explosion.
MATE_PAWNS = 10.0

#: Bucket floors in pawns, from Rau's point of view. Read top down; the first
#: one the score clears wins.
WINNING = 3.0
BETTER = 0.8
LEVEL = -0.8
WORSE = -3.0

#: Past this many pawns down, a club player stops playing on. Feeds the
#: `hopeless` flag — a boolean precisely so the number itself stays in here.
HOPELESS_PAWNS = -6.5

#: Inside this band the position is not merely level-ish but genuinely dead,
#: which is when a draw offer is a courtesy rather than a swindle.
DEAD_LEVEL_PAWNS = 0.35

#: Threads and hash are pinned low. He is one opponent on a machine that is also
#: rendering him, listening for a wake word, and holding a websocket open.
THREADS = 1
HASH_MB = 32


@dataclass(frozen=True)
class MoveChoice:
    """One move, plus everything the performance layer is allowed to know."""

    move: chess.Move
    #: SAN in the position *before* the move, which is the only position where
    #: it can still be computed.
    san: str
    bucket: str
    #: Pawns, Rau's point of view, against the last time he looked at the board.
    swing: float
    is_capture: bool
    is_check: bool
    is_castle: bool
    is_promotion: bool
    piece: str
    #: The two judgements a person makes without counting: "I am lost" and
    #: "there is nothing here for either of us". Booleans on purpose — they are
    #: what the pump's resign-and-offer temperament runs on, and handing it the
    #: evaluation instead would put a number back on the path this whole module
    #: exists to keep numbers off.
    hopeless: bool = False
    dead_level: bool = False


_lock = threading.RLock()
_engine: Optional[chess.engine.SimpleEngine] = None
_configured_elo: Optional[int] = None
#: Last eval seen per game, in pawns from Rau's side. Keyed by game id so two
#: games in one run cannot inherit each other's swing.
_last_eval: Dict[str, float] = {}


def available() -> bool:
    """Whether there is an engine to play with at all. Cheap; does not open one."""
    return binary.found() is not None


def _bucket(pawns: float) -> str:
    if pawns >= WINNING:
        return "winning"
    if pawns >= BETTER:
        return "better"
    if pawns > LEVEL:
        return "level"
    if pawns > WORSE:
        return "worse"
    return "losing"


def _open() -> chess.engine.SimpleEngine:
    """Caller holds the lock."""
    global _engine, _configured_elo
    if _engine is not None:
        return _engine
    path = binary.found()
    if not path:
        raise RuntimeError("no chess engine")
    _engine = chess.engine.SimpleEngine.popen_uci(path)
    _configured_elo = None
    return _engine


def _shutdown() -> None:
    """Caller holds the lock. Never raises: this runs on paths that are already
    handling a failure, and a second exception there loses the first one."""
    global _engine, _configured_elo
    engine, _engine, _configured_elo = _engine, None, None
    if engine is None:
        return
    try:
        engine.quit()
    except Exception:
        pass
    try:
        # `quit` waits politely for a process that may already be gone or wedged.
        # Closing after it is what actually guarantees the transport is down, and
        # it is a no-op when the quit worked.
        engine.close()
    except Exception:
        pass


def _apply_elo(engine: chess.engine.SimpleEngine, elo: int) -> None:
    """Caller holds the lock. Only re-sends when it changed — `configure` is a
    round trip to the engine and the elo moves once per game, not once per move."""
    global _configured_elo
    if _configured_elo == elo:
        return
    engine.configure(
        {
            "UCI_LimitStrength": True,
            "UCI_Elo": elo,
            "Threads": THREADS,
            "Hash": HASH_MB,
        }
    )
    _configured_elo = elo


def _play(board: chess.Board, elo: int) -> chess.engine.PlayResult:
    """Caller holds the lock. One attempt, no recovery."""
    engine = _open()
    _apply_elo(engine, elo)
    return engine.play(
        board,
        chess.engine.Limit(depth=DEPTH),
        info=chess.engine.INFO_SCORE,
    )


def best_move(
    board: chess.Board,
    *,
    elo: int,
    game_id: str = "",
    previous: Optional[float] = None,
) -> MoveChoice:
    """
    Pick Rau's move in this position.

    **It must be Rau's turn.** `board.turn` is taken as his side and every score
    below is read from that point of view, so handing this a position where the
    user is to move would invert the buckets silently rather than complain.

    `swing` needs the evaluation of the position from the last time he looked,
    which is a turn ago from his side and a whole exchange ago in table time —
    that gap is exactly what is worth reacting to. It is remembered here under
    `game_id` and dropped by `forget`. Pass `previous` to override it, which is
    what a replayed or restored game does, since nothing was remembered for it.

    Raises `RuntimeError` if there is no engine. That is the only failure a
    caller has to think about; a dead process is recovered from here.
    """
    with _lock:
        try:
            result = _play(board, elo)
        except (
            chess.engine.EngineTerminatedError,
            chess.engine.EngineError,
            BrokenPipeError,
            OSError,
        ):
            # Stockfish died mid-game — killed by the OS, or the machine slept
            # with the pipe open. Reopen and try once. A second failure is real
            # and belongs to the caller.
            _shutdown()
            result = _play(board, elo)

        move = result.move
        if move is None:
            raise RuntimeError("engine returned no move")

        score = result.info.get("score") if result.info else None
        if score is None:
            # Depth-limited searches occasionally return without a score line.
            # Treat it as level rather than inventing a number.
            pawns = _last_eval.get(game_id, 0.0)
        else:
            cp = score.pov(board.turn).score(mate_score=int(MATE_PAWNS * 100))
            pawns = max(-MATE_PAWNS, min(MATE_PAWNS, (cp or 0) / 100.0))

        before = previous if previous is not None else _last_eval.get(game_id)
        swing = 0.0 if before is None else pawns - before
        if game_id:
            _last_eval[game_id] = pawns

        piece = board.piece_at(move.from_square)
        return MoveChoice(
            move=move,
            san=board.san(move),
            bucket=_bucket(pawns),
            swing=round(swing, 2),
            is_capture=board.is_capture(move),
            is_check=board.gives_check(move),
            is_castle=board.is_castling(move),
            is_promotion=move.promotion is not None,
            piece=piece.symbol().upper() if piece else "",
            hopeless=pawns <= HOPELESS_PAWNS,
            dead_level=abs(pawns) <= DEAD_LEVEL_PAWNS,
        )


def forget(game_id: str) -> None:
    """That game is over; its eval must not colour the next one's first swing."""
    with _lock:
        _last_eval.pop(game_id, None)


def close() -> None:
    """Shut the process down. Safe to call when nothing was ever opened."""
    with _lock:
        _shutdown()
        _last_eval.clear()


# The engine outlives every game, so nobody's lifecycle is a natural place to
# shut it down. Left to itself a Stockfish opened at the last move of the day
# survives the process that opened it — it is a child on its own event loop
# thread, not something the interpreter reaps on the way out.
atexit.register(close)

"""
Rau talking across the chessboard when nobody asked him to.

A chess opponent who only speaks when he moves is unbearable, because in chess
you are the one taking the time. He plays, and then there are ninety seconds of
you staring at it, and if he is silent for all of them he is a program again.
`kittens/banter.py` exists for the same reason and this is its shape, with the
triggers rewritten for a game where things happen slowly and mean more.

Three rules keep it from becoming noise, and they are the kittens rules:

* **He is never the second voice.** If a think of his is in flight, or the line
  that came with his last move is still recent, he stays quiet. His move line is
  the better version of anything that could be said about his move, and two
  lines about one move reads as a stutter.
* **The model decides whether there is anything to say.** Salience is a
  judgement, not a rule table, so the prompt offers `SKIP` and a real model takes
  it most of the time. The cooldowns here are the floor under that judgement,
  not a substitute for it.
* **A reflex, not a reply.** One short line, small budget, hard deadline. A line
  about a capture that arrives after the recapture is worse than no line.

What it is allowed to know is `session.last_read()` — a bucket word and a swing
in pawns — and the SAN list. It never imports the engine and never sees a
centipawn. That read is one ply stale between his moves, which at this
resolution is invisible and is the price of keeping the evaluation where it
belongs.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

from rau.events import BUS
from rau.games.chess.board import PHASE_PLAYING, RAU, ChessGame

#: Floor on the gap between two proactive lines. Longer than kittens: a chess
#: move is a slower event and there are fewer of them worth remarking on.
MIN_GAP_SEC = 20.0

#: After the model says there is nothing worth saying, wait this long before
#: asking again. Keeps a long quiet manoeuvring phase from costing a call a tick.
SKIP_GAP_SEC = 8.0

#: A think this long is fair game. Chess is allowed to take a while before
#: taking a while is funny.
IDLE_PROD_SEC = 45.0

#: Hard budget for one line. Past this the moment it was about is gone.
REACT_TIMEOUT_SEC = 5.0

#: Ceiling on the line itself. Table talk, not commentary.
MAX_TOKENS = 60

#: A swing this size means somebody handed something over.
BLUNDER_PAWNS = 1.5

_lock = threading.RLock()
_busy = threading.Event()

#: Fingerprint of the move list the last time this looked. A tuple rather than a
#: length so a takeback or a resumed game cannot look like "nothing happened".
_seen_mark: Tuple = ()
_turn_since: float = 0.0
_last_seat: Optional[str] = None
_next_ok_at: float = 0.0

#: One-shot per game. The opening ending and the endgame arriving are each worth
#: one remark, and exactly one.
_said_opening: bool = False
_said_endgame: bool = False


def reset() -> None:
    """Fresh board: forget the cooldowns, the clock, and the one-shot remarks."""
    global _seen_mark, _turn_since, _last_seat, _next_ok_at
    global _said_opening, _said_endgame
    with _lock:
        _seen_mark = ()
        _turn_since = 0.0
        _last_seat = None
        _next_ok_at = 0.0
        _said_opening = False
        _said_endgame = False


def busy() -> threading.Event:
    """Exposed for tests that need to wait for an in-flight line."""
    return _busy


def note_user_chat() -> None:
    """
    They said something, so he is about to answer it properly.

    The face talker owns that reply. This just holds the proactive line back for
    a beat so he does not talk over his own answer.
    """
    global _next_ok_at
    with _lock:
        _next_ok_at = max(_next_ok_at, time.monotonic() + MIN_GAP_SEC)


def _face_is_talking() -> bool:
    """A conversational turn is running — he is already speaking to someone."""
    try:
        from rau import state as runtime_state

        return bool(runtime_state.status_snapshot().get("face_busy"))
    except Exception:
        return False


# ------------------------------------------------------------------ triggers


def _reason(game: ChessGame, moves: List[str], new_move: bool, now: float) -> str:
    """
    What, if anything, is worth a line right now. Empty string for nothing.

    Only ever consulted while the user is on the clock, so `moves[-1]` is the
    move he just made and `moves[-2]` is theirs. Both are fair material: his own
    move line only fires sometimes, and when it did the cooldown in `consider`
    has already sent us home.
    """
    global _said_opening, _said_endgame

    from rau.games.chess import view as view_mod

    # Same thresholds `view` describes the position with, so what he remarks on
    # and what he is told about the position cannot drift apart.
    if not _said_endgame and len(game.board.piece_map()) < view_mod.ENDGAME_MEN:
        _said_endgame = True
        return "endgame"
    if not _said_opening and len(moves) >= view_mod.OPENING_PLY:
        _said_opening = True
        return "opening_done"

    if new_move:
        from rau.games.chess import session

        swing = float(session.last_read().get("swing") or 0.0)
        if swing >= BLUNDER_PAWNS:
            return "blunder"
        if swing <= -BLUNDER_PAWNS:
            return "slipping"
        mine = moves[-1] if moves else ""
        theirs = moves[-2] if len(moves) >= 2 else ""
        if "x" in mine and "x" in theirs:
            return "trade"
        if "x" in theirs:
            return "captured"

    if now - _turn_since >= IDLE_PROD_SEC:
        return "idle"
    return ""


_NUDGES = {
    "blunder": "Something just fell into your lap. Do not explain why — enjoy it.",
    "slipping": "That went badly for you. Take it like someone who is still playing.",
    "trade": "Pieces just came off on both sides.",
    "captured": "They took something of yours.",
    "endgame": "The board has emptied out. It is an endgame now.",
    "opening_done": "The opening is over and the real game is starting.",
    "idle": (
        "They have been sitting on this move for a long time. Needle them about "
        "it, gently."
    ),
}


# -------------------------------------------------------------------- the line


def _prompt(game: ChessGame, reason: str) -> str:
    from rau.games.chess import session, view as view_mod
    from rau.language import response_language_instruction

    return "\n".join(
        [
            "You are Rau, playing chess against them, out loud.",
            response_language_instruction(),
            "",
            view_mod.coarse_read(game, session.last_read()).strip(),
            "",
            _NUDGES.get(reason, ""),
            "",
            "Say ONE short line across the table — under fifteen words, spoken, in "
            "your own voice. No notation, no analysis, no coaching them, no emoji.",
            "If there is nothing worth saying right now — nothing has changed, or "
            "you have already said it — reply with exactly: SKIP",
        ]
    )


def _ask(prompt: str) -> str:
    from rau.providers.base import Message
    from rau.providers.registry import chat_for_slot

    provider, slot = chat_for_slot("player")
    result = provider.chat(
        [Message(role="user", content=prompt)],
        model=slot.get("model") or "deepseek-v4-pro",
        max_tokens=MAX_TOKENS,
        # Higher than a move call: this one is only worth making if it is not the
        # same line every game.
        temperature=0.95,
    )
    return str(getattr(result, "text", "") or "")


def _run(game: ChessGame, reason: str) -> None:
    global _next_ok_at
    from rau.games.chess import player

    said = ""
    try:
        answer: List[str] = []

        def ask() -> None:
            try:
                answer.append(_ask(_prompt(game, reason)))
            except Exception as exc:
                BUS.emit("game_error", game="chess", error=f"banter: {exc}")

        worker = threading.Thread(target=ask, name="chess-banter-ask", daemon=True)
        worker.start()
        worker.join(REACT_TIMEOUT_SEC)
        said = player.clean_line(answer[0]) if answer else ""
    finally:
        now = time.monotonic()
        spoke = bool(said) and said.upper() != "SKIP"
        with _lock:
            # A dropped or declined line still costs a wait, so a dead provider or
            # a quiet board cannot turn this into a call every tick.
            _next_ok_at = now + (MIN_GAP_SEC if spoke else SKIP_GAP_SEC)
        _busy.clear()

    if not spoke:
        return

    from rau.games.chess import session

    # The board can have moved on entirely while the model was thinking — the
    # game ended, or he moved and said his own line. A stale line is worse than
    # no line.
    live = session.current()
    if live is None or live.game_id != game.game_id or live.phase != PHASE_PLAYING:
        return
    if live.turn_seat() == RAU or player.speaking().is_set():
        return
    player.table_talk(said)


def consider(game: Optional[ChessGame], *, thinking: bool = False) -> None:
    """
    Look at the board and, once in a while, say something about it.

    Called every pump tick. Cheap and synchronous up to the point where there is
    genuinely a reason to speak; the model call itself runs on its own thread so
    the pump keeps its cadence while he thinks of something.
    """
    global _seen_mark, _turn_since, _last_seat

    if game is None or game.phase != PHASE_PLAYING:
        return

    from rau.games.chess import player

    now = time.monotonic()
    moves = list(game.moves)
    mark = (len(moves), moves[-1] if moves else "")
    seat = game.turn_seat()

    with _lock:
        if seat != _last_seat:
            _last_seat = seat
            _turn_since = now
        first_look = not _seen_mark
        new_move = mark != _seen_mark
        if new_move:
            _seen_mark = mark
            _turn_since = now
        # Arriving mid-game — a reload, or the pump restarting — is not a move
        # anyone just made, so there is nothing to react to yet.
        if first_look:
            return

        if _busy.is_set() or now < _next_ok_at:
            return
        # His own move is coming, or his own line just went out. Either way the
        # floor is his.
        if thinking or seat == RAU or player.speaking().is_set():
            return
        if now - player.last_spoke() < MIN_GAP_SEC:
            return

        reason = _reason(game, moves, new_move, now)
        if not reason:
            return
        if reason == "idle":
            # Reset the clock here rather than on the answer: whether or not he
            # decides to needle them, this stretch has been accounted for.
            _turn_since = now
        if _face_is_talking():
            return
        _busy.set()

    threading.Thread(
        target=_run, args=(game, reason), name="chess-banter", daemon=True
    ).start()


__all__ = ["consider", "reset", "note_user_chat", "busy"]

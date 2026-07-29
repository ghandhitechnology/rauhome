"""
Rau's player half, with the choosing taken out of it.

In Exploding Kittens this is the module that plays. It reads the hand, picks a
legal move, and lives with it, which is why `kittens/player.py` ends in a retry,
a correction prompt carrying the enumerated legal moves, and a guaranteed
fallback: a model that picks moves will eventually pick an impossible one, and
the table must not stall when it does.

Here Stockfish has already picked. There is no wrong move to recover from, so
none of that machinery exists — the absence is the design, not an oversight, and
anyone reintroducing a fallback ladder into this file has misread what the file
is for. `perform_move` receives a move that is already correct and its only
possible failure is the board disappearing out from under it, whose answer is to
abandon rather than to try again.

What is left is everything that happens *around* a move that was never in doubt.
The pause while he appears to weigh it. The claw that goes out toward one square,
sits there, and then plays a different one. The line said across the table
afterwards. Afterwards is load-bearing: he is asked for a line only once the move
is on the board, and he is handed a coarsened read of the position rather than an
evaluation, so there is no path by which he can announce a plan he never made or
repeat a number nobody showed him.

Delivery is the kittens path unchanged — bubble, journal, desktop TTS — because
that path already works and a second one would only be a second thing to break.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import chess

from rau.events import BUS
from rau.games.chess.board import PHASE_OVER, RAU, ChessGame

#: Hard budget for the line he says after a move. Past this the position has
#: moved on and a late line lands on top of the next thing that happened.
SPEAK_TIMEOUT_SEC = 4.0

#: Ceiling on the line itself. Across the table, not into a microphone.
MAX_TOKENS = 48

#: Two refusals inside this window is him lecturing. A user clicking at pieces
#: that cannot move deserves one answer, not one per click.
REFUSAL_GAP_SEC = 4.0

#: Chance an ordinary quiet move is even offered to the model. Captures, checks
#: and real swings always are; this is the cost floor under the rest, not a
#: judgement about whether the line is worth saying. That judgement is SKIP.
QUIET_MOVE_CHANCE = 0.18

#: How finely the delay is chopped while waiting. Short enough that a resignation
#: mid-think is honoured almost immediately, long enough not to spin a core.
SLICE_SEC = 0.1

#: What he says when he gives check and the model had nothing, or was not there.
#: Announcing check is a courtesy of the game rather than banter, so it must not
#: depend on a provider being up.
_CHECK_LINES: Tuple[str, ...] = (
    "check.",
    "check — mind the king.",
    "that's check.",
    "check on you.",
)

#: The table manners. Resigning, offering a draw, and answering one are moments
#: the game produces on its own schedule, so like the check announcement they
#: get canned lines rather than a model call — a resignation that hangs for six
#: seconds while a provider wakes up reads as a crash, not a concession.
TABLE_LINES: Dict[str, Tuple[str, ...]] = {
    "resign": (
        "alright — that's enough. you have it.",
        "no. i'm not playing this out. well played.",
        "i know how this ends. take it.",
    ),
    "offer_draw": (
        "there's nothing left in this. split it?",
        "shall we call it? there's no way through for either of us.",
        "i'll offer you the draw before this board bores us both.",
    ),
    "accept_draw": (
        "yeah, alright. a draw.",
        "agreed. neither of us was getting through.",
        "fine — split it.",
    ),
    "decline_draw": (
        "no. we play on.",
        "not yet. there's still a game here.",
        "you'd like that, wouldn't you. play on.",
    ),
}

TABLE_LINES_KO: Dict[str, Tuple[str, ...]] = {
    "resign": ("좋아, 여기까지. 네가 이겼어.", "끝이 보이네. 잘 뒀어.", "이건 네 판이야. 인정할게."),
    "offer_draw": ("더 갈 데가 없네. 무승부 어때?", "이쯤에서 비길까?", "둘 다 뚫을 길이 없어. 무승부를 제안할게."),
    "accept_draw": ("그래, 무승부로 하자.", "좋아. 누구도 뚫지 못했네.", "좋아, 여기서 나누자."),
    "decline_draw": ("아니, 계속 두자.", "아직 게임이 남았어.", "그렇게 쉽게 끝내긴 싫은데. 계속해."),
}


def table_line(kind: str) -> str:
    """One canned line for a table courtesy. Empty string for an unknown kind."""
    from rau.language import get_locale

    source = TABLE_LINES_KO if get_locale() == "ko" else TABLE_LINES
    lines = source.get(kind) or ()
    return _rng.choice(lines) if lines else ""

_lock = threading.RLock()
_rng = random.Random()

#: Set for as long as a line of his is in flight, so banter never doubles him.
_speaking = threading.Event()

#: Which game the hover script is currently running for, and where the claw is.
#: Deliberately not written onto the board: thinking is theatre, not position,
#: and `board.py` should never have to carry a field that means "pretending".
_think_game: Optional[str] = None
_hover: Optional[str] = None

_spoke_at: float = 0.0
_last_refusal: Tuple[str, float] = ("", 0.0)


def reset() -> None:
    """New board: forget the claw, the cooldowns, and the last thing refused."""
    global _think_game, _hover, _spoke_at, _last_refusal
    with _lock:
        _think_game = None
        _hover = None
        _spoke_at = 0.0
        _last_refusal = ("", 0.0)


def speaking() -> threading.Event:
    """Set while his own line is in flight. Banter waits on this."""
    return _speaking


def last_spoke() -> float:
    """Monotonic time of his last spoken line, 0.0 if he has not said anything."""
    with _lock:
        return _spoke_at


def thinking_on(game: ChessGame) -> bool:
    """Is the hover script running for this game? `view` asks before it renders."""
    with _lock:
        return _think_game is not None and _think_game == game.game_id


def current_hover() -> Optional[str]:
    """The square the claw is over right now, or None for sitting back."""
    with _lock:
        return _hover


# ------------------------------------------------------------------- speech


def table_talk(text: str) -> None:
    """One short line across the table — bubble, log, and desktop speak."""
    global _spoke_at
    line = str(text or "").strip()
    if not line:
        return
    from rau.face import choreography
    from rau import state as runtime_state
    from rau.games.chess import journal

    turn_id = choreography.new_turn_id()
    journal.record("rau", "table_talk", line)
    runtime_state.add_log("rau", line, turn_id)
    BUS.emit("chat_started", turn_id=turn_id, text="")
    BUS.emit("chat_done", turn_id=turn_id, text=line)
    runtime_state.push_control({"action": "speak", "text": line})
    with _lock:
        _spoke_at = time.monotonic()


def refuse(text: str) -> None:
    """
    Say why their move did not happen.

    The refusal strings are written to be spoken — `session` hands them over
    exactly as the board phrased them — so there is no model call here. Speaking
    the refusal matters: a piece that snaps back with no explanation reads as the
    board being broken rather than as him telling you no.
    """
    global _last_refusal
    line = str(text or "").strip()
    if not line:
        return
    now = time.monotonic()
    with _lock:
        _, at = _last_refusal
        if now - at < REFUSAL_GAP_SEC:
            return
        _last_refusal = (line, now)
    table_talk(line)


# ----------------------------------------------------------------- the move


def perform_move(game: ChessGame, choice: Any, plan: Any) -> None:
    """
    Deliver a move that has already been chosen: pause, reach, play, maybe speak.

    Returns without touching the board if the game ends, is cleared, or is
    replaced at any point during the delay. A twenty-second think that lands a
    move onto a board the user resigned at second nineteen is the one failure
    mode this whole function is arranged to avoid.
    """
    from rau.games.chess import session

    game_id = game.game_id
    if not _run_delay(game_id, plan):
        return

    result = session.apply_move(RAU, _payload(choice))
    if not result.get("ok"):
        # Stockfish does not offer illegal moves, so this means the board and the
        # engine disagree about the position — worth surfacing loudly rather than
        # papering over with a second attempt.
        BUS.emit("game_error", game="chess", error=f"player: {result.get('error')}")
        return

    _maybe_say(game_id, choice)


def _payload(choice: Any) -> Dict[str, Any]:
    """His move in the same shape the browser sends one. One door, one door only."""
    move = choice.move
    return {
        "move": "move",
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
    }


def _run_delay(game_id: str, plan: Any) -> bool:
    """
    Walk the hover script and burn the rest of the delay. False means abandon.

    Each step broadcasts, because the hover square is the only part of the
    performance the browser can see while it is happening.
    """
    global _think_game, _hover
    from rau.games.chess import session

    try:
        with _lock:
            _think_game = game_id
            _hover = None
        session._broadcast()  # noqa: SLF001 — the claw is a state change like any other

        spent = 0.0
        for step in plan.hovers:
            with _lock:
                if _think_game != game_id:
                    return False
                _hover = step.square
            session._broadcast()  # noqa: SLF001
            if not _wait(game_id, step.dwell):
                return False
            spent += float(step.dwell)

        if not _wait(game_id, float(plan.delay) - spent):
            return False
        return _still_live(game_id) is not None
    finally:
        with _lock:
            if _think_game == game_id:
                _think_game = None
                _hover = None


def _still_live(game_id: str) -> Optional[ChessGame]:
    from rau.games.chess import session

    game = session.current()
    if game is None or game.game_id != game_id or game.phase == PHASE_OVER:
        return None
    return game


def _wait(game_id: str, seconds: float) -> bool:
    """Sleep in slices, giving up the moment the board is no longer the same one."""
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(SLICE_SEC, remaining))
        if _still_live(game_id) is None:
            return False


# ------------------------------------------------------------------ the line


def _worth_a_line(choice: Any) -> bool:
    """
    Whether to spend a call at all. Not whether the line is worth saying.

    A model asked about every quiet developing move will say something about
    every quiet developing move, and forty of those is a man narrating. So the
    loud moves always get asked and the rest get asked rarely; the model still
    decides, on top of that, that most of what it was asked about is nothing.
    """
    if choice.is_check or choice.is_capture or choice.is_promotion or choice.is_castle:
        return True
    if abs(float(choice.swing)) >= 0.8:
        return True
    return _rng.random() < QUIET_MOVE_CHANCE


def _prompt(read: str) -> str:
    from rau.language import response_language_instruction

    return "\n".join(
        [
            "You are Rau, playing chess against them, out loud. You have just moved.",
            response_language_instruction(),
            "",
            read.strip(),
            "",
            "Say ONE short line across the table — under fifteen words, spoken, in "
            "your own voice. No notation, no analysis, no coaching them, no emoji.",
            "If there is nothing worth saying right now — the position is quiet, or "
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
        # Warm. The same six lines every game is worse than no lines at all.
        temperature=0.95,
    )
    return str(getattr(result, "text", "") or "")


def clean_line(text: str) -> str:
    """Whatever the model thought the format was, reduced to one spoken line."""
    line = str(text or "").strip()
    # Models like to wrap spoken lines in quotes even when told not to.
    if len(line) >= 2 and line[0] in "\"'“‘" and line[-1] in "\"'”’":
        line = line[1:-1].strip()
    return line.split("\n", 1)[0].strip()


def _maybe_say(game_id: str, choice: Any) -> None:
    """
    Ask for a line about a move that has already been played.

    The read handed over is `view.coarse_read`, which is bucket, swing, recent
    SAN, material and stage — nothing that could be read back as a score. He is
    talking about a position he is looking at, the way anyone at a board is.
    """
    from rau.games.chess import session, view as view_mod

    game = _still_live(game_id)
    if game is None:
        return
    if not _worth_a_line(choice):
        return

    _speaking.set()
    try:
        answer: List[str] = []

        def ask() -> None:
            try:
                answer.append(_ask(_prompt(view_mod.coarse_read(game, session.last_read()))))
            except Exception as exc:
                BUS.emit("game_error", game="chess", error=f"player: {exc}")

        worker = threading.Thread(target=ask, name="chess-line", daemon=True)
        worker.start()
        worker.join(SPEAK_TIMEOUT_SEC)

        line = clean_line(answer[0]) if answer else ""
        if line.upper() == "SKIP":
            line = ""
        if not line and choice.is_check:
            from rau.language import get_locale

            line = (
                _rng.choice(("체크.", "왕 조심해.", "체크야."))
                if get_locale() == "ko"
                else _rng.choice(_CHECK_LINES)
            )
        if not line:
            return
        # The board can have moved on entirely while the model was thinking.
        if _still_live(game_id) is None:
            return
        table_talk(line)
    finally:
        _speaking.clear()


__all__ = [
    "clean_line",
    "table_talk",
    "refuse",
    "reset",
    "speaking",
    "last_spoke",
    "thinking_on",
    "current_hover",
    "perform_move",
]

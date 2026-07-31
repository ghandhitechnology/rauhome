"""
Rau talking across the table when nobody asked him to.

His player half already says a line with each move it makes. That covers half
a game: the half where he is doing something. The other half — you playing a
Favor on him, you sitting on a turn for a minute, the deck getting thin enough
that the next draw is a coin flip — was silent, and a card player who only
speaks on his own turn is a card player who is not really at the table.

So this watches the table between his moves and occasionally says something.
Three rules keep it from becoming noise:

* **He is never the second voice.** If it is his turn, or a turn of his is in
  flight, he stays quiet — the line that comes with his move says it better,
  and two lines about one move reads as a stutter.
* **The model decides whether there is anything to say.** Salience is a
  judgement, not a rule table, so the prompt offers `SKIP` and a real model
  takes it most of the time. The cooldowns here are the floor under that
  judgement, not a substitute for it.
* **A reflex, not a reply.** One short line, small budget, hard deadline. If
  the provider is slow the moment has passed and the line is dropped rather
  than delivered late on top of whatever happened next.

Delivery is `player.table_talk`, the same path his move lines take: bubble,
journal, and desktop TTS. Nothing here touches the face talker's tool loop.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from rau.events import BUS
from rau.games.kittens.engine import PHASE_PLAYING, RAU, USER, Game

#: Floor on the gap between two proactive lines. Long, on purpose: this is
#: seasoning on a game, and the move lines are already talking.
MIN_GAP_SEC = 7.0

#: After the model says there is nothing worth saying — or a line was dropped
#: unheard — wait this long before asking it again. Keeps a quiet stretch
#: from costing a call every tick.
SKIP_GAP_SEC = 6.0

#: Floor under the quiet after one of his own move lines, before a proactive
#: line may follow it. Much shorter than MIN_GAP_SEC: the move line is one
#: sentence, and hushing the table for the full gap after it ate most of a
#: user turn.
LAST_SPOKE_GAP_SEC = 4.0

#: A turn the user has been sitting on this long is worth prodding.
IDLE_PROD_SEC = 32.0

#: Hard budget for one line. Past this the moment it was about is gone.
REACT_TIMEOUT_SEC = 9.0

#: Ceiling on the line itself. Table talk, not a paragraph.
MAX_TOKENS = 60

_lock = threading.RLock()
_busy = threading.Event()
#: Fingerprint of the newest engine log entry the last time this looked.
#: Not a length: the engine keeps only the last forty entries, so a long hand
#: reaches a point where every new move leaves the count exactly where it was.
_seen_mark: tuple = ()
#: When the user's current turn started being the user's turn.
_turn_since = 0.0
_last_seat: Optional[str] = None
_next_ok_at = 0.0


def reset() -> None:
    """Fresh hand: forget the cooldowns and whose turn we were watching."""
    global _seen_mark, _turn_since, _last_seat, _next_ok_at
    with _lock:
        _seen_mark = ()
        _turn_since = 0.0
        _last_seat = None
        _next_ok_at = 0.0


def busy() -> threading.Event:
    """Exposed for tests that need to wait for an in-flight line."""
    return _busy


def _face_is_talking() -> bool:
    """A conversational turn is running — he is already speaking to someone."""
    try:
        from rau import state as runtime_state

        return bool(runtime_state.status_snapshot().get("face_busy"))
    except Exception:
        return False


def _prompt(game: Game, reason: str) -> str:
    from rau.games.kittens import journal
    from rau.games.kittens import view as view_mod
    from rau.games.kittens import vibe as vibe_mod
    from rau.language import response_language_instruction

    table = view_mod.talker_fragment(game, RAU).strip()
    # The board alone cannot tell him what has already been said, which is how
    # a proactive line ends up repeating the one that came with his last move.
    history = journal.tail().strip()
    nudge = {
        "moved": "They just moved. React to it if it is worth reacting to.",
        "idle": (
            "It has been their turn for a while and they have not moved. "
            "Needle them about it, gently."
        ),
    }.get(reason, "")
    parts = [
        "You are Rau, playing Exploding Kittens against them, out loud.",
        response_language_instruction(),
        "",
        table,
    ]
    if history:
        parts.extend(["", history])
    parts.extend(
        [
            "",
            f"Your read on them: {vibe_mod.read()}",
            nudge,
            "",
            "Say ONE short line across the table — under fifteen words, spoken, "
            "in your own voice. No narration, no quotes, no emoji, no card "
            "instructions.",
            "A taunt or a joke is welcome when the mood carries it. When it "
            "would not land, say nothing rather than forcing one.",
            "If there is nothing worth saying right now — nothing has changed, "
            "or you have already said it — reply with exactly: SKIP",
        ]
    )
    return "\n".join(parts)


def _ask(prompt: str) -> str:
    from rau.providers.base import Message
    from rau.providers.registry import chat_for_slot

    provider, slot = chat_for_slot("player")
    result = provider.chat(
        [Message(role="user", content=prompt)],
        model=slot.get("model") or "deepseek-v4-pro",
        max_tokens=MAX_TOKENS,
        # Higher than a move call: this one is only worth making if it is not
        # the same line every hand.
        temperature=0.95,
        # Sixty tokens cannot fit a thinking block and a line, and leaving
        # `effort` off does not mean "no thinking" — it means the catalog
        # default, which is "high" for DeepSeek. That is why this module has
        # almost certainly never once managed to speak.
        effort="minimal",
    )
    return str(result.content or "")


def _clean(text: str) -> str:
    line = str(text or "").strip()
    # Models like to wrap spoken lines in quotes even when told not to.
    if len(line) >= 2 and line[0] in "\"'“‘" and line[-1] in "\"'”’":
        line = line[1:-1].strip()
    # One line, whatever it thought the format was.
    line = line.split("\n", 1)[0].strip()
    return line


def _run(game: Game, reason: str) -> None:
    global _next_ok_at
    said = ""
    deliver = False
    try:
        answer: list = []

        def ask() -> None:
            try:
                answer.append(_ask(_prompt(game, reason)))
            except Exception as exc:
                BUS.emit("game_error", game="kittens", error=f"banter: {exc}")

        worker = threading.Thread(target=ask, name="kittens-banter-ask", daemon=True)
        worker.start()
        worker.join(REACT_TIMEOUT_SEC)
        said = _clean(answer[0]) if answer else ""
        deliver = bool(said) and said.upper() != "SKIP"

        if deliver:
            from rau.games.kittens import session

            # The table can have moved on entirely while the model was
            # thinking — the hand ended, or he took his turn and said his own
            # line. Either way this one is stale, and a stale line is worse
            # than no line.
            live = session.current()
            if (
                live is None
                or live.game_id != game.game_id
                or live.phase != PHASE_PLAYING
            ):
                deliver = False
            elif live.current == RAU or live.awaiting_seat == RAU:
                deliver = False
            elif _face_is_talking():
                # A conversation started while the model was thinking and it
                # owns the voice now. Talking over it is worse than no line.
                deliver = False
    finally:
        with _lock:
            # A declined or dropped line still costs a wait, so a dead
            # provider or a quiet table cannot turn this into a call every
            # tick — but a line nobody heard costs the short wait, not the
            # full one.
            _next_ok_at = time.monotonic() + (MIN_GAP_SEC if deliver else SKIP_GAP_SEC)
        _busy.clear()

    if not deliver:
        return

    from rau.games.kittens import player

    player.table_talk(said)


def consider(game: Game, *, thinking: bool = False) -> None:
    """
    Look at the table and, once in a while, say something about it.

    Called every pump tick. Cheap and synchronous up to the point where there
    is genuinely a reason to speak; the model call itself runs on its own
    thread so the pump keeps expiring Nope windows while he thinks.
    """
    global _seen_mark, _turn_since, _last_seat

    if game is None or game.phase != PHASE_PLAYING:
        return

    from rau.games.kittens import player as player_mod

    now = time.monotonic()
    newest = game.log[-1] if game.log else None
    mark = (len(game.log), newest.at, newest.text) if newest else ()

    with _lock:
        # Whose turn it is, and since when — the clock for the idle prod.
        if game.current != _last_seat:
            _last_seat = game.current
            _turn_since = now
        first_look = not _seen_mark
        new_moves = mark != _seen_mark
        # Arriving mid-hand — a reload, or the pump restarting — is not a move
        # anyone just made, so there is nothing to react to yet. It still
        # fingerprints the table, or the first real move would look brand new.
        if first_look:
            if new_moves:
                _seen_mark = mark
                _turn_since = now
            return

        if _busy.is_set() or now < _next_ok_at:
            return
        # His own turn is coming: the line that arrives with the move is the
        # better version of anything that could be said here.
        if thinking or game.current == RAU or game.awaiting_seat is not None:
            return
        # He now says a line with every move, and the turn flips to them the
        # instant that move lands — so the seat check above stops guarding the
        # moment it matters most. Without this, a proactive line can go out
        # while his move line is still being spoken.
        if now - player_mod.last_spoke() < LAST_SPOKE_GAP_SEC:
            return
        if _face_is_talking():
            return

        # Fingerprint only once every gate has passed: a move that lands
        # behind a closed gate is still unseen here, so it earns its reaction
        # when the gates clear instead of being silently forgotten.
        if new_moves:
            _seen_mark = mark
            _turn_since = now

        if new_moves and _last_move_was(game, USER):
            reason = "moved"
        elif now - _turn_since >= IDLE_PROD_SEC:
            reason = "idle"
            # Reset the clock here rather than on the answer: whether or not
            # he decides to needle them, this stretch has been accounted for.
            _turn_since = now
        else:
            return

        _busy.set()

    threading.Thread(
        target=_run, args=(game, reason), name="kittens-banter", daemon=True
    ).start()


def _last_move_was(game: Game, seat: str) -> bool:
    for entry in reversed(game.log):
        if entry.seat in (USER, RAU):
            return entry.seat == seat
    return False


def note_user_chat() -> None:
    """
    They said something, so he is about to answer it properly.

    The face talker owns that reply. This just holds the proactive line back
    for a beat so he does not talk over his own answer.
    """
    global _next_ok_at
    with _lock:
        _next_ok_at = max(_next_ok_at, time.monotonic() + MIN_GAP_SEC)


__all__ = ["consider", "reset", "note_user_chat", "busy"]

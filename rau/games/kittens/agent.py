"""
The one decision Rau cannot afford to think about.

Every other move he makes is a normal conversational turn: the move arrives in
his context, he answers in his own voice, and the tool call comes with it. That
takes seconds, which is fine — the table is waiting for him and everyone knows it.

Nope is different. It is the only card in the game played *against the clock*,
during someone else's action, and a five-second window that waits on a streaming
face turn is not a window. So Nope gets its own path: the cheap slot, a tiny
prompt containing only what he is entitled to see, and a hard deadline. If the
answer does not arrive in time he simply does not Nope, which is a legal thing to
do and the same thing a distracted human does.

He is asked at all only when he is holding a Nope. That is not a shortcut for
speed — the window itself opens either way, so the pause tells the user nothing —
it just avoids paying for a call whose answer cannot matter.

His *reasoning* is mechanical here. His *voice* is not: the fact that he Noped
lands in his context and he says something about it on his next turn, which is
where the personality belongs anyway.
"""
from __future__ import annotations

import threading
from typing import Optional

from rau.games.kittens import deck as deck_mod
from rau.games.kittens.deck import ATTACK, FAVOR, NOPE
from rau.games.kittens.engine import RAU, USER, Game

#: Wall-clock budget for the decision. Comfortably inside the Nope window, with
#: room left for the state to broadcast before the window closes.
DECIDE_TIMEOUT_SEC = 1.2

#: Cards worth burning a Nope on when the model does not answer in time. Attack
#: is the only card that costs real tempo; Favor is the only one that reaches
#: into his hand.
REFLEX_NOPE = frozenset({ATTACK, FAVOR})


def _prompt(game: Game) -> str:
    pending = game.pending
    assert pending is not None
    played = ", ".join(deck_mod.label(c) for c in pending.cards)
    mine = pending.actor == RAU
    stacked = (
        f" There are already {pending.nopes} Nopes on it, so right now it "
        f"{'will not' if pending.cancelled else 'will'} happen."
        if pending.nopes
        else ""
    )
    return (
        "You are playing Exploding Kittens. "
        f"{'You' if mine else 'Your opponent'} played {played}.{stacked}\n"
        f"Your hand: {', '.join(deck_mod.label(c) for c in game.hands[RAU])}.\n"
        f"They hold {len(game.hands[USER])} cards. "
        f"{len(game.draw)} cards left in the deck, one of them the kitten.\n\n"
        "Do you play a Nope to cancel it? Answer with exactly one word: "
        "NOPE or PASS. Nothing else."
    )


def _reflex(game: Game) -> bool:
    """What he does when the model does not answer in time."""
    pending = game.pending
    if not pending or pending.actor == RAU:
        return False
    return any(card in REFLEX_NOPE for card in pending.cards)


def decide_nope(game: Game) -> bool:
    """
    Should Rau Nope what is on the table? Blocks for at most `DECIDE_TIMEOUT_SEC`.

    Returns the decision only; the caller applies it, so a slow or broken
    provider degrades this into a reflex rather than into a hung game.
    """
    with game._lock:  # noqa: SLF001 — the snapshot must not straddle a move
        pending = game.pending
        if not pending or pending.waiting_on() != RAU:
            return False
        if NOPE not in game.hands[RAU]:
            return False
        prompt = _prompt(game)
        fallback = _reflex(game)

    answer: list = []

    def ask() -> None:
        try:
            from rau.providers.base import Message
            from rau.providers.registry import chat_for_slot

            provider, slot = chat_for_slot("subagent")
            result = provider.chat(
                [Message(role="user", content=prompt)],
                model=slot.get("model") or "deepseek-v4-pro",
                max_tokens=8,
                temperature=0.4,
            )
            answer.append(str(getattr(result, "text", "") or "").strip().upper())
        except Exception:
            pass

    worker = threading.Thread(target=ask, name="kittens-nope", daemon=True)
    worker.start()
    worker.join(DECIDE_TIMEOUT_SEC)

    if not answer:
        return fallback
    said = answer[0]
    if "NOPE" in said:
        return True
    if "PASS" in said:
        return False
    return fallback

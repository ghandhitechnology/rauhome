"""
Whether needling this person, today, would land.

Rau talks across the table on every move now, and the line he says is meant to
have some edge to it. Edge is the part that goes wrong: the same joke is warm
on a night you have been trading insults and cold on a night you have been
quiet. The table itself cannot tell him which night it is — a hand of Exploding
Kittens looks the same either way — so the read has to come from outside the
game.

`journal.tail()` carries the current hand and is already in both prompts. It is
the right signal once a hand has some history in it, and no signal at all on
the first move of a fresh deal, which is exactly when he speaks first. This
module covers that gap: at deal time it reads the last few days of conversation
and boils them down to one sentence about how the two of you have been getting
on. That sentence rides along in every prompt for the rest of the hand.

Three things keep it from becoming a tax:

* **Once per hand, off the hot path.** The call happens on its own thread when
  the cards are dealt. Nothing waits for it. A turn that lands before the
  verdict does just uses the default.
* **The default is playful.** He was asked to be a bit of a menace. A memory
  read that fails should not quietly turn him polite forever — that failure
  looks exactly like working software, which is how the last one survived so
  long.
* **It only ever advises.** The line is context in a prompt, not a gate in
  code. The model still reads the room from the transcript and can decline the
  joke on its own.
"""
from __future__ import annotations

import threading
from typing import Optional

#: How much recent conversation the read is based on. Enough to catch the tone
#: of the last couple of days without turning a 40-token answer into a 6000
#: character question.
CONTEXT_CHARS = 2000

#: Ceiling on the verdict. One sentence — it is going into other prompts.
MAX_TOKENS = 40

#: Hard budget. Nothing waits on this, but a thread that never returns is still
#: a thread that never returns.
TIMEOUT_SEC = 8.0

#: What he assumes when the read has not landed, or did not work. Deliberately
#: the permissive end: see the module docstring.
DEFAULT_VIBE = (
    "You have no read on their mood today, so play it warm and a little "
    "mischievous — teasing is welcome until they show you otherwise."
)

_lock = threading.RLock()
_verdict: Optional[str] = None

#: Bumped whenever a read is started or thrown away. A read carries the number
#: it began under and drops its answer if it no longer matches, so a slow read
#: from the last hand cannot land on this one — it would be answering a
#: question about a conversation that has since moved on, and worse, it would
#: overwrite a fresher read that finished first.
_generation = 0
_busy = threading.Event()


def reset() -> None:
    """Fresh hand: forget the last read and orphan any still in flight."""
    global _verdict, _generation
    with _lock:
        _verdict = None
        _generation += 1


def busy() -> threading.Event:
    """Exposed for tests that need to wait for an in-flight read."""
    return _busy


def read() -> str:
    """The vibe line for a prompt. Never empty — falls back to `DEFAULT_VIBE`."""
    with _lock:
        return _verdict or DEFAULT_VIBE


def _prompt(history: str) -> str:
    return "\n".join(
        [
            "Below is recent conversation between Rau and the person he lives "
            "with. Rau is about to play a card game with them and wants to "
            "know how hard he can tease.",
            "",
            history.strip(),
            "",
            "In ONE short sentence, addressed to Rau as 'you', describe how "
            "they have been getting on and whether teasing and trash talk "
            "would land right now. No preamble, no quotes, just the sentence.",
        ]
    )


def _ask(history: str) -> str:
    from rau.providers.base import Message
    from rau.providers.registry import chat_for_slot

    provider, slot = chat_for_slot("player")
    result = provider.chat(
        [Message(role="user", content=_prompt(history))],
        model=slot.get("model") or "deepseek-v4-pro",
        max_tokens=MAX_TOKENS,
        temperature=0.5,
        # Thinking would eat the whole budget and hand back an empty string.
        effort="minimal",
    )
    return str(result.content or "")


def _run(generation: int) -> None:
    global _verdict
    said = ""
    try:
        from rau.memory.store import recent_context

        history = recent_context(CONTEXT_CHARS).strip()
        if not history:
            # Nothing to read yet — a new install, or a quiet few days. The
            # default already says "no read", so leave it there.
            return
        said = str(_ask(history) or "").strip().split("\n", 1)[0].strip()
    except Exception:
        # A vibe read is a nicety. It must never be the reason a hand fails to
        # start, so this swallows rather than emitting a game error.
        said = ""
    finally:
        with _lock:
            current = generation == _generation
            if current:
                if said:
                    _verdict = said
                # Only the newest read owns the flag. A late one clearing it
                # would tell a waiter the fresh read had finished when it had
                # not.
                _busy.clear()


def prime() -> None:
    """
    Start the read for this hand. Returns immediately; nothing waits on it.

    Safe to call again. A read already in flight is not waited on or reused —
    it is orphaned, and a fresh one starts, because the older one was asked
    about an older conversation.
    """
    global _generation
    with _lock:
        _generation += 1
        generation = _generation
    _busy.set()
    threading.Thread(
        target=_run, args=(generation,), name="kittens-vibe", daemon=True
    ).start()


__all__ = ["prime", "read", "reset", "busy", "DEFAULT_VIBE"]

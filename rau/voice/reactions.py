"""
The small noises a person makes before they answer.

Latency you can hear is latency. Latency you cannot is just a beat. The gap
between the user finishing their sentence and Rau's first synthesised word is
dominated by two things that cannot be removed — the model's time to its first
sentence, and a full sentence of TTS before any audio exists. What *can* be
removed is the silence, and the silence is the part that reads as lag.

So the gap gets a short hesitation played into it. Everything here is
pre-synthesised and cached: a filler that needed its own network round trip
would add latency rather than hide it, which is the whole trap. By the time
the model's real first sentence arrives, the user has heard Rau start to
respond, and the wait was spent listening rather than watching a spinner.

The hard part is not playing a sound. It is playing a *different* one. A stock
"hmm" on every turn is worse than silence within about four turns — it stops
reading as thought and starts reading as a loading noise. So selection draws
from a shuffled bag rather than at random, the pool is grouped by what Rau is
actually about to do, and the whole thing declines to fire at all when the
answer came back fast enough not to need covering.
"""
from __future__ import annotations

import hashlib
import random
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from rau.paths import ASSETS_DIR

#: Cached PCM lives here, one file per (text, voice, model, effect).
CACHE_DIR = ASSETS_DIR / "reactions"



@dataclass(frozen=True)
class Reaction:
    """One hesitation: what to synthesise, and when it fits."""

    text: str
    #: Rough weight — some noises bear repetition better than others.
    weight: int = 1


#: What Rau is about to do, which is what the noise should imply.
#:
#: The families exist because the wrong hesitation is worse than none: "let me
#: look" when nothing is being looked up is a small lie, and the user notices
#: it the second time. `thinking` is the safe default; the others are only
#: chosen when the session actually knows more.
FAMILIES: Dict[str, Sequence[Reaction]] = {
    # Plain consideration. The bulk of turns land here.
    "thinking": (
        Reaction("Hmm.", weight=3),
        Reaction("Mm…"),
        Reaction("Ah…"),
        Reaction("Right…", weight=2),
        Reaction("Okay…", weight=2),
        Reaction("Hm, okay."),
        Reaction("Let me think."),
        Reaction("Give me a second."),
        Reaction("Oh —"),
        Reaction("So…", weight=2),
    ),
    # A question that wants a considered answer rather than a fact.
    "considering": (
        Reaction("Hm, good question."),
        Reaction("Ooh."),
        Reaction("Huh."),
        Reaction("Let me think about that."),
        Reaction("That's a fair question."),
        Reaction("Mm, hang on."),
    ),
    # A tool is about to run — the wait has a reason, so name it.
    "searching": (
        Reaction("Let me look."),
        Reaction("One moment."),
        Reaction("Checking…"),
        Reaction("Let me check that."),
        Reaction("Hang on, looking."),
    ),
    # The user said something short that mostly needs acknowledging.
    "acknowledging": (
        Reaction("Mm-hm."),
        Reaction("Right."),
        Reaction("Yeah…"),
        Reaction("Sure."),
        Reaction("Got it."),
    ),
}

DEFAULT_FAMILY = "thinking"


def _expand(pool: Iterable[Reaction]) -> List[str]:
    """Weights as repeats, so the bag shuffle honours them."""
    out: List[str] = []
    for reaction in pool:
        out.extend([reaction.text] * max(1, reaction.weight))
    return out


class _Bag:
    """
    A shuffled bag, refilled when empty.

    Not `random.choice`. Choice repeats — over ten turns it will say the same
    thing twice running often enough to be noticed, and being noticed is the
    one thing a filler must not be. A bag guarantees the whole pool is heard
    before anything comes round again, and reshuffles so the *order* still
    varies between passes.
    """

    def __init__(self, items: Sequence[str], rng: random.Random) -> None:
        self._items = list(items)
        self._rng = rng
        self._remaining: List[str] = []

    def _refill(self) -> None:
        fresh = list(self._items)
        self._rng.shuffle(fresh)
        # Appended, because `pop` draws from the end: anything left over from
        # the previous pass stays queued behind the new one rather than being
        # thrown away, so nothing is ever skipped.
        self._remaining = self._remaining + fresh

    def draw(self, avoid: Optional[str] = None) -> str:
        """
        The next item, never equal to `avoid` while any alternative exists.

        Weighted entries appear several times in the bag, so two copies of the
        same line land next to each other inside a pass often enough to matter
        — a shuffle alone does not prevent a repeat, it only makes it less
        likely, and "less likely" is still audible over a long conversation.
        """
        if not self._items:
            return ""
        if not self._remaining:
            self._refill()
        if avoid and self._remaining[-1] == avoid:
            index = self._find_other(avoid)
            if index is None:
                # The whole tail is the same line. Bring the next pass forward
                # rather than accept the one repeat this bag cannot avoid.
                self._refill()
                index = self._find_other(avoid)
            if index is not None:
                self._remaining[index], self._remaining[-1] = (
                    self._remaining[-1],
                    self._remaining[index],
                )
        return self._remaining.pop()

    def _find_other(self, avoid: str) -> Optional[int]:
        """The nearest position holding something other than `avoid`."""
        for i in range(len(self._remaining) - 2, -1, -1):
            if self._remaining[i] != avoid:
                return i
        return None


def _cache_key(text: str, voice_id: str, model: str, effect: str) -> str:
    raw = "\x1f".join([text, voice_id, model, effect]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


@dataclass
class _Voice:
    voice_id: str
    model: str
    effect: str

    @property
    def token(self) -> str:
        return f"{self.voice_id}|{self.model}|{self.effect}"


class ReactionPool:
    """
    Cached hesitation audio, and the choice of which one to play.

    One instance per process. Synthesis is lazy and memoised on disk, so the
    first turn after a voice change pays for one short clip and every turn
    after that pays nothing.
    """

    def __init__(self, *, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)
        self._bags: Dict[str, _Bag] = {}
        self._pcm: Dict[str, bytes] = {}
        self._last: str = ""
        self._recent: List[str] = []
        self._lock = threading.Lock()
        self._voice: Optional[_Voice] = None

    # ── selection ────────────────────────────────────────────────────

    def choose(self, family: str = DEFAULT_FAMILY) -> str:
        """The text of the next hesitation to play, or '' if there is none."""
        pool = FAMILIES.get(family) or FAMILIES.get(DEFAULT_FAMILY) or ()
        if not pool:
            return ""
        with self._lock:
            bag = self._bags.get(family)
            if bag is None:
                bag = _Bag(_expand(pool), self._rng)
                self._bags[family] = bag
            text = bag.draw(avoid=self._last)
            self._last = text
            self._recent = [*self._recent[-5:], text]
            return text

    @property
    def recent(self) -> List[str]:
        """What has been played lately, oldest first. For tests and debugging."""
        with self._lock:
            return list(self._recent)

    # ── audio ────────────────────────────────────────────────────────

    def _current_voice(self) -> _Voice:
        from rau.providers.registry import get_slot
        from rau.voice.tts_stream import DEFAULT_TTS_MODEL, DEFAULT_VOICE_ID

        slot = get_slot("tts") or {}
        return _Voice(
            voice_id=str(slot.get("voice_id") or DEFAULT_VOICE_ID),
            model=str(slot.get("model") or DEFAULT_TTS_MODEL),
            effect=str(slot.get("effect") or "robot"),
        )

    def _forget_if_voice_changed(self, voice: _Voice) -> None:
        if self._voice is not None and self._voice.token == voice.token:
            return
        # A different voice makes every cached clip wrong, and a wrong-voiced
        # hesitation in front of the right-voiced reply is worse than silence.
        self._voice = voice
        self._pcm.clear()

    def audio(self, text: str) -> bytes:
        """
        PCM16 at `SR` for one hesitation, synthesising and caching on miss.

        Returns `b""` on any failure. A hesitation is a nicety; it must never
        be able to take a turn down, and a turn that answers without one is
        simply a turn that sounds like it answered quickly.
        """
        if not text:
            return b""
        try:
            voice = self._current_voice()
        except Exception:
            return b""

        with self._lock:
            self._forget_if_voice_changed(voice)
            cached = self._pcm.get(text)
        if cached is not None:
            return cached

        pcm = self._load_from_disk(text, voice)
        if pcm is None:
            pcm = self._synthesise(text, voice)
            if pcm:
                self._save_to_disk(text, voice, pcm)
        pcm = pcm or b""

        with self._lock:
            # Re-check the voice: a settings change can land during synthesis,
            # and caching under the new token would pin the old voice's audio.
            if self._voice is not None and self._voice.token == voice.token:
                self._pcm[text] = pcm
        return pcm

    def _path(self, text: str, voice: _Voice) -> Path:
        return CACHE_DIR / f"{_cache_key(text, voice.voice_id, voice.model, voice.effect)}.pcm"

    def _load_from_disk(self, text: str, voice: _Voice) -> Optional[bytes]:
        try:
            path = self._path(text, voice)
            if not path.is_file():
                return None
            data = path.read_bytes()
        except OSError:
            return None
        # A truncated write from a previous run reads as a click.
        if not data or len(data) % 2:
            return None
        return data

    def _save_to_disk(self, text: str, voice: _Voice, pcm: bytes) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._path(text, voice)
            # Write-then-rename: a half-written file must never be read back as
            # audio by the next process to start.
            temp = path.with_suffix(".part")
            temp.write_bytes(pcm)
            temp.replace(path)
        except OSError:
            pass

    def _synthesise(self, text: str, voice: _Voice) -> bytes:
        from rau.voice.tts_stream import (
            MAX_REACTION_BYTES,
            RobotVoice,
            soften_edges,
            synth_sentence,
        )
        from rau.providers.registry import get_slot

        try:
            parts = bytearray()
            for chunk in synth_sentence(
                text,
                voice_id=voice.voice_id,
                model=voice.model,
                voice_settings=(get_slot("tts") or {}).get("voice_settings"),
            ):
                parts.extend(chunk)
                if len(parts) > MAX_REACTION_BYTES:
                    # A provider that ignores a two-word request and reads an
                    # essay must not get to hold the turn open.
                    return b""
            raw = bytes(parts)
            if not raw:
                return b""
            if voice.effect != "none":
                raw = RobotVoice(voice.effect).process_pcm(raw)
            # This clip is played butted directly against the first real
            # sentence, so its tail is exactly the kind of join that clicks.
            return soften_edges(raw)
        except Exception:
            return b""

    def warm(self, families: Sequence[str] = (DEFAULT_FAMILY,)) -> int:
        """
        Synthesise a family up front, off the hot path.

        Called on a background thread when a voice session opens, so the first
        turn of a conversation gets a hesitation like every turn after it —
        otherwise the one turn where latency is most visible is the one turn
        with nothing to cover it.
        """
        made = 0
        for family in families:
            for reaction in FAMILIES.get(family, ()):
                if self.audio(reaction.text):
                    made += 1
        return made


#: The process-wide pool. Voice sessions are per-connection; the cache is not.
POOL = ReactionPool()


def classify(user_text: str, *, tool_expected: bool = False) -> str:
    """
    Which family fits what the user just said.

    Deliberately shallow. This runs before the model has produced a single
    token, so there is nothing to inspect but the user's own words — and a
    confident guess that lands wrong ("let me look" when nothing is looked up)
    costs more than the safe default ever saves.
    """
    if tool_expected:
        return "searching"
    text = (user_text or "").strip()
    if not text:
        return DEFAULT_FAMILY
    lowered = text.lower()
    words = lowered.split()

    # Short and not a question: mostly wants acknowledging, not answering.
    if len(words) <= 3 and not lowered.endswith("?"):
        return "acknowledging"

    opinion = (
        "why",
        "what do you think",
        "how come",
        "should i",
        "do you think",
        "how would",
        "what would",
    )
    if lowered.endswith("?") and any(lowered.startswith(o) or o in lowered for o in opinion):
        return "considering"
    return DEFAULT_FAMILY

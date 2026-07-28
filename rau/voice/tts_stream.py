"""
Streaming text-to-speech.

The old path (`rau.face.tts.tts`) collapses the ElevenLabs generator into one
buffer with `b"".join(gen)`, so nothing is heard until the whole reply has been
synthesised. Here we synthesise sentence by sentence and emit PCM as it
arrives, so Rau starts speaking while the model is still writing.
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlencode

import numpy as np

from rau.env import get_secret
from rau.providers.registry import get_slot
from rau.voice.pronunciation import normalize_for_tts

SR = 24000
log = logging.getLogger("rau.voice.tts")

DEFAULT_VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"
DEFAULT_TTS_PROVIDER = "elevenlabs"
CARTESIA_TTS_MODEL = "sonic-3.5"

# A healthy warm ElevenLabs socket normally produces audio well inside this
# window.  Without a deadline, a rejected/malformed context can leave a Voice
# turn in "thinking" forever because there is no frame for the consumer to
# inspect and therefore no opportunity to use the HTTP fallback.
REALTIME_FIRST_AUDIO_TIMEOUT_SEC = 2.5
# Once the complete model response has been submitted, the server must either
# finish the context or fail it. This is deliberately longer than the initial
# deadline because the final sentence may contain substantially more audio.
REALTIME_FINAL_IDLE_TIMEOUT_SEC = 12.0

#: Split on sentence enders, but keep the terminator with the sentence.
#: End-of-buffer is deliberately NOT a boundary: a terminator at the buffer's
#: edge may be mid-sentence ("…roughly 3" + "." + "5 today"); flush() releases
#: the true final sentence once the stream ends.
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")

#: Don't ship a fragment shorter than this to TTS — one-word chunks sound
#: clipped and cost a request each. Waits for more text instead.
MIN_CHARS = 24
#: ...except the very first fragment of a reply, which is held to a lower bar.
#:
#: Nothing is audible until the opening chunk has been synthesised in full, so
#: every character it waits for is silence the user sits through. Later chunks
#: are synthesised while earlier ones play and cost nothing to make longer, so
#: only the first one trades phrasing for latency — and it is the only one
#: where that trade is worth making.
FIRST_MIN_CHARS = 8
#: Boundaries the opening fragment may also break on. A clause end is a place
#: a voice can stop without sounding cut off; mid-clause is not.
_SOFT_BREAK = re.compile(r"[,;:—–]\s")
#: ...unless it already ends a sentence, or we have this much queued.
MAX_CHARS = 220
MAX_SENTENCE_PCM_BYTES = SR * 2 * 120
#: A hesitation is two words. A provider that returns more than a couple of
#: seconds for one has misunderstood the request, and the clip is discarded.
MAX_REACTION_BYTES = SR * 2 * 3
#: Short hesitation openers ("음…") may flush under MIN_CHARS.
_SHORT_HESITATION = re.compile(
    r"^(음|그|어|아|well|um|uh|hmm)\s*[.…]+$",
    re.I,
)


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]


@dataclass
class SentenceTiming:
    """
    Where each character of one spoken sentence lands in its own audio.

    `char_ms[i]` is when character `i` of `text` starts, measured from the
    first sample of this sentence. That is what lets the browser fire a
    phrase-anchored body cue when playback actually reaches the phrase,
    instead of when the audio for it merely arrived over the socket.
    """

    text: str
    char_ms: List[float]
    duration_ms: float


def linear_char_ms(text: str, duration_ms: float) -> List[float]:
    """
    Even character timing across a measured duration.

    The fallback for a backend that returns no alignment. It is wrong in the
    small — a comma does not take as long as a syllable — but it is right at
    the ends and monotonic in between, which is all a phrase cue needs.
    """
    count = len(text)
    if count <= 0:
        return []
    step = max(0.0, float(duration_ms)) / count
    return [i * step for i in range(count)]


def scale_char_ms(char_ms: List[float], factor: float) -> List[float]:
    """Rescale character times after processing changed the audio duration."""
    if not char_ms or factor == 1.0 or factor <= 0:
        return list(char_ms)
    return [t * factor for t in char_ms]


class SentenceBuffer:
    """
    Accumulates streamed tokens and releases speakable chunks.

    Sentence boundaries are where a voice can breathe; releasing on token
    boundaries instead produces audible stutter between requests.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._opened = False

    def _min_chars(self) -> int:
        return MIN_CHARS if self._opened else FIRST_MIN_CHARS

    def push(self, token: str) -> List[str]:
        self._buf += token
        out: List[str] = []
        while True:
            match = _SENTENCE.search(self._buf)
            if match:
                end = match.end()
                head = self._buf[:end].strip()
                # A short sentence ("Hi.") is not worth a clipped TTS request
                # of its own — but it must not hold back what follows it
                # either. Walk the boundaries behind it and release the
                # accumulated span once it is speakable; the tail past the
                # last boundary is still being written and waits for its own
                # terminator, or for flush() to ship it.
                while (
                    len(head) < self._min_chars()
                    and not _SHORT_HESITATION.match(head)
                ):
                    nxt = _SENTENCE.search(self._buf, end)
                    if nxt is None:
                        break
                    end = nxt.end()
                    head = self._buf[:end].strip()
                if len(head) >= self._min_chars() or _SHORT_HESITATION.match(head):
                    out.append(head)
                    self._buf = self._buf[end:]
                    self._opened = True
                    continue
            elif _SHORT_HESITATION.match(self._buf.strip()):
                # A hesitation ("음…") is complete on its own; without a
                # trailing space there is no sentence match to release it.
                out.append(self._buf.strip())
                self._buf = ""
                self._opened = True
                continue
            # Only ever for the opening fragment, and only once the sentence
            # is long enough that waiting for its full stop is the expensive
            # option. A short opener reaches the ear soon anyway; a long one
            # would hold everything silent until its last word was written.
            if not self._opened and len(self._buf) >= MIN_CHARS:
                soft = _SOFT_BREAK.search(self._buf)
                # "Right," is a real lead-in and a fine thing to say on its
                # own; a two-character stub before a comma is not.
                # Floor at 3 so stubs like "So," never become their own request.
                if soft and soft.start() >= max(3, FIRST_MIN_CHARS // 3):
                    out.append(self._buf[: soft.start() + 1].strip())
                    self._buf = self._buf[soft.end() :]
                    self._opened = True
                    continue
            if len(self._buf) >= MAX_CHARS:
                # No punctuation in sight — cut at the last space so we do not
                # slice a word in half.
                cut = self._buf.rfind(" ", 0, MAX_CHARS)
                if cut <= 0:
                    cut = MAX_CHARS
                out.append(self._buf[:cut].strip())
                self._buf = self._buf[cut:]
                self._opened = True
                continue
            break
        return [s for s in out if s]

    def flush(self) -> Optional[str]:
        tail = self._buf.strip()
        self._buf = ""
        self._opened = True
        return tail or None


class RobotVoice:
    """
    The robot FX chain, applied once per complete sentence.

    It is tempting to run this incrementally with `reset=False` so the reverb
    tail carries across chunks — but PitchShift has ~25,900 samples of latency
    at 24 kHz, so streaming mode swallows the first ~1.08s of every reply and
    drops the last ~1.08s entirely. (Measured: Bitcrush, Distortion and Reverb
    are all zero-latency; PitchShift is the sole culprit.)

    One-shot processing is exactly lossless, so each sentence is buffered and
    processed whole. The per-sentence reverb seam is inaudible at 8% wet.
    """

    def __init__(self, effect: str = "none") -> None:
        self._board = None
        self.effect = effect
        if effect == "none":
            return
        try:
            from pedalboard import Bitcrush, Distortion, Pedalboard, PitchShift, Reverb

            if effect == "childlike":
                self._board = Pedalboard(
                    [
                        PitchShift(semitones=3),
                        Reverb(room_size=0.08, wet_level=0.03, dry_level=0.97),
                    ]
                )
            else:
                self._board = Pedalboard(
                    [
                        PitchShift(semitones=2),
                        Bitcrush(bit_depth=10),
                        Distortion(drive_db=2),
                        Reverb(room_size=0.15, wet_level=0.08, dry_level=0.92),
                    ]
                )
        except Exception:
            self._board = None

    def process_pcm(self, pcm: bytes) -> bytes:
        """PCM16 in, PCM16 out. Returns the input untouched on any failure."""
        if self._board is None or not pcm:
            return pcm
        try:
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            out = self._board.process(audio, SR)
            return (np.clip(out, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        except Exception:
            return pcm


class StreamingRobotVoice:
    """
    Quality-preserving effect accumulator for a real-time TTS context.

    Pedalboard's PitchShift currently buffers about 25,900 samples and drops
    sub-latency input across ``reset=False`` calls. Both configured effects use
    it, so incremental processing can silently remove short replies. Hyper
    therefore degrades this individual stage to the proven one-shot chain
    while retaining the faster endpoint, model, socket, routing, and playback
    stages. SentenceBuffer keeps this fallback scoped to short natural phrases.
    """

    def __init__(self, effect: str) -> None:
        self.effect = effect
        self._buf = bytearray()

    def push(self, pcm: bytes) -> List[bytes]:
        if len(self._buf) + len(pcm) > MAX_SENTENCE_PCM_BYTES:
            raise RuntimeError("TTS sentence audio exceeded two minutes")
        self._buf.extend(pcm)
        return []

    def flush(self) -> List[bytes]:
        if not self._buf:
            return []
        pcm = bytes(self._buf)
        self._buf.clear()
        rendered = RobotVoice(self.effect).process_pcm(pcm)
        return [soften_edges(rendered)] if rendered else []


#: Length of the ramp applied to each end of a whole-sentence buffer.
#:
#: Sentences are emitted as separate PCM buffers and played back to back. If
#: one ends mid-waveform and the next starts mid-waveform, the step between
#: them is a discontinuity, and a discontinuity is a click. At 1.5 ms the ramp
#: is far too short to hear as a fade — well under one cycle of the lowest
#: voiced pitch — but long enough to bring both ends to zero.
EDGE_FADE_MS = 1.5


def soften_edges(pcm: bytes, sample_rate: int = SR) -> bytes:
    """
    Ramp a whole-sentence buffer to zero at both ends.

    Only safe on buffers that are complete utterances. Applying it to the raw
    streaming chunks — which cut mid-phoneme — would put a notch in the middle
    of words and read as tremolo rather than as cleanliness.
    """
    if not pcm or len(pcm) % 2:
        return pcm
    try:
        samples = np.frombuffer(pcm, dtype=np.int16)
        n = int(sample_rate * EDGE_FADE_MS / 1000.0)
        # Nothing to do for a clip shorter than two ramps.
        if n < 2 or samples.size < n * 2:
            return pcm
        out = samples.astype(np.float32)
        # Raised cosine rather than linear: its slope is zero at both ends, so
        # the ramp itself introduces no corner for the ear to find.
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n, dtype=np.float32))
        out[:n] *= ramp
        out[-n:] *= ramp[::-1]
        return np.clip(out, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return pcm


_el_client = None
_el_client_lock = threading.Lock()


def _client(provider: str = DEFAULT_TTS_PROVIDER):
    """Reuse one ElevenLabs client across speaks (TLS/setup off the hot path)."""
    if provider != "elevenlabs":
        return None
    global _el_client
    with _el_client_lock:
        if _el_client is None:
            from elevenlabs.client import ElevenLabs

            key = get_secret("ELEVENLABS_API_KEY")
            if not key:
                raise RuntimeError("ELEVENLABS_API_KEY not set")
            _el_client = ElevenLabs(api_key=key)
        return _el_client


def warmup() -> bool:
    """Touch the client and fire a tiny synth so the first real speak is warm."""
    try:
        for _ in synth_sentence("warm"):
            break
        return True
    except Exception:
        return False


def _sdk_voice_settings(settings: Optional[Dict[str, Any]]):
    """Convert our JSON-safe settings to the current ElevenLabs SDK type."""
    if not settings:
        return None
    from elevenlabs import VoiceSettings

    return VoiceSettings(
        stability=float(settings.get("stability", 0.5)),
        similarity_boost=float(settings.get("similarity_boost", 0.75)),
        style=float(settings.get("style", 0.0)),
        speed=float(settings.get("speed", 1.0)),
        use_speaker_boost=bool(settings.get("use_speaker_boost", True)),
    )


def synth_sentence(
    text: str,
    *,
    client: Any = None,
    provider: str = "",
    voice_id: str = "",
    model: str = "",
    voice_settings: Optional[Dict[str, Any]] = None,
    cancel: Optional[threading.Event] = None,
) -> Iterator[bytes]:
    """Yield PCM16 chunks for one sentence, stopping early if cancelled."""
    spoken = normalize_for_tts(text)
    if not spoken:
        return
    slot = get_slot("tts") if not provider or not voice_id or not model else {}
    selected_provider = str(provider or slot.get("provider") or DEFAULT_TTS_PROVIDER)
    selected_voice = str(voice_id or slot.get("voice_id") or DEFAULT_VOICE_ID)
    selected_model = str(
        model
        or slot.get("model")
        or (CARTESIA_TTS_MODEL if selected_provider == "cartesia" else DEFAULT_TTS_MODEL)
    )
    selected_settings = (
        voice_settings if voice_settings is not None else slot.get("voice_settings")
    ) or {}
    if selected_provider == "cartesia":
        from rau.voice.cartesia_api import stream_audio

        emitted = 0
        stream = stream_audio(
            text=spoken,
            voice_id=selected_voice,
            model=selected_model,
            speed=float(selected_settings.get("speed", 1.0)),
        )
        try:
            for chunk in stream:
                if cancel is not None and cancel.is_set():
                    return
                if not isinstance(chunk, bytes):
                    raise TypeError("TTS provider returned a non-bytes audio chunk")
                if len(chunk) % 2:
                    raise RuntimeError("TTS provider returned incomplete PCM16 audio")
                emitted += len(chunk)
                if emitted > MAX_SENTENCE_PCM_BYTES:
                    raise RuntimeError("TTS sentence audio exceeded two minutes")
                yield chunk
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        return
    if selected_provider != "elevenlabs":
        raise RuntimeError(f"Unsupported TTS provider: {selected_provider}")

    c = client or _client(selected_provider)
    request: Dict[str, Any] = {
        "voice_id": selected_voice,
        "text": spoken,
        "model_id": selected_model,
        "output_format": "pcm_24000",
    }
    sdk_settings = _sdk_voice_settings(selected_settings)
    if sdk_settings is not None:
        request["voice_settings"] = sdk_settings
    stream = c.text_to_speech.stream(**request)
    emitted = 0
    try:
        for chunk in stream:
            if cancel is not None and cancel.is_set():
                return
            if chunk:
                if not isinstance(chunk, bytes):
                    raise TypeError("TTS provider returned a non-bytes audio chunk")
                if len(chunk) % 2:
                    raise RuntimeError("TTS provider returned incomplete PCM16 audio")
                emitted += len(chunk)
                if emitted > MAX_SENTENCE_PCM_BYTES:
                    raise RuntimeError("TTS sentence audio exceeded two minutes")
                yield chunk
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _chunk_audio(item: Any) -> bytes:
    """PCM16 out of one timestamped stream item."""
    raw = getattr(item, "audio_base_64", None)
    if raw is None and isinstance(item, dict):
        raw = item.get("audio_base_64")
    if not raw:
        return b""
    pcm = base64.b64decode(raw)
    if len(pcm) % 2:
        raise RuntimeError("TTS provider returned incomplete PCM16 audio")
    return pcm


def _chunk_alignment(item: Any) -> Optional[Tuple[List[str], List[float]]]:
    """Characters and their start times (seconds) from one stream item."""
    align = getattr(item, "alignment", None)
    if align is None and isinstance(item, dict):
        align = item.get("alignment")
    if align is None:
        return None
    chars = getattr(align, "characters", None)
    starts = getattr(align, "character_start_times_seconds", None)
    if chars is None and isinstance(align, dict):
        chars = align.get("characters")
        starts = align.get("character_start_times_seconds")
    if not isinstance(chars, list) or not isinstance(starts, list):
        return None
    if len(chars) != len(starts):
        return None
    return [str(c) for c in chars], [float(s) for s in starts]


def synth_sentence_timed(
    text: str,
    *,
    client: Any = None,
    provider: str = "",
    voice_id: str = "",
    model: str = "",
    voice_settings: Optional[Dict[str, Any]] = None,
    cancel: Optional[threading.Event] = None,
) -> Iterator[Tuple[bytes, Optional[Tuple[List[str], List[float]]]]]:
    """
    Yield `(pcm, alignment)` for one sentence.

    Falls back to the plain stream — and therefore to `alignment=None` — for a
    client or an account that cannot serve character timestamps, so losing
    alignment costs cue precision rather than the voice.
    """
    spoken = normalize_for_tts(text)
    if not spoken:
        return
    slot = get_slot("tts") if not provider or not voice_id or not model else {}
    selected_provider = str(provider or slot.get("provider") or DEFAULT_TTS_PROVIDER)
    if selected_provider == "cartesia":
        for chunk in synth_sentence(
            spoken,
            provider=selected_provider,
            voice_id=voice_id,
            model=model,
            voice_settings=voice_settings
            if voice_settings is not None
            else slot.get("voice_settings"),
            cancel=cancel,
        ):
            yield chunk, None
        return
    c = client or _client(selected_provider)
    vid = voice_id or slot.get("voice_id") or DEFAULT_VOICE_ID
    mid = model or slot.get("model") or DEFAULT_TTS_MODEL

    timed = getattr(getattr(c, "text_to_speech", None), "stream_with_timestamps", None)
    stream = None
    if callable(timed):
        try:
            request: Dict[str, Any] = {
                "voice_id": vid,
                "text": spoken,
                "model_id": mid,
                "output_format": "pcm_24000",
            }
            selected_settings = _sdk_voice_settings(
                voice_settings
                if voice_settings is not None
                else slot.get("voice_settings")
            )
            if selected_settings is not None:
                request["voice_settings"] = selected_settings
            stream = timed(**request)
        except Exception:
            stream = None

    if stream is not None:
        emitted = 0
        degraded = False
        try:
            for item in stream:
                if cancel is not None and cancel.is_set():
                    return
                pcm = _chunk_audio(item)
                if not pcm:
                    continue
                emitted += len(pcm)
                if emitted > MAX_SENTENCE_PCM_BYTES:
                    raise RuntimeError("TTS sentence audio exceeded two minutes")
                yield pcm, _chunk_alignment(item)
        except GeneratorExit:
            raise
        except Exception:
            # Nothing was audible yet, so the plain endpoint can still serve
            # this sentence. Once audio has shipped, the failure is real.
            if emitted:
                raise
            degraded = True
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if not degraded:
            return

    for chunk in synth_sentence(
        spoken,
        client=c,
        provider=selected_provider,
        voice_id=vid,
        model=mid,
        voice_settings=voice_settings
        if voice_settings is not None
        else slot.get("voice_settings"),
        cancel=cancel,
    ):
        yield chunk, None


class _AlignmentCollector:
    """Accumulates per-chunk character timestamps into one sentence timing."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._chars: List[str] = []
        self._starts: List[float] = []
        self.saw_alignment = False

    def add(self, alignment: Optional[Tuple[List[str], List[float]]]) -> None:
        if alignment is None:
            return
        chars, starts = alignment
        if not chars:
            return
        self.saw_alignment = True
        self._chars.extend(chars)
        self._starts.extend(starts)

    def finish(self, duration_ms: float) -> SentenceTiming:
        """
        Resolve to character times against the sentence text we actually sent.

        The provider's characters normally reproduce the request verbatim, but
        an account with text normalisation on can return something else. Cues
        are matched against the reply, so anything that does not line up with
        the reply is thrown away in favour of even spacing.
        """
        char_ms = linear_char_ms(self.text, duration_ms)
        if self.saw_alignment and "".join(self._chars) == self.text:
            char_ms = [s * 1000.0 for s in self._starts]
        return SentenceTiming(
            text=self.text, char_ms=char_ms, duration_ms=float(duration_ms)
        )


#: Mood tags the model may open a reply with (mirrors brain.extract_emotion).
#: The face strips the tag from the finished text; a streaming voice cannot
#: wait that long, or the synthesiser reads "[HAPPY]" out loud.
_EMOTION_TAG = re.compile(
    r"\[(HAPPY|CURIOUS|EXCITED|SAD|SCARED|AMAZED|LOVE|DETERMINED|IDLE)\]",
    re.I,
)
_EMOTION_TAG_NAMES = (
    "HAPPY", "CURIOUS", "EXCITED", "SAD", "SCARED", "AMAZED", "LOVE",
    "DETERMINED", "IDLE",
)


def _could_open_tag(text: str) -> bool:
    """True while `text` (lstripped) may still grow into a leading tag."""
    if not text:
        return True  # only whitespace so far
    if not text.startswith("["):
        return False
    inner = text[1:]
    if "]" in inner:
        return False  # decided one way or the other
    upper = inner.upper()
    return any(name.startswith(upper) for name in _EMOTION_TAG_NAMES)


def _without_leading_emotion_tag(tokens: Iterator[str]) -> Iterator[str]:
    """
    Drop a leading "[HAPPY]"-style mood tag before sentence chunking.

    The tag may span several tokens, so hold the opening tokens until the
    stream proves or disproves one; anything that is not a tag is forwarded
    verbatim.
    """
    head = ""
    undecided = True
    for token in tokens:
        if not undecided:
            yield token
            continue
        head += token
        text = head.lstrip()
        if _could_open_tag(text):
            continue
        undecided = False
        match = _EMOTION_TAG.match(text)
        if match:
            remainder = text[match.end() :]
            if remainder:
                yield remainder
        else:
            yield head
        head = ""
    if undecided and head:
        # Stream ended inside what could have been a tag — it is just text.
        yield head


def speak_stream(
    tokens: Iterator[str],
    *,
    on_audio: Callable[[bytes], None],
    on_sentence: Optional[Callable[[str], None]] = None,
    on_timing: Optional[Callable[[SentenceTiming], None]] = None,
    cancel: Optional[threading.Event] = None,
    robot: Optional[bool] = None,
) -> Generator[None, None, None]:
    """
    Drive TTS from a token stream.

    `on_audio` receives PCM16 mono 24 kHz ready to play. `on_sentence` fires as
    each sentence begins synthesising, which is what drives Clawd's per-sentence
    reaction beats. `on_timing` fires once per sentence, after its audio has
    been handed over, carrying the character timestamps a client needs to sync
    body cues to playback.
    """
    buf = SentenceBuffer()
    slot = get_slot("tts")
    provider = str(slot.get("provider") or DEFAULT_TTS_PROVIDER)
    # Keep the no-argument call for compatibility with injected ElevenLabs
    # clients in tests and local extensions.
    client = None if provider == "cartesia" else _client()
    voice_id = str(slot.get("voice_id") or DEFAULT_VOICE_ID)
    model = str(
        slot.get("model")
        or (CARTESIA_TTS_MODEL if provider == "cartesia" else DEFAULT_TTS_MODEL)
    )
    effect = str(slot.get("effect") or "none")
    if robot is True:
        effect = "robot"
    elif robot is False:
        effect = "none"
    if effect == "none":
        fx = None
    else:
        try:
            fx = RobotVoice(effect)
        except TypeError:
            # Compatibility with simple injected processors in tests and local
            # extensions written before effects became selectable.
            fx = RobotVoice()
    voice_settings = slot.get("voice_settings")

    def emit(sentence: str) -> bool:
        if cancel is not None and cancel.is_set():
            return False
        if on_sentence:
            on_sentence(sentence)

        align = _AlignmentCollector(sentence)

        if fx is None:
            # No FX: forward chunks the instant they arrive, lowest latency.
            raw_bytes = 0
            for chunk, alignment in synth_sentence_timed(
                sentence,
                client=client,
                provider=provider,
                voice_id=voice_id,
                model=model,
                voice_settings=voice_settings,
                cancel=cancel,
            ):
                if cancel is not None and cancel.is_set():
                    return False
                align.add(alignment)
                raw_bytes += len(chunk)
                on_audio(chunk)
            if on_timing and raw_bytes:
                on_timing(align.finish(bytes_duration_ms(raw_bytes)))
            return True

        # FX must see the whole sentence at once (see RobotVoice), so collect
        # it first. Granularity is a sentence, not the whole reply, so the
        # first words still arrive far sooner than the old one-shot path.
        parts = bytearray()
        for chunk, alignment in synth_sentence_timed(
            sentence,
            client=client,
            provider=provider,
            voice_id=voice_id,
            model=model,
            voice_settings=voice_settings,
            cancel=cancel,
        ):
            if cancel is not None and cancel.is_set():
                return False
            align.add(alignment)
            if len(parts) + len(chunk) > MAX_SENTENCE_PCM_BYTES:
                raise RuntimeError("TTS sentence audio exceeded two minutes")
            parts.extend(chunk)
        if cancel is not None and cancel.is_set():
            return False
        if parts:
            raw_ms = pcm_duration_ms(bytes(parts))
            processed = soften_edges(fx.process_pcm(bytes(parts)))
            on_audio(processed)
            if on_timing:
                out_ms = pcm_duration_ms(processed)
                timing = align.finish(raw_ms)
                # Pitch shift and reverb can lengthen or shorten the buffer.
                # Timestamps describe the audio the browser will play, not the
                # audio the provider returned.
                if raw_ms > 0 and out_ms != raw_ms:
                    timing = SentenceTiming(
                        text=timing.text,
                        char_ms=scale_char_ms(timing.char_ms, out_ms / raw_ms),
                        duration_ms=out_ms,
                    )
                on_timing(timing)
        return True

    for token in _without_leading_emotion_tag(tokens):
        if cancel is not None and cancel.is_set():
            return
        for sentence in buf.push(token):
            if not emit(sentence):
                return
        yield

    tail = buf.flush()
    if tail:
        emit(tail)


def _ws_alignment(item: Dict[str, Any]) -> Optional[Tuple[List[str], List[float]]]:
    raw = (
        item.get("normalizedAlignment")
        or item.get("normalized_alignment")
        or item.get("alignment")
    )
    if not isinstance(raw, dict):
        return None
    chars = raw.get("chars") or raw.get("characters")
    starts_ms = raw.get("char_start_times_ms")
    if starts_ms is None:
        # ElevenLabs' WebSocket wire format currently uses camelCase while
        # its agent/client examples and HTTP timestamp types use snake_case.
        starts_ms = raw.get("charStartTimesMs")
    if starts_ms is None:
        starts_sec = raw.get("character_start_times_seconds")
        if isinstance(starts_sec, list):
            starts_ms = [float(value) * 1000.0 for value in starts_sec]
    if not isinstance(chars, list) or not isinstance(starts_ms, list):
        return None
    if len(chars) != len(starts_ms):
        return None
    return [str(char) for char in chars], [float(value) / 1000.0 for value in starts_ms]


def _realtime_provider_error(item: Dict[str, Any]) -> Optional[RuntimeError]:
    """Turn an ElevenLabs error frame into a safe, actionable exception."""
    kind = str(item.get("type") or item.get("status") or "").lower()
    if "error" not in item and kind not in {"error", "failed", "failure"}:
        return None
    code = item.get("code") or item.get("status_code")
    suffix = f" ({code})" if isinstance(code, (str, int)) else ""
    # Do not include the provider's free-form detail: it can echo submitted
    # text, and Voice diagnostics intentionally contain no transcript content.
    return RuntimeError(f"real-time TTS provider error{suffix}")


class RealtimeTtsSession:
    """One provider-aware, persistent multi-context socket per Voice session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._ws = None
        self._provider = DEFAULT_TTS_PROVIDER
        self._signature: Optional[Tuple[str, str, str]] = None
        self._contexts: Dict[str, Tuple[Any, "queue.Queue[object]"]] = {}
        self._context_cfg: Dict[str, Dict[str, Any]] = {}
        self._finishing: set[str] = set()
        self._receiver: Optional[threading.Thread] = None

    def _connect(
        self,
        voice_id: str,
        model: str,
        provider: str = DEFAULT_TTS_PROVIDER,
    ):
        from websockets.sync.client import connect

        if provider == "cartesia":
            from rau.voice.cartesia_api import API_VERSION

            key = get_secret("CARTESIA_API_KEY")
            if not key:
                raise RuntimeError("CARTESIA_API_KEY not set")
            return connect(
                "wss://api.cartesia.ai/tts/websocket",
                additional_headers={
                    "X-API-Key": key,
                    "Cartesia-Version": API_VERSION,
                },
                open_timeout=6,
                close_timeout=2,
                ping_interval=15,
                ping_timeout=10,
                max_size=4 * 1024 * 1024,
            )
        if provider != "elevenlabs":
            raise RuntimeError(f"Unsupported TTS provider: {provider}")

        key = get_secret("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        params = urlencode(
            {
                "model_id": model,
                "output_format": "pcm_24000",
                # Hyper captions and phrase-bound body cues need a timeline
                # before/alongside each PCM response, not one aggregate
                # alignment after the whole context has played.
                "sync_alignment": "true",
                # The documented maximum keeps the session socket warm between
                # user turns; protocol pings cover transport keepalive.
                "inactivity_timeout": "180",
            }
        )
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/"
            f"{quote(voice_id, safe='')}/multi-stream-input?{params}"
        )
        return connect(
            url,
            additional_headers={"xi-api-key": key},
            open_timeout=6,
            close_timeout=2,
            ping_interval=15,
            ping_timeout=10,
            max_size=4 * 1024 * 1024,
        )

    def ensure(
        self,
        voice_id: str,
        model: str,
        provider: str = DEFAULT_TTS_PROVIDER,
    ) -> None:
        signature = (provider, voice_id, model)
        with self._connect_lock:
            with self._lock:
                if self._ws is not None and self._signature == signature:
                    return
            self._close_current()
            ws = self._connect(voice_id, model, provider)
            with self._lock:
                self._ws = ws
                self._provider = provider
                self._signature = signature
                self._receiver = threading.Thread(
                    target=self._receive,
                    args=(ws,),
                    daemon=True,
                    name="rau-realtime-tts-recv",
                )
                self._receiver.start()

    def warm(self) -> None:
        slot = get_slot("tts")
        provider = str(slot.get("provider") or DEFAULT_TTS_PROVIDER)
        self.ensure(
            str(slot.get("voice_id") or DEFAULT_VOICE_ID),
            str(
                slot.get("model")
                or (CARTESIA_TTS_MODEL if provider == "cartesia" else DEFAULT_TTS_MODEL)
            ),
            provider,
        )

    def _receive(self, ws) -> None:
        failure: Optional[BaseException] = None
        try:
            while True:
                raw = ws.recv()
                if raw is None:
                    break
                if isinstance(raw, bytes):
                    continue
                item = json.loads(raw)
                if not isinstance(item, dict):
                    continue
                context_id = item.get("contextId") or item.get("context_id")
                provider_error = _realtime_provider_error(item)
                if not isinstance(context_id, str):
                    # Socket-level errors do not carry a context id. Dropping
                    # one here strands every active turn waiting on an empty
                    # queue, so fail the socket and let each pre-audio turn
                    # take its normal HTTP fallback.
                    if provider_error is not None:
                        raise provider_error
                    continue
                with self._lock:
                    pair = self._contexts.get(context_id)
                    out = pair[1] if pair is not None and pair[0] is ws else None
                if out is not None:
                    out.put(provider_error or item)
        except BaseException as exc:
            failure = exc
        finally:
            # A provider error frame can terminate this receiver while the
            # transport itself remains open. Close that orphan explicitly so
            # reconnecting cannot leak a stale socket and its ping thread.
            try:
                ws.close()
            except Exception:
                pass
            with self._lock:
                if self._ws is ws:
                    self._ws = None
                    self._signature = None
                dead = [
                    context_id
                    for context_id, pair in self._contexts.items()
                    if pair[0] is ws
                ]
                contexts = [self._contexts.pop(context_id)[1] for context_id in dead]
                for context_id in dead:
                    self._context_cfg.pop(context_id, None)
                self._finishing.difference_update(dead)
            terminal = failure or RuntimeError("real-time TTS socket closed")
            for out in contexts:
                out.put(terminal)

    def _send(self, payload: Dict[str, Any], *, socket=None) -> None:
        with self._send_lock:
            if socket is None:
                with self._lock:
                    ws = self._ws
            else:
                ws = socket
            if ws is None:
                raise RuntimeError("real-time TTS socket is unavailable")
            ws.send(json.dumps(payload))

    def _context_socket(self, context_id: str):
        with self._lock:
            pair = self._contexts.get(context_id)
        if pair is None:
            raise RuntimeError("real-time TTS context is unavailable")
        return pair[0]

    def open_context(
        self,
        context_id: str,
        *,
        voice_id: str,
        model: str,
        voice_settings: Dict[str, Any],
        provider: str = DEFAULT_TTS_PROVIDER,
    ) -> "queue.Queue[object]":
        self.ensure(voice_id, model, provider)
        out: "queue.Queue[object]" = queue.Queue()
        with self._lock:
            ws = self._ws
            if ws is None:
                raise RuntimeError("real-time TTS socket is unavailable")
            self._finishing.discard(context_id)
            self._contexts[context_id] = (ws, out)
            self._context_cfg[context_id] = {
                "provider": provider,
                "voice_id": voice_id,
                "model": model,
                "voice_settings": dict(voice_settings or {}),
            }
        if provider == "cartesia":
            return out
        initial: Dict[str, Any] = {"context_id": context_id, "text": " "}
        if voice_settings:
            initial["voice_settings"] = voice_settings
        try:
            self._send(initial, socket=ws)
        except Exception:
            with self._lock:
                self._contexts.pop(context_id, None)
            raise
        return out

    def text(self, context_id: str, text: str, *, flush: bool = False) -> None:
        cfg = self._context_cfg.get(context_id) or {}
        if cfg.get("provider") == "cartesia":
            settings = cfg.get("voice_settings") or {}
            payload: Dict[str, Any] = {
                "model_id": cfg.get("model") or CARTESIA_TTS_MODEL,
                "transcript": text,
                "voice": {"mode": "id", "id": cfg.get("voice_id")},
                "context_id": context_id,
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": SR,
                },
                "continue": True,
                # Rau already buffers to natural sentence/clause boundaries.
                "max_buffer_delay_ms": 0,
                "generation_config": {
                    "speed": float(settings.get("speed", 1.0))
                },
            }
            if flush:
                payload["flush"] = True
            self._send(payload, socket=self._context_socket(context_id))
            return
        payload: Dict[str, Any] = {"context_id": context_id, "text": text}
        if flush:
            payload["flush"] = True
        self._send(payload, socket=self._context_socket(context_id))

    def flush_context(self, context_id: str) -> None:
        cfg = self._context_cfg.get(context_id) or {}
        if cfg.get("provider") == "cartesia":
            self.text(context_id, "", flush=True)
            return
        self._send(
            {"context_id": context_id, "flush": True},
            socket=self._context_socket(context_id),
        )

    def finish_context(self, context_id: str) -> None:
        """
        Gracefully end input while keeping the receive queue alive.

        ``flush`` only forces currently buffered text to be generated; the
        context remains open for more text and is therefore not required to
        emit ``is_final``. A normal completed model turn must close its input
        context too. We retain the local mapping until its final audio/terminal
        frame has been consumed.
        """
        socket = self._context_socket(context_id)
        cfg = self._context_cfg.get(context_id) or {}
        if cfg.get("provider") == "cartesia":
            payload = {
                "model_id": cfg.get("model") or CARTESIA_TTS_MODEL,
                "transcript": "",
                "voice": {"mode": "id", "id": cfg.get("voice_id")},
                "context_id": context_id,
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": SR,
                },
                "continue": False,
                "max_buffer_delay_ms": 0,
                "generation_config": {
                    "speed": float(
                        (cfg.get("voice_settings") or {}).get("speed", 1.0)
                    )
                },
            }
            self._send(payload, socket=socket)
        else:
            self._send(
                {"context_id": context_id, "close_context": True},
                socket=socket,
            )
        with self._lock:
            pair = self._contexts.get(context_id)
            if pair is not None and pair[0] is socket:
                self._finishing.add(context_id)

    def close_context(self, context_id: str) -> None:
        with self._lock:
            pair = self._contexts.pop(context_id, None)
            cfg = self._context_cfg.pop(context_id, {})
            was_finishing = context_id in self._finishing
            self._finishing.discard(context_id)
        if pair is None:
            return
        if was_finishing:
            return
        try:
            if cfg.get("provider") == "cartesia":
                self._send(
                    {"context_id": context_id, "cancel": True},
                    socket=pair[0],
                )
            else:
                self._send(
                    {"context_id": context_id, "close_context": True},
                    socket=pair[0],
                )
        except Exception:
            pass

    def _close_current(self) -> None:
        with self._lock:
            ws, self._ws = self._ws, None
            self._signature = None
        if ws is None:
            return
        if self._provider == "elevenlabs":
            try:
                with self._send_lock:
                    ws.send(json.dumps({"close_socket": True}))
            except Exception:
                pass
        try:
            ws.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._connect_lock:
            self._close_current()
        with self._lock:
            contexts = [pair[1] for pair in self._contexts.values()]
            self._contexts.clear()
            self._context_cfg.clear()
            self._finishing.clear()
        for out in contexts:
            out.put(RuntimeError("real-time TTS session closed"))
        receiver = self._receiver
        if receiver is not None and receiver is not threading.current_thread():
            receiver.join(timeout=0.5)


def speak_realtime_stream(
    tokens: Iterator[str],
    *,
    on_audio: Callable[[bytes], None],
    on_sentence: Optional[Callable[[str], None]] = None,
    on_timing: Optional[Callable[[SentenceTiming], None]] = None,
    cancel: Optional[threading.Event] = None,
    session: Optional[RealtimeTtsSession] = None,
    context_id: str = "turn",
) -> Generator[None, None, None]:
    """
    Feed generated phrases through the selected provider's TTS WebSocket.

    Connection setup happens before the token iterator is consumed, so a
    handshake failure can safely fall back to the established HTTP path.
    Once any audio is emitted, failures surface rather than replaying speech.
    """
    slot = get_slot("tts")
    provider = str(slot.get("provider") or DEFAULT_TTS_PROVIDER)
    voice_id = str(slot.get("voice_id") or DEFAULT_VOICE_ID)
    model = str(
        slot.get("model")
        or (CARTESIA_TTS_MODEL if provider == "cartesia" else DEFAULT_TTS_MODEL)
    )
    effect = str(slot.get("effect") or "none")
    voice_settings = dict(slot.get("voice_settings") or {})
    owned_session = session is None
    realtime = session or RealtimeTtsSession()

    # Do not consume a token until the low-latency transport is known-good.
    try:
        messages = realtime.open_context(
            context_id,
            voice_id=voice_id,
            model=model,
            voice_settings=voice_settings,
            provider=provider,
        )
    except Exception as exc:
        log.warning(
            "voice_tts_degraded profile=hyper stage=connect fallback=http "
            "context=%s error=%s",
            context_id,
            type(exc).__name__,
        )
        # Existing HTTP streaming is the quality-preserving fallback.
        yield from speak_stream(
            tokens,
            on_audio=on_audio,
            on_sentence=on_sentence,
            on_timing=on_timing,
            cancel=cancel,
        )
        if owned_session:
            realtime.close()
        return

    phrases: "deque[Tuple[str, str]]" = deque()
    phrases_ready = threading.Condition()
    sender_done = threading.Event()
    fallback_mode = threading.Event()
    sender_error: List[BaseException] = []
    replay: "queue.Queue[object]" = queue.Queue()
    replay_end = object()
    emitted = False
    received_audio = False
    first_phrase_sent_at = 0.0

    def sender() -> None:
        buf = SentenceBuffer()
        source = iter(_without_leading_emotion_tag(tokens))

        def send_phrase(sentence: str) -> None:
            nonlocal first_phrase_sent_at
            if fallback_mode.is_set():
                return
            spoken = normalize_for_tts(sentence)
            if not spoken:
                return
            with phrases_ready:
                phrases.append((sentence, spoken))
                phrases_ready.notify_all()
            if not first_phrase_sent_at:
                first_phrase_sent_at = time.monotonic()
            realtime.text(context_id, spoken + " ", flush=True)

        try:
            for token in source:
                if cancel is not None and cancel.is_set():
                    return
                replay.put(token)
                for sentence in buf.push(token):
                    send_phrase(sentence)
            tail = buf.flush()
            if tail:
                send_phrase(tail)
            if not fallback_mode.is_set():
                realtime.flush_context(context_id)
                finish = getattr(realtime, "finish_context", None)
                if callable(finish):
                    finish(context_id)
        except BaseException as exc:  # delivered to the receiver thread below
            if not fallback_mode.is_set():
                sender_error.append(exc)
            fallback_mode.set()
            realtime.close_context(context_id)
            # Keep sole ownership of the model iterator and feed the fallback
            # queue. This prevents two threads from calling next() on it after
            # a pre-audio socket failure.
            try:
                for token in source:
                    if cancel is not None and cancel.is_set():
                        break
                    replay.put(token)
            except BaseException as source_exc:
                sender_error.append(source_exc)
        finally:
            replay.put(replay_end)
            sender_done.set()
            with phrases_ready:
                phrases_ready.notify_all()

    worker = threading.Thread(target=sender, name="rau-realtime-tts-send", daemon=True)
    worker.start()

    current = ""
    current_spoken = ""
    collector: Optional[_AlignmentCollector] = None
    current_bytes = 0
    current_raw_bytes = 0
    aligned_chars = 0
    fx = StreamingRobotVoice(effect) if effect != "none" else None
    last_message_at = time.monotonic()

    def finish_current(*, timing_sent: bool = False) -> None:
        nonlocal current, current_spoken, collector
        nonlocal current_bytes, current_raw_bytes, aligned_chars
        if (
            not timing_sent
            and current
            and collector is not None
            and on_timing
            and current_bytes
        ):
            on_timing(collector.finish(bytes_duration_ms(current_bytes)))
        current = ""
        current_spoken = ""
        collector = None
        current_bytes = 0
        current_raw_bytes = 0
        aligned_chars = 0

    try:
        while True:
            if cancel is not None and cancel.is_set():
                break
            try:
                raw = messages.get(timeout=0.2)
            except queue.Empty:
                if sender_done.is_set() and sender_error:
                    raise sender_error[0]
                now = time.monotonic()
                if (
                    first_phrase_sent_at
                    and not received_audio
                    and now - first_phrase_sent_at
                    >= REALTIME_FIRST_AUDIO_TIMEOUT_SEC
                ):
                    raise TimeoutError(
                        "real-time TTS produced no audio before its deadline"
                    )
                if (
                    received_audio
                    and sender_done.is_set()
                    and now - last_message_at >= REALTIME_FINAL_IDLE_TIMEOUT_SEC
                ):
                    raise TimeoutError(
                        "real-time TTS did not finish the submitted context"
                    )
                if sender_done.is_set() and not first_phrase_sent_at:
                    # An empty/model-metadata-only response has nothing to
                    # synthesise. Do not wait forever for a context final that
                    # the provider has no reason to send.
                    break
                continue
            last_message_at = time.monotonic()
            if isinstance(raw, BaseException):
                raise raw
            item = raw
            if not isinstance(item, dict):
                continue
            encoded = item.get("audio") or item.get("data")
            pcm = base64.b64decode(encoded) if isinstance(encoded, str) and encoded else b""
            alignment = _ws_alignment(item)

            if pcm:
                received_audio = True
                current_raw_bytes += len(pcm)
                if current_raw_bytes > MAX_SENTENCE_PCM_BYTES:
                    raise RuntimeError("TTS sentence audio exceeded two minutes")
                if not current:
                    with phrases_ready:
                        if not phrases and not sender_done.is_set():
                            phrases_ready.wait(timeout=0.25)
                        if phrases:
                            current, current_spoken = phrases.popleft()
                        else:
                            current, current_spoken = "", ""
                    if current:
                        collector = _AlignmentCollector(current)
                        if on_sentence:
                            on_sentence(current)
                if collector is not None:
                    collector.add(alignment)
                if alignment is not None:
                    aligned_chars += len(alignment[0])
                chunks = fx.push(pcm) if fx is not None else [pcm]
                for chunk in chunks:
                    current_bytes += len(chunk)
                    emitted = True
                    on_audio(chunk)
                    yield None
                if current and aligned_chars >= len(current_spoken):
                    if fx is not None:
                        rendered = fx.flush()
                        rendered_bytes = sum(len(chunk) for chunk in rendered)
                        # Buffered effects release one phrase at a time. Put
                        # its character timeline on the browser socket before
                        # its PCM so the playback worklet's very first level
                        # report can reveal the bubble progressively.
                        if (
                            current
                            and collector is not None
                            and on_timing
                            and rendered_bytes
                        ):
                            on_timing(
                                collector.finish(bytes_duration_ms(rendered_bytes))
                            )
                        for chunk in rendered:
                            current_bytes += len(chunk)
                            emitted = True
                            on_audio(chunk)
                            yield None
                        fx = StreamingRobotVoice(effect)
                        finish_current(timing_sent=True)
                    else:
                        finish_current()
            if item.get("flush_done") and current:
                if fx is not None:
                    rendered = fx.flush()
                    rendered_bytes = sum(len(chunk) for chunk in rendered)
                    if collector is not None and on_timing and rendered_bytes:
                        on_timing(
                            collector.finish(bytes_duration_ms(rendered_bytes))
                        )
                    for chunk in rendered:
                        current_bytes += len(chunk)
                        emitted = True
                        on_audio(chunk)
                        yield None
                    fx = StreamingRobotVoice(effect)
                    finish_current(timing_sent=True)
                else:
                    finish_current()
            if item.get("isFinal") or item.get("is_final") or item.get("done") is True:
                if first_phrase_sent_at and not received_audio:
                    # A syntactically successful context with no PCM is still
                    # a failed speech turn. Because nothing reached playback,
                    # replaying through HTTP is safe and cannot duplicate.
                    raise RuntimeError("real-time TTS completed without audio")
                break

        if fx is not None:
            rendered = fx.flush()
            rendered_bytes = sum(len(chunk) for chunk in rendered)
            if (
                current
                and collector is not None
                and on_timing
                and rendered_bytes
            ):
                on_timing(collector.finish(bytes_duration_ms(rendered_bytes)))
            for chunk in rendered:
                current_bytes += len(chunk)
                emitted = True
                on_audio(chunk)
                yield None
            finish_current(timing_sent=True)
        else:
            finish_current()
        if sender_error:
            raise sender_error[0]
    except Exception as exc:
        if emitted:
            log.error(
                "voice_tts_failed profile=hyper stage=realtime "
                "fallback=prohibited_after_audio context=%s error=%s",
                context_id,
                type(exc).__name__,
            )
            raise
        log.warning(
            "voice_tts_degraded profile=hyper stage=realtime fallback=http "
            "context=%s error=%s received_audio=%s",
            context_id,
            type(exc).__name__,
            received_audio,
        )
        # No user-audible side effect: make the sender a token pump and replay
        # its complete queue into the established HTTP implementation.
        fallback_mode.set()
        realtime.close_context(context_id)

        def replay_tokens() -> Iterator[str]:
            while True:
                item = replay.get()
                if item is replay_end:
                    return
                yield str(item)

        yield from speak_stream(
            replay_tokens(),
            on_audio=on_audio,
            on_sentence=on_sentence,
            on_timing=on_timing,
            cancel=cancel,
        )
    finally:
        if cancel is not None and cancel.is_set():
            realtime.close_context(context_id)
        worker.join(timeout=0.2)
        realtime.close_context(context_id)
        if owned_session:
            realtime.close()


def pcm_duration_ms(pcm: bytes, sample_rate: int = SR) -> float:
    """How long a PCM16 mono buffer will take to play."""
    return bytes_duration_ms(len(pcm), sample_rate)


def bytes_duration_ms(byte_count: int, sample_rate: int = SR) -> float:
    """Same, for a byte count that was never held whole in memory."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return (max(0, int(byte_count)) // 2) / sample_rate * 1000.0

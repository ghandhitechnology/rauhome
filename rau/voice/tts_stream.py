"""
Streaming text-to-speech.

The old path (`rau.face.tts.tts`) collapses the ElevenLabs generator into one
buffer with `b"".join(gen)`, so nothing is heard until the whole reply has been
synthesised. Here we synthesise sentence by sentence and emit PCM as it
arrives, so Rau starts speaking while the model is still writing.
"""
from __future__ import annotations

import base64
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Generator, Iterator, List, Optional, Tuple

import numpy as np

from rau.env import get_secret
from rau.providers.registry import get_slot

SR = 24000

DEFAULT_VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"

#: Split on sentence enders, but keep the terminator with the sentence.
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…])$|\n{2,}")

#: Don't ship a fragment shorter than this to TTS — one-word chunks sound
#: clipped and cost a request each. Waits for more text instead.
MIN_CHARS = 24
#: ...unless it already ends a sentence, or we have this much queued.
MAX_CHARS = 220
MAX_SENTENCE_PCM_BYTES = SR * 2 * 120


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

    def push(self, token: str) -> List[str]:
        self._buf += token
        out: List[str] = []
        while True:
            match = _SENTENCE.search(self._buf)
            if match:
                head = self._buf[: match.end()].strip()
                rest = self._buf[match.end() :]
                if len(head) >= MIN_CHARS or len(rest) > 0:
                    out.append(head)
                    self._buf = rest
                    continue
            if len(self._buf) >= MAX_CHARS:
                # No punctuation in sight — cut at the last space so we do not
                # slice a word in half.
                cut = self._buf.rfind(" ", 0, MAX_CHARS)
                if cut <= 0:
                    cut = MAX_CHARS
                out.append(self._buf[:cut].strip())
                self._buf = self._buf[cut:]
                continue
            break
        return [s for s in out if s]

    def flush(self) -> Optional[str]:
        tail = self._buf.strip()
        self._buf = ""
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

    def __init__(self) -> None:
        self._board = None
        try:
            from pedalboard import Bitcrush, Distortion, Pedalboard, PitchShift, Reverb

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


def _client():
    from elevenlabs.client import ElevenLabs

    key = get_secret("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    return ElevenLabs(api_key=key)


def synth_sentence(
    text: str,
    *,
    client: Any = None,
    voice_id: str = "",
    model: str = "",
    cancel: Optional[threading.Event] = None,
) -> Iterator[bytes]:
    """Yield PCM16 chunks for one sentence, stopping early if cancelled."""
    slot = get_slot("tts") if not voice_id or not model else {}
    c = client or _client()
    stream = c.text_to_speech.stream(
        voice_id=voice_id or slot.get("voice_id") or DEFAULT_VOICE_ID,
        text=text,
        model_id=model or slot.get("model") or DEFAULT_TTS_MODEL,
        output_format="pcm_24000",
    )
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
    voice_id: str = "",
    model: str = "",
    cancel: Optional[threading.Event] = None,
) -> Iterator[Tuple[bytes, Optional[Tuple[List[str], List[float]]]]]:
    """
    Yield `(pcm, alignment)` for one sentence.

    Falls back to the plain stream — and therefore to `alignment=None` — for a
    client or an account that cannot serve character timestamps, so losing
    alignment costs cue precision rather than the voice.
    """
    slot = get_slot("tts") if not voice_id or not model else {}
    c = client or _client()
    vid = voice_id or slot.get("voice_id") or DEFAULT_VOICE_ID
    mid = model or slot.get("model") or DEFAULT_TTS_MODEL

    timed = getattr(getattr(c, "text_to_speech", None), "stream_with_timestamps", None)
    stream = None
    if callable(timed):
        try:
            stream = timed(
                voice_id=vid,
                text=text,
                model_id=mid,
                output_format="pcm_24000",
            )
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
        text, client=c, voice_id=vid, model=mid, cancel=cancel
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


def speak_stream(
    tokens: Iterator[str],
    *,
    on_audio: Callable[[bytes], None],
    on_sentence: Optional[Callable[[str], None]] = None,
    on_timing: Optional[Callable[[SentenceTiming], None]] = None,
    cancel: Optional[threading.Event] = None,
    robot: bool = True,
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
    fx = RobotVoice() if robot else None
    client = _client()
    slot = get_slot("tts")
    voice_id = str(slot.get("voice_id") or DEFAULT_VOICE_ID)
    model = str(slot.get("model") or DEFAULT_TTS_MODEL)

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
                voice_id=voice_id,
                model=model,
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
            voice_id=voice_id,
            model=model,
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
            processed = fx.process_pcm(bytes(parts))
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

    for token in tokens:
        if cancel is not None and cancel.is_set():
            return
        for sentence in buf.push(token):
            if not emit(sentence):
                return
        yield

    tail = buf.flush()
    if tail:
        emit(tail)


def pcm_duration_ms(pcm: bytes, sample_rate: int = SR) -> float:
    """How long a PCM16 mono buffer will take to play."""
    return bytes_duration_ms(len(pcm), sample_rate)


def bytes_duration_ms(byte_count: int, sample_rate: int = SR) -> float:
    """Same, for a byte count that was never held whole in memory."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return (max(0, int(byte_count)) // 2) / sample_rate * 1000.0

"""
Streaming text-to-speech.

The old path (`rau.face.tts.tts`) collapses the ElevenLabs generator into one
buffer with `b"".join(gen)`, so nothing is heard until the whole reply has been
synthesised. Here we synthesise sentence by sentence and emit PCM as it
arrives, so Rau starts speaking while the model is still writing.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Callable, Generator, Iterator, List, Optional

import numpy as np

from rau.env import get_secret
from rau.providers.registry import get_slot

SR = 24000

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
        voice_id=voice_id or slot.get("voice_id") or "TX3LPaxmHKxFdv7VOQHJ",
        text=text,
        model_id=model or slot.get("model") or "eleven_flash_v2_5",
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


def speak_stream(
    tokens: Iterator[str],
    *,
    on_audio: Callable[[bytes], None],
    on_sentence: Optional[Callable[[str], None]] = None,
    cancel: Optional[threading.Event] = None,
    robot: bool = True,
) -> Generator[None, None, None]:
    """
    Drive TTS from a token stream.

    `on_audio` receives PCM16 mono 24 kHz ready to play. `on_sentence` fires as
    each sentence begins synthesising, which is what drives Clawd's per-sentence
    reaction beats.
    """
    buf = SentenceBuffer()
    fx = RobotVoice() if robot else None
    client = _client()
    slot = get_slot("tts")
    voice_id = str(slot.get("voice_id") or "TX3LPaxmHKxFdv7VOQHJ")
    model = str(slot.get("model") or "eleven_flash_v2_5")

    def emit(sentence: str) -> bool:
        if cancel is not None and cancel.is_set():
            return False
        if on_sentence:
            on_sentence(sentence)

        if fx is None:
            # No FX: forward chunks the instant they arrive, lowest latency.
            for chunk in synth_sentence(
                sentence,
                client=client,
                voice_id=voice_id,
                model=model,
                cancel=cancel,
            ):
                if cancel is not None and cancel.is_set():
                    return False
                on_audio(chunk)
            return True

        # FX must see the whole sentence at once (see RobotVoice), so collect
        # it first. Granularity is a sentence, not the whole reply, so the
        # first words still arrive far sooner than the old one-shot path.
        parts = bytearray()
        for chunk in synth_sentence(
            sentence,
            client=client,
            voice_id=voice_id,
            model=model,
            cancel=cancel,
        ):
            if cancel is not None and cancel.is_set():
                return False
            if len(parts) + len(chunk) > MAX_SENTENCE_PCM_BYTES:
                raise RuntimeError("TTS sentence audio exceeded two minutes")
            parts.extend(chunk)
        if cancel is not None and cancel.is_set():
            return False
        if parts:
            on_audio(fx.process_pcm(bytes(parts)))
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
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return (len(pcm) // 2) / sample_rate * 1000.0

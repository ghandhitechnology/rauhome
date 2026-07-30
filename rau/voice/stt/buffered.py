"""
Base for STT backends that need a complete utterance.

Scribe, buffered OpenAI (whisper / gpt-4o-transcribe / gpt-transcribe), and
local whisper are all request/response: they cannot return anything until the
speaker stops. These buffer the PCM, then transcribe once when the caller
closes the stream, and emit a single final Transcript.

Partials from these backends would be a lie, so `supports_partials` stays False
and the UI shows a listening indicator instead of live text. Live OpenAI
(`gpt-live-transcribe`) uses the Realtime WebSocket path instead.
"""
from __future__ import annotations

import io
import wave
from abc import abstractmethod
from typing import AsyncIterator

from rau.voice.stt.base import SAMPLE_RATE, SttProvider, Transcript

#: Ignore blips shorter than this — a click or a door closing is not speech.
MIN_SAMPLES = SAMPLE_RATE // 5  # 200ms
MAX_PCM_BYTES = SAMPLE_RATE * 2 * 90  # 90 seconds of PCM16 mono


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw PCM16 mono in a WAV container, which every STT API accepts."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class BufferedStt(SttProvider):
    supports_partials = False

    @abstractmethod
    def transcribe(self, pcm: bytes) -> str:
        """Blocking transcription of a whole utterance. Runs in a thread."""
        raise NotImplementedError

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[Transcript]:
        import asyncio

        chunks = bytearray()
        async for frame in audio:
            if not isinstance(frame, bytes):
                raise ValueError("STT audio frames must be bytes")
            if len(frame) % 2:
                raise ValueError("STT audio ended with an incomplete PCM16 sample")
            if len(chunks) + len(frame) > MAX_PCM_BYTES:
                raise ValueError("STT utterance exceeds 90 seconds")
            chunks.extend(frame)

        if len(chunks) < MIN_SAMPLES * 2:  # 2 bytes per sample
            return

        # These are all blocking network or CPU work; keep the event loop free
        # so audio for the *next* utterance keeps flowing.
        text = await asyncio.to_thread(self.transcribe, bytes(chunks))
        text = (text or "").strip()
        if text:
            yield Transcript(text=text, final=True)

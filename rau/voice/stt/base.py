"""
Speech-to-text provider interface.

Every backend consumes the same thing — an async stream of raw PCM16 mono
frames at 16 kHz, exactly what the browser capture worklet emits — and yields
Transcript events. Providers that cannot do real partials simply never emit
`final=False`; callers must not assume partials will arrive.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

SAMPLE_RATE = 16000


@dataclass
class Transcript:
    text: str
    #: False for interim guesses that may still change, True once settled.
    final: bool = False
    confidence: Optional[float] = None


class SttProvider(ABC):
    name: str = "base"

    #: True when the backend emits interim results worth showing on screen.
    supports_partials: bool = False

    @abstractmethod
    async def stream(
        self, audio: AsyncIterator[bytes]
    ) -> AsyncIterator[Transcript]:
        """
        Transcribe `audio` until it is exhausted.

        Implementations must return promptly when the source stops; the caller
        closes it to signal end-of-utterance.
        """
        raise NotImplementedError
        yield  # pragma: no cover — makes this an async generator for typing

    async def close(self) -> None:
        """Release sockets/models. Safe to call more than once."""
        return None

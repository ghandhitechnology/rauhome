"""
Local faster-whisper STT.

No key, no network, no cost — the fallback when nothing else is configured, and
the only option that keeps the user's voice on the machine. Slower than the
cloud backends and cannot produce partials.

Shares the model singleton with the legacy host-side pipeline so we never hold
two copies of whisper in memory.
"""
from __future__ import annotations

import numpy as np

from rau.voice.stt.buffered import BufferedStt

_model = None


def _get_model(size: str):
    """Reuse the pipeline's loaded model when the size matches."""
    global _model
    from rau.face import pipeline

    if getattr(pipeline, "_whisper_model", None) is not None and size == "small":
        return pipeline._whisper_model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


class LocalWhisperStt(BufferedStt):
    name = "local"

    def __init__(self, model: str = "small", language: str = ""):
        self.model = model or "small"
        self.language = language or ""

    def transcribe(self, pcm: bytes) -> str:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = _get_model(self.model).transcribe(
            audio,
            language=self.language or None,
            beam_size=5,
            vad_filter=False,
        )
        return " ".join(s.text for s in segments).strip()

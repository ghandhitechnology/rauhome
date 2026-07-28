"""Korean pronunciation for speech synthesis.

The public surface is deliberately small: ask whether text is Korean, and get a
Hangul-only copy of it for the synthesiser.
"""
from __future__ import annotations

from rau.voice.korean.engine import (
    contains_hangul,
    is_korean,
    normalize_korean_for_tts,
)

__all__ = ["contains_hangul", "is_korean", "normalize_korean_for_tts"]

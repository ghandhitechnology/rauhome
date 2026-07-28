"""Particle agreement for text this library rewrites.

A Korean particle changes shape with the sound before it. Replacing a word
changes that sound, so the particle the author typed can end up wrong: someone
writes ``H2O와`` because "에이치 투 오" ends in a vowel, but the spoken form is
물, which takes 과.

This is only ever applied to a span that was just rewritten. Korean verb
endings are spelled like particles — ``먹는`` is not ``먹은`` — so a blanket
pass over a whole sentence would corrupt ordinary text.
"""
from __future__ import annotations

from typing import Dict, Final, Optional

from rau.voice.korean.hangul import decompose

#: (form after a final consonant, form after a vowel).
PAIRS: Final[tuple] = (
    ("이라고", "라고"), ("이라는", "라는"), ("이라도", "라도"),
    ("으로서", "로서"), ("으로써", "로써"), ("이에요", "예요"),
    ("이랑", "랑"), ("이나", "나"), ("이란", "란"), ("이야", "야"),
    ("으로", "로"), ("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"),
)
_PAIR_OF: Final[Dict[str, tuple]] = {form: pair for pair in PAIRS for form in pair}

#: Regex fragment adding an optional trailing particle to any pattern. The
#: named group is always ``particle``, so a pattern may only use it once.
SUFFIX: Final[str] = (
    "(?P<particle>(?:"
    + "|".join(sorted(_PAIR_OF, key=len, reverse=True))
    + ")(?![가-힣]))?"
)


def final_coda(reading: str) -> Optional[str]:
    """The last syllable's coda: ``""`` after a vowel, ``None`` if not Hangul."""
    for char in reversed(reading):
        parts = decompose(char)
        if parts:
            return parts[2]
        if not char.isspace():
            return None
    return None


def agree(reading: str, particle: str) -> str:
    """Attach ``particle`` in the form the new reading calls for."""
    if not particle:
        return reading
    pair = _PAIR_OF.get(particle)
    coda = final_coda(reading)
    if not pair or coda is None:
        return reading + particle
    consonant_form, vowel_form = pair
    if not coda:
        return reading + vowel_form
    # 서울로, not 서울으로: a ㄹ ending takes the vowel form of 으로.
    if coda == "ㄹ" and consonant_form.startswith("으로"):
        return reading + vowel_form
    return reading + consonant_form


__all__ = ["PAIRS", "SUFFIX", "agree", "final_coda"]

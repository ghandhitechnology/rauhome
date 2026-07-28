"""Hangul syllable assembly and the alphabet readings every other module needs.

Korean speech synthesis wants finished syllables, not jamo. Everything that
builds a reading — the transliterator, the acronym speller, the number writer —
composes here so the only place that knows the U+AC00 block layout is this file.
"""
from __future__ import annotations

from typing import Dict, Final

#: Initial consonants in Unicode order.
ONSETS: Final[str] = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
#: Vowels in Unicode order.
VOWELS: Final[str] = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
#: Final consonants in Unicode order; index 0 is "no coda".
CODAS: Final[str] = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

_ONSET_INDEX: Final[Dict[str, int]] = {jamo: i for i, jamo in enumerate(ONSETS)}
_VOWEL_INDEX: Final[Dict[str, int]] = {jamo: i for i, jamo in enumerate(VOWELS)}
_CODA_INDEX: Final[Dict[str, int]] = {jamo: i for i, jamo in enumerate(CODAS)}
_CODA_INDEX[""] = 0

SYLLABLE_START: Final[int] = 0xAC00
SYLLABLE_END: Final[int] = 0xD7A3

#: Codas a transliterated consonant may legally occupy. Anything outside this
#: set has to become its own syllable with a ``ㅡ`` support vowel instead.
CODA_CAPABLE: Final[frozenset] = frozenset("ㄱㄴㄷㄹㅁㅂㅅㅇ")

#: Adding a ``y`` glide to a plain vowel. Used for ``sh`` onsets (shy -> 샤이)
#: and for the ``u`` of *cute*.
Y_GLIDE: Final[Dict[str, str]] = {
    "ㅏ": "ㅑ", "ㅐ": "ㅒ", "ㅓ": "ㅕ", "ㅔ": "ㅖ", "ㅗ": "ㅛ", "ㅜ": "ㅠ",
    "ㅡ": "ㅣ", "ㅣ": "ㅣ",
}
#: Adding a ``w`` glide. ``ㅗ``/``ㅜ`` absorb it rather than doubling up.
W_GLIDE: Final[Dict[str, str]] = {
    "ㅏ": "ㅘ", "ㅐ": "ㅙ", "ㅓ": "ㅝ", "ㅔ": "ㅞ", "ㅣ": "ㅟ", "ㅗ": "ㅗ",
    "ㅜ": "ㅜ", "ㅡ": "ㅜ",
}


def compose(onset: str, vowel: str, coda: str = "") -> str:
    """Return one Hangul syllable, or ``""`` when the jamo are unusable."""
    try:
        lead = _ONSET_INDEX[onset]
        medial = _VOWEL_INDEX[vowel]
        tail = _CODA_INDEX[coda]
    except KeyError:
        return ""
    return chr(SYLLABLE_START + (lead * 21 + medial) * 28 + tail)


def decompose(syllable: str) -> tuple:
    """Return ``(onset, vowel, coda)`` for one syllable, or ``()`` if it is not one."""
    if len(syllable) != 1:
        return ()
    code = ord(syllable) - SYLLABLE_START
    if not 0 <= code <= SYLLABLE_END - SYLLABLE_START:
        return ()
    tail = code % 28
    medial = (code // 28) % 21
    lead = code // 588
    return ONSETS[lead], VOWELS[medial], (CODAS[tail] if tail else "")


def with_coda(syllable: str, coda: str) -> str:
    """Attach ``coda`` to an existing syllable that has none."""
    parts = decompose(syllable)
    if not parts or parts[2]:
        return ""
    return compose(parts[0], parts[1], coda)


def is_hangul(char: str) -> bool:
    """True for a composed Hangul syllable."""
    return len(char) == 1 and SYLLABLE_START <= ord(char) <= SYLLABLE_END


#: How Koreans say each Latin letter. Unknown acronyms are spelled out with
#: this table, which is why ``KBS`` still speaks as 케이비에스 without an entry.
LETTERS: Final[Dict[str, str]] = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프",
    "g": "지", "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘",
    "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
    "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스",
    "y": "와이", "z": "제트",
}

#: Digits spelled individually, for serial numbers and letter-by-letter codes.
DIGITS: Final[Dict[str, str]] = {
    "0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
    "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구",
}

#: Greek letters, which arrive in maths and physics text far more often than
#: any other non-Latin script.
GREEK: Final[Dict[str, str]] = {
    "α": "알파", "Α": "알파", "β": "베타", "Β": "베타", "γ": "감마", "Γ": "감마",
    "δ": "델타", "Δ": "델타", "ε": "엡실론", "Ε": "엡실론", "ζ": "제타", "Ζ": "제타",
    "η": "에타", "Η": "에타", "θ": "세타", "Θ": "세타", "ι": "이오타", "Ι": "이오타",
    "κ": "카파", "Κ": "카파", "λ": "람다", "Λ": "람다", "μ": "뮤", "Μ": "뮤",
    "ν": "뉴", "Ν": "뉴", "ξ": "크시", "Ξ": "크시", "ο": "오미크론", "Ο": "오미크론",
    "π": "파이", "Π": "파이", "ρ": "로", "Ρ": "로", "σ": "시그마", "Σ": "시그마",
    "ς": "시그마", "τ": "타우", "Τ": "타우", "υ": "웁실론", "Υ": "웁실론",
    "φ": "피", "Φ": "피", "χ": "카이", "Χ": "카이", "ψ": "프시", "Ψ": "프시",
    "ω": "오메가", "Ω": "오메가",
}

__all__ = [
    "CODA_CAPABLE",
    "CODAS",
    "DIGITS",
    "GREEK",
    "LETTERS",
    "ONSETS",
    "VOWELS",
    "W_GLIDE",
    "Y_GLIDE",
    "compose",
    "decompose",
    "is_hangul",
    "with_coda",
]

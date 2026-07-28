"""The merged Korean reading lexicon.

Each module is one domain. They are merged in the order below and the first
module to claim a key wins, so a collision resolves the same way on every run:
romanised Korean outranks everything (``kimchi`` must never be transliterated
as English), fixed expressions outrank single words, and the broad everyday
vocabulary comes last so a specialist reading is never overwritten by a generic
one.
"""
from __future__ import annotations

import re
from typing import Dict, Final, List, Pattern, Tuple

from rau.voice.korean.lexicon.academia import ACADEMIA
from rau.voice.korean.lexicon.acronyms import ACRONYMS
from rau.voice.korean.lexicon.basic import BASIC
from rau.voice.korean.lexicon.brands import BRANDS
from rau.voice.korean.lexicon.business import BUSINESS
from rau.voice.korean.lexicon.culture import CULTURE
from rau.voice.korean.lexicon.everyday import EVERYDAY
from rau.voice.korean.lexicon.expressions import EXPRESSIONS
from rau.voice.korean.lexicon.medicine import MEDICINE
from rau.voice.korean.lexicon.people import PEOPLE
from rau.voice.korean.lexicon.places import PLACES
from rau.voice.korean.lexicon.romanized import ROMANIZED
from rau.voice.korean.lexicon.science import SCIENCE
from rau.voice.korean.lexicon.technology import TECHNOLOGY

#: Merge order. Earlier modules win a key collision.
SOURCES: Final[Tuple[Tuple[str, Dict[str, str]], ...]] = (
    ("romanized", ROMANIZED),
    ("expressions", EXPRESSIONS),
    ("places", PLACES),
    ("brands", BRANDS),
    ("acronyms", ACRONYMS),
    ("people", PEOPLE),
    ("technology", TECHNOLOGY),
    ("science", SCIENCE),
    ("medicine", MEDICINE),
    ("business", BUSINESS),
    ("academia", ACADEMIA),
    ("culture", CULTURE),
    ("everyday", EVERYDAY),
    ("basic", BASIC),
)


def _merge(skip: str = "") -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for name, table in SOURCES:
        if name == skip:
            continue
        for key, reading in table.items():
            merged.setdefault(key, reading)
    return merged


#: Every reading, keyed by the lowercased written form.
WORDS: Final[Dict[str, str]] = _merge()

#: The same table without the acronyms. Consulted when a short key is only an
#: acronym reading and the source text did not capitalise it: an "IT" in Korean
#: text is 아이티, a lowercase "it" inside an English fragment is not.
NON_ACRONYM: Final[Dict[str, str]] = _merge(skip="acronyms")

#: Keys that carry an acronym reading, which is what the guard above checks.
ACRONYM_KEYS: Final[frozenset] = frozenset(ACRONYMS)

#: Multi-word entries, matched before single tokens and longest first.
PHRASES: Final[List[str]] = sorted(
    (key for key in WORDS if " " in key), key=len, reverse=True
)

_phrase_pattern: Pattern | None = None


def phrase_pattern() -> Pattern:
    """Compiled alternation over every multi-word entry, built on first use."""
    global _phrase_pattern
    if _phrase_pattern is None:
        alternatives = "|".join(
            re.escape(phrase).replace(r"\ ", r"[\s]+") for phrase in PHRASES
        )
        _phrase_pattern = re.compile(
            rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])", re.IGNORECASE
        )
    return _phrase_pattern


def lookup(key: str) -> str:
    """Return the reading for one lowercased key, or ``""``."""
    return WORDS.get(key, "")


def collisions() -> Dict[str, List[str]]:
    """Keys defined by more than one module, for the consistency test."""
    seen: Dict[str, List[str]] = {}
    for name, table in SOURCES:
        for key in table:
            seen.setdefault(key, []).append(name)
    return {key: names for key, names in seen.items() if len(names) > 1}


__all__ = [
    "ACRONYM_KEYS",
    "NON_ACRONYM",
    "PHRASES",
    "SOURCES",
    "WORDS",
    "collisions",
    "lookup",
    "phrase_pattern",
]

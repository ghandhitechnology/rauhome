"""Turn Korean text containing Latin script and notation into pure Hangul speech.

A Korean voice reads Hangul. Everything else — an English brand name, a unit
symbol, a chemical formula, a bare acronym — is either mispronounced or read in
a sudden English accent that breaks the sentence. This module rewrites all of
it before the text reaches the synthesiser.

Nothing here can raise into the audio path: :func:`normalize_korean_for_tts`
catches everything and returns the original text, because a slightly awkward
reading is always better than silence.
"""
from __future__ import annotations

import re
from typing import Dict, Final, List, Match

from rau.voice.korean import lexicon
from rau.voice.korean.hangul import DIGITS, GREEK, LETTERS
from rau.voice.korean.lexicon.chemistry import BARE_SYMBOLS, ELEMENTS, FORMULAS
from rau.voice.korean.numbers import apply_numbers
from rau.voice.korean.particles import SUFFIX as _PARTICLE_SUFFIX
from rau.voice.korean.particles import agree as _agree
from rau.voice.korean.transliterate import hangulize
from rau.voice.korean.units import BARE_UNITS, apply_units
from rau.voice.verbatim import protect

_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_LATIN = re.compile(r"[A-Za-z]")


def contains_hangul(text: str) -> bool:
    """True when the text has any Korean in it."""
    return bool(_HANGUL.search(text))


def is_korean(text: str) -> bool:
    """True when the text should be spoken by a Korean voice.

    Any Hangul at all is enough. A sentence that mixes the two scripts is a
    Korean sentence with foreign words in it, which is exactly the case this
    library handles.
    """
    return contains_hangul(text)


# ---------------------------------------------------------------- chemistry

_SUBSCRIPT: Final[Dict[int, int]] = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FORMULA_PIECE = re.compile(r"([A-Z][a-z]?)([0-9]*)")
_FORMULA = re.compile(
    r"(?P<formula>"
    r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?[0-9₀₁₂₃₄₅₆₇₈₉]*){2,}(?![A-Za-z])|"
    r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?)[0-9₀₁₂₃₄₅₆₇₈₉]+(?![A-Za-z])"
    r")" + _PARTICLE_SUFFIX
)


def _formula(match: Match) -> str:
    source = match.group("formula")
    particle = match.group("particle") or ""
    plain = source.translate(_SUBSCRIPT)
    settled = FORMULAS.get(plain)
    if settled:
        return _agree(settled, particle)
    # Without a digit, a run of capitals is an acronym far more often than a
    # compound — KBS is a broadcaster, not 칼륨 붕소 황.
    if not any(char.isdigit() for char in plain):
        return match.group(0)
    pieces = _FORMULA_PIECE.findall(plain)
    if not pieces or "".join(sym + num for sym, num in pieces) != plain:
        return match.group(0)
    if any(symbol not in ELEMENTS for symbol, _count in pieces):
        return match.group(0)
    spoken: List[str] = []
    for symbol, count in pieces:
        spoken.append(ELEMENTS[symbol])
        if count:
            spoken.append(count)
    return _agree(" ".join(spoken), particle)


# ------------------------------------------------------------------ symbols

#: Operators only become words between numbers. A bare hyphen in ``2026-07-29``
#: or an ampersand in a company name must survive untouched.
_OPERATORS: Final[tuple] = (
    (re.compile(r"(?<=\d)\s*\+\s*(?=\d)"), " 더하기 "),
    (re.compile(r"(?<=\d)\s+[-−]\s+(?=\d)"), " 빼기 "),
    (re.compile(r"(?<=\d)\s*[×xX*]\s*(?=\d)"), " 곱하기 "),
    (re.compile(r"(?<=\d)\s*÷\s*(?=\d)"), " 나누기 "),
    (re.compile(r"(?<=\d)\s*=\s*(?=\d)"), " 는 "),
)
#: A colon between numbers is a ratio here. The clock reading is claimed
#: earlier, by the number pass, so that its hour can become native Korean.
_COLON_RATIO = re.compile(r"(?<![\d:])(?P<left>\d+)\s*:\s*(?P<right>\d+)(?![\d:])")

#: Operators are padded so they never fuse with a neighbouring word; nouns are
#: not, because a particle usually follows them (``∞로`` -> 무한대로).
_SYMBOLS: Final[tuple] = (
    ("±", " 플러스 마이너스 "),
    ("≤", " 이하 "),
    ("≥", " 이상 "),
    ("≠", " 같지 않음 "),
    ("≈", " 약 "),
    ("→", " 에서 "),
    ("←", " 로부터 "),
    ("↑", " 상승 "),
    ("↓", " 하락 "),
    ("∞", "무한대"),
    ("√", "루트 "),
    ("©", "카피라이트"),
    ("№", "넘버 "),
    ("®", ""),
    ("™", ""),
)
_TILDE_ABOUT = re.compile(r"(?<![\w가-힣])~\s*(?=\d)")
_HASH_NUMBER = re.compile(r"(?<![\w가-힣])#\s*(\d+)")
_AMPERSAND = re.compile(r"(?<=[\s가-힣])&(?=[\s가-힣])|(?<=[A-Za-z0-9])\s+&\s+(?=[A-Za-z0-9])")
_AT_SIGN = re.compile(r"(?<=\s)@(?=\s)")
_GREEK = re.compile("|".join(re.escape(letter) for letter in GREEK))


def _apply_symbols(text: str) -> str:
    value = _COLON_RATIO.sub(lambda m: f"{m.group('left')} 대 {m.group('right')}", text)
    for pattern, replacement in _OPERATORS:
        value = pattern.sub(replacement, value)
    value = _TILDE_ABOUT.sub("약 ", value)
    value = _HASH_NUMBER.sub(r"\1번", value)
    value = _AMPERSAND.sub(" 앤드 ", value)
    value = _AT_SIGN.sub(" 앳 ", value)
    for glyph, replacement in _SYMBOLS:
        value = value.replace(glyph, replacement)
    value = _GREEK.sub(lambda m: GREEK[m.group(0)], value)
    return value


# -------------------------------------------------------------- Latin words

#: One run of Latin script, including the punctuation that lives inside names
#: and initialisms: ``mcdonald's``, ``x-ray``, ``ci/cd``, ``s&p``, ``u.s.``.
_WORD = re.compile(
    r"(?P<word>[A-Za-z][A-Za-z0-9'’&+./\-]*[A-Za-z0-9.]|[A-Za-z])" + _PARTICLE_SUFFIX
)
_SEPARATORS = re.compile(r"[-/&+.]")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ALNUM_SPLIT = re.compile(r"(\d+)")
_UPPER = re.compile(r"^[A-Z0-9&+.\-/']+$")


def _spell_out(token: str) -> str:
    """Read a token one character at a time: KBS -> 케이비에스."""
    spoken = [
        LETTERS.get(char.lower()) or DIGITS.get(char) or ""
        for char in token
    ]
    return "".join(spoken)


def _lookup(key: str, *, upper: bool) -> str:
    """Lexicon hit for one key, with the short-acronym guard applied."""
    reading = lexicon.WORDS.get(key, "")
    if not reading:
        return ""
    if len(key) <= 2 and not upper and key in lexicon.ACRONYM_KEYS:
        # "IT" is 아이티, but a lowercase "it" in an English fragment is not.
        return lexicon.NON_ACRONYM.get(key, "")
    return reading


def _speak_word(raw: str) -> str:
    """Return the Hangul reading of one Latin token. Never returns Latin."""
    token = raw.rstrip(".")
    trailing = raw[len(token):]
    if not token or not _LATIN.search(token):
        # A digit or punctuation fragment from a split token: leave it be.
        return raw
    if trailing:
        # "u.s." keeps its dots; "jumps." does not, and the sentence needs the
        # full stop back for its prosody.
        dotted = _lookup(raw.casefold(), upper=bool(_UPPER.match(raw)))
        if dotted:
            return dotted
        return _speak_word(token) + trailing

    upper = bool(_UPPER.match(token)) and _LATIN.search(token) is not None
    key = token.casefold().replace("’", "'")

    reading = _lookup(key, upper=upper)
    if reading:
        return reading
    if len(token) == 2 and token in BARE_SYMBOLS:
        return BARE_SYMBOLS[token]
    unit = BARE_UNITS.get(token)
    if unit:
        return unit

    if key.endswith("'s"):
        base = _lookup(key[:-2], upper=upper)
        if base:
            return f"{base}의"
    if key.endswith("s") and not key.endswith("ss"):
        singular = key[:-3] + "y" if key.endswith("ies") else key[:-1]
        base = _lookup(singular, upper=upper)
        if base:
            return f"{base}스"

    if _SEPARATORS.search(token):
        parts = [part for part in _SEPARATORS.split(token) if part]
        if len(parts) > 1:
            return "".join(_speak_word(part) for part in parts)

    if any(char.isdigit() for char in token):
        pieces = [piece for piece in _ALNUM_SPLIT.split(token) if piece]
        if len(pieces) > 1:
            return " ".join(
                piece if piece.isdigit() else _speak_word(piece) for piece in pieces
            )

    if upper and 2 <= len(token) <= 8:
        return _spell_out(token)

    split = _CAMEL.split(token)
    if len(split) > 1:
        return "".join(_speak_word(part) for part in split)

    if len(token) == 1:
        return LETTERS.get(key, "")
    return hangulize(key)


_phrase_with_particle: re.Pattern | None = None


def _phrase_pattern() -> re.Pattern:
    global _phrase_with_particle
    if _phrase_with_particle is None:
        inner = lexicon.phrase_pattern().pattern
        _phrase_with_particle = re.compile(
            f"(?P<phrase>{inner}){_PARTICLE_SUFFIX}", re.IGNORECASE
        )
    return _phrase_with_particle


def _phrase(match: Match) -> str:
    phrase = match.group("phrase")
    reading = lexicon.WORDS.get(re.sub(r"\s+", " ", phrase.casefold()), "")
    if not reading:
        return match.group(0)
    return _agree(reading, match.group("particle") or "")


def _word(match: Match) -> str:
    return _agree(_speak_word(match.group("word")), match.group("particle") or "")


def _apply_words(text: str) -> str:
    return _WORD.sub(_word, _phrase_pattern().sub(_phrase, text))


# ------------------------------------------------------------------ pipeline

_SPACES = re.compile(r"[ \t]{2,}")
_LINES = re.compile(r" *\n *")


def normalize_korean_for_tts(text: str) -> str:
    """Return a Hangul-only speakable copy of Korean text.

    Falls back to the input unchanged on any internal error — this runs inline
    on the audio path and must never be the reason a sentence goes unspoken.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        value, restore = protect(text)
        value = apply_units(value)
        value = _FORMULA.sub(_formula, value)
        # Numbers before symbols: the clock has to claim ``14:05`` before the
        # ratio rule turns it into 대, and the 대 a ratio produces must not then
        # look like a native counter.
        value = apply_numbers(value)
        value = _apply_symbols(value)
        value = _apply_words(value)
        value = _SPACES.sub(" ", value)
        value = _LINES.sub("\n", value).strip()
        return restore(value)
    except Exception:  # pragma: no cover - defensive, see docstring
        return text


__all__ = ["contains_hangul", "is_korean", "normalize_korean_for_tts"]

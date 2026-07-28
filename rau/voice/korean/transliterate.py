"""Rule-based English-to-Hangul transliteration — the library's safety net.

The lexicon carries the words Koreans have already settled on. This module
exists for everything else: a product name coined last week, a surname, a
misspelling. It never returns Latin text, so a Korean voice is never handed a
character it cannot read.

The pipeline is spelling -> phonemes -> syllables. Phonemes are deliberately
coarse; the goal is the reading a Korean would write down after hearing the
word once, not a phonetic transcription. Where English spelling is genuinely
ambiguous (``-ow``, ``-oo``) the rule picks the commoner outcome and the
lexicon overrides it for words that matter.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from rau.voice.korean.hangul import (
    CODA_CAPABLE,
    W_GLIDE,
    Y_GLIDE,
    compose,
    decompose,
    with_coda,
)

#: A phoneme is ``("c", name)`` for a consonant or ``("v", jamo, long)`` for a
#: vowel. ``jamo`` may hold more than one vowel, each becoming its own syllable
#: (``ai`` -> 아이). ``long`` suppresses the short-vowel coda rule.
_Token = Tuple

def _c(name: str) -> _Token:
    return ("c", name)


def _v(jamo: str, long: bool = False) -> _Token:
    return ("v", jamo, long)


# Ordered spelling rules. The first pattern that matches at the cursor wins, so
# suffixes and digraphs come before single letters. Patterns are anchored at the
# cursor by ``match(word, index)``; lookarounds still see the whole word.
_RULES: Sequence[Tuple[re.Pattern, Sequence[_Token]]] = [
    # -- Latinate endings ------------------------------------------------
    (re.compile(r"tions$"), (_c("sh"), _v("ㅓ"), _c("n"), _c("s"))),
    (re.compile(r"tional$"), (_c("sh"), _v("ㅓ"), _c("n"), _v("ㅓ"), _c("l"))),
    (re.compile(r"tion$"), (_c("sh"), _v("ㅓ"), _c("n"))),
    (re.compile(r"ssion$"), (_c("sh"), _v("ㅓ"), _c("n"))),
    (re.compile(r"sion$"), (_c("j"), _v("ㅓ"), _c("n"))),
    (re.compile(r"cian$"), (_c("sh"), _v("ㅓ"), _c("n"))),
    (re.compile(r"gion$"), (_c("j"), _v("ㅓ"), _c("n"))),
    (re.compile(r"tures$"), (_c("ch"), _v("ㅓ"), _c("s"))),
    (re.compile(r"ture$"), (_c("ch"), _v("ㅓ"))),
    (re.compile(r"sure$"), (_c("j"), _v("ㅓ"))),
    (re.compile(r"cial$"), (_c("sh"), _v("ㅓ"), _c("l"))),
    (re.compile(r"tial$"), (_c("sh"), _v("ㅓ"), _c("l"))),
    (re.compile(r"ious$"), (_v("ㅣ"), _v("ㅓ"), _c("s"))),
    (re.compile(r"eous$"), (_v("ㅣ"), _v("ㅓ"), _c("s"))),
    (re.compile(r"ous$"), (_v("ㅓ"), _c("s"))),
    (re.compile(r"ance$"), (_v("ㅓ"), _c("n"), _c("s"))),
    (re.compile(r"ence$"), (_v("ㅓ"), _c("n"), _c("s"))),
    (re.compile(r"ment$"), (_c("m"), _v("ㅓ"), _c("n"), _c("t"))),
    (re.compile(r"(?<=[a-z]{3})able$"), (_v("ㅓ"), _c("b"), _v("ㅡ"), _c("l"))),
    (re.compile(r"(?<=[a-z]{3})ible$"), (_v("ㅣ"), _c("b"), _v("ㅡ"), _c("l"))),
    (re.compile(r"(?<=[bcdfgkpstvz])le$"), (_v("ㅡ"), _c("l"))),
    (re.compile(r"que$"), (_c("k"),)),
    (re.compile(r"gue$"), (_c("g"),)),
    (re.compile(r"ing$"), (_v("ㅣ"), _c("ng"))),
    (re.compile(r"gy$"), (_c("j"), _v("ㅣ"))),
    (re.compile(r"eate$"), (_v("ㅣㅔㅣ", True), _c("t"))),
    (re.compile(r"ies$"), (_v("ㅣ"), _c("s"))),
    (re.compile(r"ey$"), (_v("ㅣ"),)),
    (re.compile(r"ery$"), (_v("ㅓ"), _c("r"), _v("ㅣ"))),
    (re.compile(r"(?<=[a-z]{3})y$"), (_v("ㅣ"),)),
    (re.compile(r"y$"), (_v("ㅏㅣ"),)),
    # -- r-coloured vowels, before the magic-e and plain vowel rules -----
    # ``wor`` is 워, not 오: work 워크, world 월드, word 워드.
    (re.compile(r"wor(?=[^aeiou])"), (_c("w"), _v("ㅓ", True))),
    (re.compile(r"are$"), (_v("ㅔㅓ", True),)),
    (re.compile(r"ere$"), (_v("ㅣㅓ", True),)),
    (re.compile(r"ire$"), (_v("ㅏㅣㅓ", True),)),
    (re.compile(r"ore$"), (_v("ㅗ", True),)),
    (re.compile(r"ure$"), (_v("ㅜㅓ", True),)),
    (re.compile(r"ear(?![a-z])|ear(?=[^aeiouy])"), (_v("ㅣㅓ", True),)),
    (re.compile(r"air(?![a-z])|air(?=[^aeiouy])"), (_v("ㅔㅓ", True),)),
    (re.compile(r"our(?![a-z])|our(?=[^aeiouy])"), (_v("ㅜㅓ", True),)),
    (re.compile(r"ar(?![a-z])|ar(?=[^aeiouy])"), (_v("ㅏ", True),)),
    (re.compile(r"or$"), (_v("ㅓ", True),)),
    (re.compile(r"or(?=[^aeiouy])"), (_v("ㅗ", True),)),
    (re.compile(r"(?:er|ir|ur|yr)(?![a-z])"), (_v("ㅓ", True),)),
    (re.compile(r"(?:er|ir|ur|yr)(?=[^aeiouy])"), (_v("ㅓ", True),)),
    # -- silent-e lengthening --------------------------------------------
    (re.compile(r"a(?=[bcdfgklmnprstvz]e$)"), (_v("ㅔㅣ", True),)),
    (re.compile(r"i(?=[bcdfgklmnprstvz]e$)"), (_v("ㅏㅣ", True),)),
    (re.compile(r"o(?=[bcdfgklmnprstvz]e$)"), (_v("ㅗ", True),)),
    # After ㄹ or ㅈ the glide is not used: rule 룰, June 준, not 률/쥰.
    (re.compile(r"(?<=[rlj])u(?=[bcdfgklmnprstvz]e$)"), (_v("ㅜ", True),)),
    (re.compile(r"u(?=[bcdfgklmnprstvz]e$)"), (_v("ㅠ", True),)),
    (re.compile(r"e(?=[bcdfgklmnprstvz]e$)"), (_v("ㅣ", True),)),
    (re.compile(r"i(?=gh)"), (_v("ㅏㅣ", True),)),
    # -- vowel digraphs ---------------------------------------------------
    (re.compile(r"eau"), (_v("ㅗ", True),)),
    (re.compile(r"ee"), (_v("ㅣ", True),)),
    (re.compile(r"ea"), (_v("ㅣ", True),)),
    (re.compile(r"ie"), (_v("ㅣ", True),)),
    (re.compile(r"ei"), (_v("ㅔㅣ", True),)),
    (re.compile(r"ai"), (_v("ㅔㅣ", True),)),
    (re.compile(r"ay"), (_v("ㅔㅣ", True),)),
    (re.compile(r"oa"), (_v("ㅗ", True),)),
    (re.compile(r"oo"), (_v("ㅜ"),)),
    (re.compile(r"ou"), (_v("ㅏㅜ", True),)),
    (re.compile(r"ow$"), (_v("ㅗㅜ", True),)),
    (re.compile(r"ow"), (_v("ㅏㅜ", True),)),
    # Word-final it stays a diphthong: Rau 라우. Elsewhere it is 오 (author 오서),
    # and the earlier ``eau`` rule keeps 플라토 intact.
    (re.compile(r"au$"), (_v("ㅏㅜ", True),)),
    (re.compile(r"au"), (_v("ㅗ", True),)),
    (re.compile(r"aw"), (_v("ㅗ", True),)),
    (re.compile(r"oi"), (_v("ㅗㅣ", True),)),
    (re.compile(r"oy"), (_v("ㅗㅣ", True),)),
    (re.compile(r"ui"), (_v("ㅜ", True),)),
    (re.compile(r"ue"), (_v("ㅜ", True),)),
    (re.compile(r"ew"), (_v("ㅠ", True),)),
    (re.compile(r"eu"), (_v("ㅠ", True),)),
    (re.compile(r"oe"), (_v("ㅗ", True),)),
    (re.compile(r"eo"), (_v("ㅣㅗ", True),)),
    (re.compile(r"ia"), (_v("ㅣㅏ", True),)),
    (re.compile(r"io"), (_v("ㅣㅗ", True),)),
    (re.compile(r"iu"), (_v("ㅣㅜ", True),)),
    # -- consonant clusters ----------------------------------------------
    # -- doubled consonants, halved but only after the vowel rules above have
    #    seen them: a doubled consonant is what makes 애플 out of *apple*.
    (re.compile(r"cc(?=[eiy])"), (_c("k"), _c("s"))),
    (re.compile(r"ll(?=[aeiouy])"), (_c("l"), _c("l"))),
    (re.compile(r"bb"), (_c("b"),)),
    (re.compile(r"cc"), (_c("k"),)),
    (re.compile(r"dd"), (_c("d"),)),
    (re.compile(r"ff"), (_c("f"),)),
    (re.compile(r"gg"), (_c("g"),)),
    (re.compile(r"kk"), (_c("k"),)),
    (re.compile(r"ll"), (_c("l"),)),
    (re.compile(r"mm"), (_c("m"),)),
    (re.compile(r"nn"), (_c("n"),)),
    (re.compile(r"pp"), (_c("p"),)),
    (re.compile(r"rr"), (_c("r"),)),
    (re.compile(r"ss"), (_c("s"),)),
    (re.compile(r"tt"), (_c("t"),)),
    (re.compile(r"zz"), (_c("z"),)),
    (re.compile(r"sch"), (_c("s"), _c("k"))),
    (re.compile(r"tch"), (_c("ch"),)),
    (re.compile(r"ch"), (_c("ch"),)),
    (re.compile(r"sh"), (_c("sh"),)),
    (re.compile(r"ph"), (_c("f"),)),
    (re.compile(r"gh(?=t)"), ()),
    (re.compile(r"gh$"), ()),
    (re.compile(r"gh"), (_c("g"),)),
    (re.compile(r"wh(?=o)"), (_c("h"),)),
    (re.compile(r"wh"), (_c("w"),)),
    (re.compile(r"(?<![a-z])kn"), (_c("n"),)),
    (re.compile(r"(?<![a-z])wr"), (_c("r"),)),
    (re.compile(r"(?<![a-z])ps"), (_c("s"),)),
    (re.compile(r"mb$"), (_c("m"),)),
    (re.compile(r"mn$"), (_c("m"),)),
    (re.compile(r"ck"), (_c("k"),)),
    (re.compile(r"nk"), (_c("ng"), _c("k"))),
    (re.compile(r"ng"), (_c("ng"),)),
    (re.compile(r"qu"), (_c("k"), _c("w"))),
    (re.compile(r"(?<![a-z])x"), (_c("z"),)),
    (re.compile(r"x"), (_c("k"), _c("s"))),
    (re.compile(r"(?<=[aeiou])th(?=[aeiou])"), (_c("dh"),)),
    (re.compile(r"th"), (_c("th"),)),
    (re.compile(r"c(?=[eiy])"), (_c("s"),)),
    # Between vowels an ``s`` voices: music 뮤직, user 유저, president 프레지던트.
    (re.compile(r"(?<=[aeiou])s(?=[aeiou])(?!e$)"), (_c("z"),)),
    (re.compile(r"c"), (_c("k"),)),
    # -- plain vowels ------------------------------------------------------
    (re.compile(r"a(?=tion|sion|ture$)"), (_v("ㅔㅣ", True),)),
    (re.compile(r"a(?=([bcdfgklmnprstvz])\1)"), (_v("ㅐ"),)),
    (re.compile(r"a(?=[nm][bcdfgkpstvz])"), (_v("ㅐ"),)),
    (re.compile(r"a(?=[bcdfgklmnpstvz]$)"), (_v("ㅐ"),)),
    (re.compile(r"a"), (_v("ㅏ"),)),
    (re.compile(r"e$"), ()),
    (re.compile(r"e"), (_v("ㅔ"),)),
    (re.compile(r"i"), (_v("ㅣ"),)),
    (re.compile(r"o"), (_v("ㅗ"),)),
    (re.compile(r"u(?=ll)"), (_v("ㅜ"),)),
    # An open syllable lengthens it: music 뮤직, future 퓨처, super 슈퍼 —
    # but never after ㄹ or ㅈ: Bruno 브루노, ruby 루비, Julia 줄리아.
    (re.compile(r"(?<=[rlj])u(?=[bcdfgklmnprstvz][aeiouy])"), (_v("ㅜ", True),)),
    (re.compile(r"u(?=[bcdfgklmnprstvz][aeiou])"), (_v("ㅠ", True),)),
    (re.compile(r"u"), (_v("ㅓ"),)),
    (re.compile(r"y(?=[aeiou])"), (_c("y"),)),
    (re.compile(r"y"), (_v("ㅣ"),)),
    # -- plain consonants --------------------------------------------------
    (re.compile(r"w(?=[aeiou])"), (_c("w"),)),
    (re.compile(r"w"), ()),
    (re.compile(r"h"), (_c("h"),)),
    (re.compile(r"b"), (_c("b"),)),
    (re.compile(r"d"), (_c("d"),)),
    (re.compile(r"f"), (_c("f"),)),
    (re.compile(r"g"), (_c("g"),)),
    (re.compile(r"j"), (_c("j"),)),
    (re.compile(r"k"), (_c("k"),)),
    (re.compile(r"l"), (_c("l"),)),
    (re.compile(r"m"), (_c("m"),)),
    (re.compile(r"n"), (_c("n"),)),
    (re.compile(r"p"), (_c("p"),)),
    (re.compile(r"q"), (_c("k"),)),
    (re.compile(r"r"), (_c("r"),)),
    (re.compile(r"s"), (_c("s"),)),
    (re.compile(r"t"), (_c("t"),)),
    (re.compile(r"v"), (_c("v"),)),
    (re.compile(r"z"), (_c("z"),)),
]

#: Onset jamo for each consonant phoneme.
_ONSET_OF: Dict[str, str] = {
    "k": "ㅋ", "g": "ㄱ", "t": "ㅌ", "d": "ㄷ", "p": "ㅍ", "b": "ㅂ",
    "f": "ㅍ", "v": "ㅂ", "s": "ㅅ", "z": "ㅈ", "sh": "ㅅ", "ch": "ㅊ",
    "j": "ㅈ", "th": "ㅅ", "dh": "ㄷ", "m": "ㅁ", "n": "ㄴ", "ng": "ㅇ",
    "l": "ㄹ", "r": "ㄹ", "h": "ㅎ",
}
#: The syllable a consonant becomes when no vowel follows and it cannot be a
#: coda: 데스크, 테스트, 피시. ``h`` and ``r`` simply disappear.
_SUPPORT_OF: Dict[str, str] = {
    "k": "크", "g": "그", "t": "트", "d": "드", "p": "프", "b": "브",
    "f": "프", "v": "브", "s": "스", "z": "즈", "sh": "시", "ch": "치",
    "j": "지", "th": "스", "dh": "드",
}
#: Consonants that ride on the previous syllable as a coda.
_CODA_OF: Dict[str, str] = {"m": "ㅁ", "n": "ㄴ", "ng": "ㅇ", "l": "ㄹ"}
#: 짧은 모음 + 무성 파열음 = 받침 (cat 캣, cap 캡, book 북).
_STOP_CODA: Dict[str, str] = {"k": "ㄱ", "t": "ㅅ", "p": "ㅂ"}

def _phonemes(word: str) -> List[_Token]:
    tokens: List[_Token] = []
    index = 0
    length = len(word)
    while index < length:
        for pattern, produced in _RULES:
            match = pattern.match(word, index)
            if match and match.end() > index:
                tokens.extend(produced)
                index = match.end()
                break
        else:
            # Nothing claimed this character (a stray apostrophe or digit that
            # slipped through); skipping keeps the walk finite.
            index += 1
    return tokens


def _next_takes_vowel(tokens: Sequence[_Token], index: int) -> bool:
    """True when the phoneme after ``index`` will need an onset."""
    for token in tokens[index + 1:]:
        if token[0] == "v":
            return True
        if token[1] in ("w", "y"):
            continue
        return False
    return False


def _assemble(tokens: Sequence[_Token]) -> str:
    syllables: List[str] = []
    onset: Optional[str] = None
    glide = ""
    short_vowel = False

    def attach(coda: str) -> bool:
        if not syllables:
            return False
        merged = with_coda(syllables[-1], coda)
        if not merged:
            return False
        syllables[-1] = merged
        return True

    for index, token in enumerate(tokens):
        if token[0] == "v":
            jamo = token[1]
            first = jamo[0]
            if glide == "y":
                first = Y_GLIDE.get(first, first)
            elif glide == "w":
                first = W_GLIDE.get(first, first)
            syllables.append(compose(onset or "ㅇ", first))
            for extra in jamo[1:]:
                syllables.append(compose("ㅇ", extra))
            onset = None
            glide = ""
            short_vowel = not token[2] and len(jamo) == 1
            continue

        name = token[1]
        if name in ("w", "y"):
            glide = name
            continue
        if _next_takes_vowel(tokens, index):
            # 모음 사이의 [l]은 ㄹㄹ: hello -> 헬로, not 헤로.
            if name == "l" and syllables and attach("ㄹ"):
                onset = "ㄹ"
            else:
                onset = _ONSET_OF.get(name, "ㅇ")
            # ``sh`` palatalises what follows: shop 숍, station 스테이션.
            if name == "sh":
                glide = "y"
            short_vowel = False
            continue

        if name == "r" or name == "h":
            short_vowel = False
            continue
        coda = _STOP_CODA.get(name) if short_vowel else None
        if coda and attach(coda):
            short_vowel = False
            continue
        coda = _CODA_OF.get(name)
        if coda:
            if attach(coda):
                short_vowel = False
                continue
            # The coda slot is taken. A preceding ㄹ resyllabifies (film ->
            # 필름); anything else gets a plain ㅡ syllable.
            parts = decompose(syllables[-1]) if syllables else ()
            if parts and parts[2] == "ㄹ" and coda in CODA_CAPABLE and coda != "ㄹ":
                syllables.append(compose("ㄹ", "ㅡ", coda))
            else:
                syllables.append(compose(_ONSET_OF.get(name, "ㅇ"), "ㅡ"))
            short_vowel = False
            continue
        support = _SUPPORT_OF.get(name)
        if support:
            syllables.append(support)
        short_vowel = False

    return "".join(syllable for syllable in syllables if syllable)


_CLEAN = re.compile(r"[^a-z]+")
_CACHE: Dict[str, str] = {}
_CACHE_LIMIT = 4096


def hangulize(word: str) -> str:
    """Return a Hangul reading for an arbitrary Latin word.

    Returns ``""`` for input with no letters, which callers treat as "drop it".
    """
    if not word:
        return ""
    key = word.casefold()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    letters = _CLEAN.sub("", key)
    if not letters:
        return ""
    result = _assemble(_phonemes(letters))
    if len(_CACHE) < _CACHE_LIMIT:
        _CACHE[key] = result
    return result


__all__ = ["hangulize"]

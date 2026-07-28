"""Numbers that Korean does not read the way the digits suggest.

Korean runs two counting systems. Sino-Korean (일, 이, 삼) covers minutes,
money, years and percentages, and a synthesiser reads bare digits that way by
default — so those are left alone. Native Korean (하나, 둘, 셋) is obligatory in
front of a specific set of counters, and *there* bare digits are read wrong:
``3시`` is 세 시, never 삼 시. Only the cases the default reading gets wrong are
rewritten here.

The counter must be followed by a boundary or a real particle. That is what
keeps ``3개월`` (삼 개월, a Sino counter that merely starts with 개) from being
mangled into 세 개월.
"""
from __future__ import annotations

import re
from typing import Dict, Final, Match

#: Attributive forms — 한 개, not 하나 개.
_ONES: Final[Dict[int, str]] = {
    1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯",
    6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉",
}
_TENS: Final[Dict[int, str]] = {
    1: "열", 2: "스물", 3: "서른", 4: "마흔", 5: "쉰",
    6: "예순", 7: "일흔", 8: "여든", 9: "아흔",
}


def native_number(value: int) -> str:
    """Return the attributive native-Korean numeral, or ``""`` outside 1-99."""
    if not 1 <= value <= 99:
        return ""
    tens, ones = divmod(value, 10)
    if not tens:
        return _ONES[ones]
    head = _TENS[tens]
    if not ones:
        # 스물 becomes 스무 with nothing after it: 스무 살.
        return "스무" if tens == 2 else head
    return head + _ONES[ones]


#: Counters that force native numerals. Deliberately conservative: 번, 분, 장
#: and 회 are omitted because each is Sino in at least one everyday sense
#: (버스 3번 is 삼 번), and guessing wrong is worse than leaving digits alone.
NATIVE_COUNTERS: Final[tuple] = (
    "시간", "번째", "켤레", "군데", "봉지", "상자", "그릇", "송이", "포기",
    "그루", "자루", "다발", "조각", "방울", "마리", "가지", "접시",
    "살", "시", "개", "명", "권", "대", "잔", "병", "벌", "채", "척",
    "판", "통", "쌍", "알", "줄", "컵", "짝", "톨",
)

#: Syllables that may legally follow a counter: the first syllable of a
#: particle, a copula or a suffix. Anything else means the counter was really
#: the start of a longer word — 개월, 개국, 통계 — and the digits stay Sino.
_FOLLOWERS: Final[str] = "|".join(
    (
        "이", "가", "은", "는", "을", "를", "도", "만", "와", "과", "의", "에",
        "로", "으", "나", "랑", "씩", "뿐", "째", "짜", "어", "정", "밖", "조",
        "마", "처", "같", "부", "까", "보", "요", "야", "입", "였", "밑", "당",
    )
)
_COUNTER_TOKEN: Final[str] = "|".join(NATIVE_COUNTERS)

_COUNTER = re.compile(
    rf"(?<![\d.,])(?P<number>\d{{1,2}})\s*(?P<counter>{_COUNTER_TOKEN})"
    rf"(?=$|[^가-힣0-9]|(?:{_FOLLOWERS}))"
)
#: ``3시 30분`` and ``14:05`` — the hour is native, the minute stays Sino.
_CLOCK = re.compile(r"(?<![\d.,])(?P<hour>\d{1,2})\s*시\s*(?P<minute>\d{1,2})\s*분")
_COLON_CLOCK = re.compile(
    r"(?<![\d:.])(?P<hour>[01]?\d|2[0-4]):(?P<minute>[0-5]\d)(?![\d:])"
)
#: ``2026-07-29`` is a date, not three numbers joined by minus signs.
_ISO_DATE = re.compile(
    r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)"
)
#: Korean says the denominator first: ``3/4`` is 4분의 3. Restricted to proper
#: fractions with a small denominator so ``7/29`` stays a date, not 29분의 7.
_FRACTION = re.compile(r"(?<![\d/.])(?P<top>\d)\s*/\s*(?P<bottom>\d|10)(?![\d/.])")
#: Phone numbers read as digit groups; the hyphens are not spoken.
_PHONE = re.compile(r"(?<!\d)(?P<a>0\d{1,2})-(?P<b>\d{3,4})-(?P<c>\d{4})(?!\d)")
#: Korean service numbers, written as two groups: 1588-1234.
_SERVICE_NUMBER = re.compile(r"(?<!\d)(?P<a>1[0-9]{3})-(?P<b>\d{4})(?!\d)")
#: ``6월``/``10월`` are 유월/시월, not 육월/십월.
_JUNE = re.compile(r"(?<![\d.,])6\s*월(?!\d)")
_OCTOBER = re.compile(r"(?<![\d.,])10\s*월(?!\d)")
#: English ordinals inside Korean text.
_ORDINAL = re.compile(r"(?<![A-Za-z0-9])(?P<number>\d{1,3})(?:st|nd|rd|th)(?![A-Za-z])")
_ORDINAL_WORDS: Final[Dict[str, str]] = {"1": "첫", "2": "두", "3": "세", "4": "네"}
#: ``1.5e9`` and ``2^10``. Korean names the base first and the exponent second:
#: 2의 10제곱, and 10의 마이너스 9제곱 when it is negative.
_SCIENTIFIC = re.compile(
    r"(?<![A-Za-z0-9.])(?P<base>\d+(?:\.\d+)?)[eE](?P<exp>[+-]?\d+)(?![A-Za-z0-9])"
)
_POWER = re.compile(
    r"(?<![A-Za-z])(?P<base>\d+(?:\.\d+)?)\s*\^\s*(?P<exp>[+-]?\d+)(?![A-Za-z0-9])"
)
_SUPERSCRIPT = re.compile(r"(?<=\d)(?P<exp>[²³])(?![A-Za-z0-9])")
#: ``3~5명`` is a range. It has to resolve before the counter rule below, or
#: the native numeral it produces no longer looks like a digit to the range.
_RANGE = re.compile(r"(?<=\d)\s*[~〜–—]\s*(?=\d)")
#: A minus sign in front of a value, which Korean reads aloud. ``10 - 4`` is
#: subtraction rather than a negative number, and is left for the symbol pass.
_MINUS = re.compile(r"(?<![\w가-힣])(?<!\d\s)[-−]\s*(?=\d)")


def _counter(match: Match) -> str:
    spoken = native_number(int(match.group("number")))
    if not spoken:
        return match.group(0)
    return f"{spoken} {match.group('counter')}"


def _clock(match: Match) -> str:
    spoken = native_number(int(match.group("hour")))
    if not spoken:
        return match.group(0)
    return f"{spoken} 시 {match.group('minute')}분"


def _exponent_words(exponent: str) -> str:
    sign = "마이너스 " if exponent.startswith("-") else ""
    return f"{sign}{exponent.lstrip('+-')}제곱"


def _scientific(match: Match) -> str:
    return f"{match.group('base')} 곱하기 10의 {_exponent_words(match.group('exp'))}"


def _power(match: Match) -> str:
    return f"{match.group('base')}의 {_exponent_words(match.group('exp'))}"


def _ordinal(match: Match) -> str:
    number = match.group("number")
    head = _ORDINAL_WORDS.get(number)
    return f"{head} 번째" if head else f"{number}번째"


def apply_numbers(text: str) -> str:
    """Rewrite the number forms a Korean voice would otherwise read wrong."""
    # Dates and phone numbers first: both are full of characters the rules
    # below would otherwise read as arithmetic.
    value = _ISO_DATE.sub(
        lambda m: (
            f"{m.group('year')}년 {int(m.group('month'))}월 "
            f"{int(m.group('day'))}일"
        ),
        text,
    )
    value = _PHONE.sub(lambda m: f"{m.group('a')} {m.group('b')} {m.group('c')}", value)
    value = _SERVICE_NUMBER.sub(lambda m: f"{m.group('a')} {m.group('b')}", value)
    value = _FRACTION.sub(
        lambda m: f"{m.group('bottom')}분의 {m.group('top')}", value
    )
    value = _SCIENTIFIC.sub(_scientific, value)
    value = _POWER.sub(_power, value)
    value = _SUPERSCRIPT.sub(lambda m: f"의 {'2' if m.group('exp') == '²' else '3'}제곱", value)
    value = _RANGE.sub("에서 ", value)
    value = _MINUS.sub("마이너스 ", value)
    value = _ORDINAL.sub(_ordinal, value)
    value = _JUNE.sub("유월", value)
    value = _OCTOBER.sub("시월", value)
    value = _COLON_CLOCK.sub(
        lambda m: f"{int(m.group('hour'))}시 {int(m.group('minute'))}분", value
    )
    value = _CLOCK.sub(_clock, value)
    value = _COUNTER.sub(_counter, value)
    return value


__all__ = ["NATIVE_COUNTERS", "apply_numbers", "native_number"]

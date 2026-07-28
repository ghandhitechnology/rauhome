"""Measurements, currency and temperature as Korean says them.

Korean does not simply swap the symbol for a word. The qualifier leads:
``25°C`` is 섭씨 25도, ``60 km/h`` is 시속 60킬로미터, ``37.5°N`` is 북위 37.5도,
and a temperature below zero is 영하 rather than a minus sign. Everything in
this module exists because a literal translation of the English reading would
sound wrong.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Dict, Final, Match

from rau.voice.korean.particles import SUFFIX as _PARTICLE_SUFFIX
from rau.voice.korean.particles import agree

#: Unit symbol -> Korean reading. Case is meaningful exactly as it is in the
#: English normalizer: ``MB`` is megabytes, ``Mb`` megabits, ``K`` kelvin.
UNITS: Final[Dict[str, str]] = {
    # length
    "pm": "피코미터", "nm": "나노미터", "µm": "마이크로미터", "μm": "마이크로미터",
    "um": "마이크로미터", "mm": "밀리미터", "cm": "센티미터", "dm": "데시미터",
    "m": "미터", "km": "킬로미터", "in": "인치", "ft": "피트", "yd": "야드",
    "mi": "마일", "ly": "광년", "au": "천문단위",
    # area and volume
    "ha": "헥타르", "ac": "에이커",
    "µL": "마이크로리터", "μL": "마이크로리터", "uL": "마이크로리터",
    "mL": "밀리리터", "ml": "밀리리터", "cL": "센티리터", "dL": "데시리터",
    "L": "리터", "l": "리터", "cc": "시시", "tsp": "티스푼", "tbsp": "테이블스푼",
    "gal": "갤런", "pt": "파인트", "qt": "쿼트",
    # mass
    "ng": "나노그램", "µg": "마이크로그램", "μg": "마이크로그램", "ug": "마이크로그램",
    "mg": "밀리그램", "g": "그램", "kg": "킬로그램", "t": "톤", "oz": "온스",
    "lb": "파운드", "lbs": "파운드", "ct": "캐럿",
    # time and frequency
    "ns": "나노초", "µs": "마이크로초", "μs": "마이크로초", "us": "마이크로초",
    "ms": "밀리초", "s": "초", "sec": "초", "secs": "초", "min": "분",
    "mins": "분", "h": "시간", "hr": "시간", "hrs": "시간", "d": "일",
    "wk": "주", "wks": "주", "yr": "년", "yrs": "년",
    "Hz": "헤르츠", "kHz": "킬로헤르츠", "MHz": "메가헤르츠", "GHz": "기가헤르츠",
    "THz": "테라헤르츠", "rpm": "아르피엠", "bpm": "비피엠", "fps": "프레임",
    "K": "켈빈",
    # electricity, energy, force, pressure, light, sound
    "µA": "마이크로암페어", "μA": "마이크로암페어", "mA": "밀리암페어", "A": "암페어",
    "mV": "밀리볼트", "V": "볼트", "kV": "킬로볼트", "mW": "밀리와트", "W": "와트",
    "kW": "킬로와트", "MW": "메가와트", "GW": "기가와트", "Wh": "와트시",
    "kWh": "킬로와트시", "MWh": "메가와트시", "mAh": "밀리암페어시", "Ah": "암페어시",
    "VA": "볼트암페어", "kVA": "킬로볼트암페어", "J": "줄", "kJ": "킬로줄",
    "MJ": "메가줄", "cal": "칼로리", "kcal": "킬로칼로리", "N": "뉴턴",
    "Pa": "파스칼", "hPa": "헥토파스칼", "kPa": "킬로파스칼", "MPa": "메가파스칼",
    "bar": "바", "mbar": "밀리바", "atm": "기압", "psi": "피에스아이",
    "mmHg": "밀리미터 에이치지", "dB": "데시벨", "lm": "루멘", "lx": "럭스",
    "Ω": "옴", "kΩ": "킬로옴", "MΩ": "메가옴", "F": "패럿", "µF": "마이크로패럿",
    "μF": "마이크로패럿", "nF": "나노패럿", "pF": "피코패럿",
    # chemistry and medicine
    "mol": "몰", "mmol": "밀리몰", "µmol": "마이크로몰", "μmol": "마이크로몰",
    "M": "몰", "mM": "밀리몰", "IU": "국제단위", "ppm": "피피엠", "ppb": "피피비",
    # digital storage and transfer
    "b": "비트", "B": "바이트", "Kb": "킬로비트", "KB": "킬로바이트",
    "Mb": "메가비트", "MB": "메가바이트", "Gb": "기가비트", "GB": "기가바이트",
    "Tb": "테라비트", "TB": "테라바이트", "PB": "페타바이트",
    "KiB": "키비바이트", "MiB": "메비바이트", "GiB": "기비바이트", "TiB": "테비바이트",
    "kbps": "킬로비피에스", "Mbps": "메가비피에스", "Gbps": "기가비피에스",
    "dpi": "디피아이", "ppi": "피피아이", "px": "픽셀", "MP": "메가픽셀",
    # navigation and angles
    "rad": "라디안", "sr": "스테라디안", "kt": "노트", "kn": "노트",
}

#: Symbols safe to read as a unit even with no number in front of them
#: (``GB 단위로``). Deliberately excludes every symbol that is also an ordinary
#: word or initialism — ``in``, ``m``, ``s``, ``t``, ``bar``, ``min``, ``cal``.
BARE_UNITS: Final[Dict[str, str]] = {
    symbol: UNITS[symbol]
    for symbol in (
        "km", "cm", "mm", "nm", "kg", "mg", "ml", "mL", "dL", "kHz", "MHz",
        "GHz", "THz", "Hz", "kWh", "MWh", "kW", "MW", "GW", "mAh", "kbps",
        "Mbps", "Gbps", "KB", "MB", "GB", "TB", "PB", "KiB", "MiB", "GiB",
        "TiB", "dpi", "ppi", "px", "rpm", "bpm", "fps", "psi", "ppm", "ppb",
        "kPa", "hPa", "MPa", "mmHg", "kcal", "km²", "kV", "mAh",
    )
    if symbol in UNITS
}

#: Speeds Korean states as 시속/분속/초속 in front of the number.
_SPEED_PREFIX: Final[Dict[str, str]] = {
    "h": "시속", "hr": "시속", "hrs": "시속",
    "min": "분속", "mins": "분속",
    "s": "초속", "sec": "초속", "secs": "초속",
}
_LENGTH_UNITS: Final[frozenset] = frozenset(
    {"m", "km", "cm", "mm", "mi", "ft", "yd", "nm", "µm", "μm", "um", "in"}
)

#: Whole-symbol speeds that never appear as a fraction.
_SPEED_UNITS: Final[Dict[str, str]] = {
    "mph": ("시속", "마일"),
    "kph": ("시속", "킬로미터"),
    "kmh": ("시속", "킬로미터"),
    "kmph": ("시속", "킬로미터"),
}

CURRENCIES: Final[Dict[str, str]] = {
    "$": "달러", "US$": "달러", "€": "유로", "£": "파운드", "¥": "엔",
    "₩": "원", "₹": "루피", "₽": "루블", "¢": "센트", "₺": "리라",
    "₫": "동", "฿": "바트", "₴": "흐리브냐", "₪": "셰켈",
}

#: Latitude and longitude, which Korean states as a leading 북위/남위/동경/서경.
_BEARINGS: Final[Dict[str, str]] = {
    "N": "북위", "S": "남위", "E": "동경", "W": "서경",
}

NUMBER: Final[str] = r"[+−-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_UNIT_TOKEN: Final[str] = "|".join(
    re.escape(name) for name in sorted(UNITS, key=len, reverse=True)
)
_EXPONENT: Final[str] = r"(?:\s*(?:\^?\s*[23]|[²³]))?"
#: ASCII-only boundaries. ``\w`` would match Hangul, so ``25km를`` would fail to
#: match at all — the exact case this module exists for.
_BEFORE: Final[str] = r"(?<![A-Za-z0-9.])"
_AFTER: Final[str] = r"(?![A-Za-z0-9])"

_COMPOUND = re.compile(
    rf"{_BEFORE}(?P<number>{NUMBER})\s*"
    rf"(?P<numerator>{_UNIT_TOKEN})(?P<numexp>{_EXPONENT})\s*/\s*"
    rf"(?P<denominator>{_UNIT_TOKEN})(?P<denexp>{_EXPONENT}){_AFTER}" + _PARTICLE_SUFFIX
)
_MEASUREMENT = re.compile(
    rf"{_BEFORE}(?P<number>{NUMBER})\s*"
    rf"(?P<unit>{_UNIT_TOKEN})(?P<exp>{_EXPONENT})(?![A-Za-z0-9/])" + _PARTICLE_SUFFIX
)
_SPEED = re.compile(
    rf"{_BEFORE}(?P<number>{NUMBER})\s*"
    rf"(?P<unit>{'|'.join(_SPEED_UNITS)}){_AFTER}" + _PARTICLE_SUFFIX
)
_CURRENCY_SYMBOLS = "".join(re.escape(symbol) for symbol in CURRENCIES if len(symbol) == 1)
_SCALED_CURRENCY = re.compile(
    rf"(?<![A-Za-z0-9])(?P<symbol>[{_CURRENCY_SYMBOLS}])\s*"
    rf"(?P<number>{NUMBER})\s*(?P<scale>[kKmMbB]|bn|BN|Bn)(?![A-Za-z0-9])"
)
_CURRENCY = re.compile(
    rf"(?<![A-Za-z0-9])(?P<symbol>[{_CURRENCY_SYMBOLS}])\s*(?P<number>{NUMBER})"
    rf"(?![A-Za-z0-9])"
)
_PERCENT_POINT = re.compile(rf"(?P<number>{NUMBER})\s*%\s*[pP](?![A-Za-z0-9])")
_PERCENT = re.compile(rf"(?P<number>{NUMBER})\s*%")
_CELSIUS = re.compile(
    rf"(?P<number>{NUMBER})\s*(?:°\s*[Cc](?![A-Za-z])|℃|도\s*[Cc](?![A-Za-z]))"
)
_FAHRENHEIT = re.compile(rf"(?P<number>{NUMBER})\s*(?:°\s*[Ff](?![A-Za-z])|℉)")
_BEARING = re.compile(rf"(?P<number>{NUMBER})\s*°\s*(?P<bearing>[NSEW])(?![A-Za-z])")
_DEGREE = re.compile(rf"(?P<number>{NUMBER})\s*°(?!\s*[CF])")

_SCALES: Final[Dict[str, int]] = {"k": 1000, "m": 1000000, "b": 1000000000, "bn": 1000000000}


def _exponent(compact: str, reading: str) -> str:
    compact = re.sub(r"[\s^]", "", compact or "")
    if compact in {"2", "²"}:
        return f"제곱{reading}"
    if compact in {"3", "³"}:
        return f"세제곱{reading}"
    return reading


def _denominator(compact: str, reading: str) -> str:
    compact = re.sub(r"[\s^]", "", compact or "")
    if compact in {"2", "²"}:
        return f"{reading} 제곱당"
    if compact in {"3", "³"}:
        return f"{reading} 세제곱당"
    return f"{reading}당"


def _sign(number: str) -> tuple:
    """Split a leading minus off, since Korean says 영하/마이너스 before the value."""
    if number[:1] in "-−":
        return True, number[1:]
    if number[:1] == "+":
        return False, number[1:]
    return False, number


def _compound(match: Match) -> str:
    number = match.group("number")
    numerator = match.group("numerator")
    denominator = match.group("denominator")
    numexp = match.group("numexp") or ""
    denexp = match.group("denexp") or ""
    if (
        not numexp.strip()
        and not denexp.strip()
        and numerator in _LENGTH_UNITS
        and denominator in _SPEED_PREFIX
    ):
        negative, digits = _sign(number)
        prefix = "마이너스 " if negative else ""
        spoken = f"{_SPEED_PREFIX[denominator]} {prefix}{digits}{UNITS[numerator]}"
        return agree(spoken, match.group("particle") or "")
    head = _denominator(denexp, UNITS[denominator])
    tail = _exponent(numexp, UNITS[numerator])
    return agree(f"{head} {number}{tail}", match.group("particle") or "")


def _measurement(match: Match) -> str:
    spoken = (
        f"{match.group('number')}"
        f"{_exponent(match.group('exp'), UNITS[match.group('unit')])}"
    )
    return agree(spoken, match.group("particle") or "")


def _speed(match: Match) -> str:
    prefix, unit = _SPEED_UNITS[match.group("unit")]
    spoken = f"{prefix} {match.group('number')}{unit}"
    return agree(spoken, match.group("particle") or "")


def _scaled_currency(match: Match) -> str:
    scale = _SCALES[match.group("scale").lower()]
    unit = CURRENCIES[match.group("symbol")]
    raw = match.group("number").replace(",", "").replace("−", "-")
    try:
        value = Decimal(raw) * scale
    except InvalidOperation:
        return match.group(0)
    if value != value.to_integral_value():
        return f"{match.group('number')} {unit}"
    return f"{int(value)} {unit}"


def _currency(match: Match) -> str:
    return f"{match.group('number')} {CURRENCIES[match.group('symbol')]}"


def _celsius(match: Match) -> str:
    negative, digits = _sign(match.group("number"))
    return f"섭씨 {'영하 ' if negative else ''}{digits}도"


def _fahrenheit(match: Match) -> str:
    negative, digits = _sign(match.group("number"))
    return f"화씨 {'영하 ' if negative else ''}{digits}도"


def _bearing(match: Match) -> str:
    return f"{_BEARINGS[match.group('bearing')]} {match.group('number')}도"


def apply_units(text: str) -> str:
    """Rewrite measurements, currency and temperature into Korean readings."""
    value = _SCALED_CURRENCY.sub(_scaled_currency, text)
    value = _CELSIUS.sub(_celsius, value)
    value = _FAHRENHEIT.sub(_fahrenheit, value)
    value = _BEARING.sub(_bearing, value)
    value = _DEGREE.sub(lambda m: f"{m.group('number')}도", value)
    value = _CURRENCY.sub(_currency, value)
    value = _PERCENT_POINT.sub(lambda m: f"{m.group('number')}퍼센트포인트", value)
    value = _PERCENT.sub(lambda m: f"{m.group('number')}퍼센트", value)
    value = _SPEED.sub(_speed, value)
    value = _COMPOUND.sub(_compound, value)
    value = _MEASUREMENT.sub(_measurement, value)
    return value


__all__ = ["BARE_UNITS", "CURRENCIES", "NUMBER", "UNITS", "apply_units"]

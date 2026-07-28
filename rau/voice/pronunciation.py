"""Context-aware text normalization for speech synthesis.

The chat transcript and captions keep the model's original text. Only the copy
sent to TTS passes through this module, so useful written notation such as
``25 km/s`` remains compact on screen while the voice says "25 kilometers per
second".

Rules intentionally require numeric or formula context. Blind replacements such
as ``m -> meters`` corrupt ordinary words, and expanding ``He`` as helium would
turn a very common English pronoun into a chemistry lesson.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Match, Tuple


@dataclass(frozen=True)
class _Unit:
    singular: str
    plural: str


def _unit(singular: str, plural: str = "") -> _Unit:
    return _Unit(singular, plural or f"{singular}s")


# Case is meaningful: MB is megabytes, Mb is megabits, mB is not silently
# guessed, and K is kelvin while k is not a unit.
_UNITS: Dict[str, _Unit] = {
    # length
    "pm": _unit("picometer"),
    "nm": _unit("nanometer"),
    "µm": _unit("micrometer"),
    "μm": _unit("micrometer"),
    "um": _unit("micrometer"),
    "mm": _unit("millimeter"),
    "cm": _unit("centimeter"),
    "dm": _unit("decimeter"),
    "m": _unit("meter"),
    "km": _unit("kilometer"),
    "in": _unit("inch", "inches"),
    "ft": _unit("foot", "feet"),
    "yd": _unit("yard"),
    "mi": _unit("mile"),
    # volume
    "µL": _unit("microliter"),
    "μL": _unit("microliter"),
    "uL": _unit("microliter"),
    "mL": _unit("milliliter"),
    "ml": _unit("milliliter"),
    "cL": _unit("centiliter"),
    "dL": _unit("deciliter"),
    "L": _unit("liter"),
    "l": _unit("liter"),
    "cc": _unit("cubic centimeter"),
    "tsp": _unit("teaspoon"),
    "tbsp": _unit("tablespoon"),
    "fl oz": _unit("fluid ounce"),
    "gal": _unit("gallon"),
    "pt": _unit("pint"),
    "qt": _unit("quart"),
    # mass
    "ng": _unit("nanogram"),
    "µg": _unit("microgram"),
    "μg": _unit("microgram"),
    "ug": _unit("microgram"),
    "mg": _unit("milligram"),
    "g": _unit("gram"),
    "kg": _unit("kilogram"),
    "t": _unit("metric ton"),
    "oz": _unit("ounce"),
    "lb": _unit("pound"),
    "lbs": _unit("pound"),
    "st": _unit("stone", "stone"),
    # time and frequency
    "ns": _unit("nanosecond"),
    "µs": _unit("microsecond"),
    "μs": _unit("microsecond"),
    "us": _unit("microsecond"),
    "ms": _unit("millisecond"),
    "s": _unit("second"),
    "sec": _unit("second"),
    "secs": _unit("second"),
    "min": _unit("minute"),
    "mins": _unit("minute"),
    "h": _unit("hour"),
    "hr": _unit("hour"),
    "hrs": _unit("hour"),
    "d": _unit("day"),
    "wk": _unit("week"),
    "wks": _unit("week"),
    "Hz": _unit("hertz", "hertz"),
    "kHz": _unit("kilohertz", "kilohertz"),
    "MHz": _unit("megahertz", "megahertz"),
    "GHz": _unit("gigahertz", "gigahertz"),
    "THz": _unit("terahertz", "terahertz"),
    "K": _unit("kelvin", "kelvin"),
    "rpm": _unit("revolution per minute", "revolutions per minute"),
    "bpm": _unit("beat per minute", "beats per minute"),
    "fps": _unit("frame per second", "frames per second"),
    "mph": _unit("mile per hour", "miles per hour"),
    "kph": _unit("kilometer per hour", "kilometers per hour"),
    "kmph": _unit("kilometer per hour", "kilometers per hour"),
    # electricity, energy, force, pressure, light, sound
    "µA": _unit("microamp"),
    "μA": _unit("microamp"),
    "mA": _unit("milliamp"),
    "A": _unit("amp"),
    "mV": _unit("millivolt"),
    "V": _unit("volt"),
    "kV": _unit("kilovolt"),
    "mW": _unit("milliwatt"),
    "W": _unit("watt"),
    "kW": _unit("kilowatt"),
    "MW": _unit("megawatt"),
    "GW": _unit("gigawatt"),
    "Wh": _unit("watt hour"),
    "kWh": _unit("kilowatt hour"),
    "MWh": _unit("megawatt hour"),
    "mAh": _unit("milliamp hour"),
    "Ah": _unit("amp hour"),
    "VA": _unit("volt ampere"),
    "kVA": _unit("kilovolt ampere"),
    "J": _unit("joule"),
    "kJ": _unit("kilojoule"),
    "MJ": _unit("megajoule"),
    "cal": _unit("calorie"),
    "kcal": _unit("kilocalorie"),
    "N": _unit("newton"),
    "Pa": _unit("pascal"),
    "hPa": _unit("hectopascal"),
    "kPa": _unit("kilopascal"),
    "MPa": _unit("megapascal"),
    "bar": _unit("bar", "bar"),
    "mbar": _unit("millibar"),
    "psi": _unit("pound per square inch", "pounds per square inch"),
    "mmHg": _unit("millimeter of mercury", "millimeters of mercury"),
    "dB": _unit("decibel"),
    "lm": _unit("lumen"),
    "lx": _unit("lux", "lux"),
    "Ω": _unit("ohm"),
    "kΩ": _unit("kiloohm"),
    "MΩ": _unit("megaohm"),
    "F": _unit("farad"),
    "µF": _unit("microfarad"),
    "μF": _unit("microfarad"),
    "nF": _unit("nanofarad"),
    "pF": _unit("picofarad"),
    # chemistry and medicine
    "mol": _unit("mole"),
    "mmol": _unit("millimole"),
    "µmol": _unit("micromole"),
    "μmol": _unit("micromole"),
    "M": _unit("molar"),
    "mM": _unit("millimolar"),
    "IU": _unit("international unit"),
    "ppm": _unit("part per million", "parts per million"),
    "ppb": _unit("part per billion", "parts per billion"),
    # digital storage and transfer
    "b": _unit("bit"),
    "B": _unit("byte"),
    "Kb": _unit("kilobit"),
    "KB": _unit("kilobyte"),
    "Mb": _unit("megabit"),
    "MB": _unit("megabyte"),
    "Gb": _unit("gigabit"),
    "GB": _unit("gigabyte"),
    "Tb": _unit("terabit"),
    "TB": _unit("terabyte"),
    "KiB": _unit("kibibyte"),
    "MiB": _unit("mebibyte"),
    "GiB": _unit("gibibyte"),
    "TiB": _unit("tebibyte"),
    "kbps": _unit("kilobit per second", "kilobits per second"),
    "Mbps": _unit("megabit per second", "megabits per second"),
    "Gbps": _unit("gigabit per second", "gigabits per second"),
    "dpi": _unit("dot per inch", "dots per inch"),
    "ppi": _unit("pixel per inch", "pixels per inch"),
    "px": _unit("pixel"),
    "MP": _unit("megapixel"),
    # navigation and angles
    "rad": _unit("radian"),
    "sr": _unit("steradian"),
    "kt": _unit("knot"),
    "kn": _unit("knot"),
}

_NUMBER = (
    r"[+−-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
)
_UNIT_TOKEN = "|".join(
    re.escape(name) for name in sorted(_UNITS, key=len, reverse=True)
)
_EXPONENT = r"(?:\s*(?:\^?\s*[23]|[²³]))?"
_COMPOUND = re.compile(
    rf"(?<![\w.])(?P<number>{_NUMBER})\s*"
    rf"(?P<numerator>{_UNIT_TOKEN})(?P<numexp>{_EXPONENT})\s*/\s*"
    rf"(?P<denominator>{_UNIT_TOKEN})(?P<denexp>{_EXPONENT})(?![\w])"
)
_MEASUREMENT = re.compile(
    rf"(?<![\w.])(?P<number>{_NUMBER})\s*"
    rf"(?P<unit>{_UNIT_TOKEN})(?P<exp>{_EXPONENT})(?![\w/])"
)

_PROTECTED = re.compile(
    r"```[\s\S]*?```|`[^`\n]+`|https?://[^\s<>()]+|www\.[^\s<>()]+|"
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"
)


def _is_one(number: str) -> bool:
    try:
        return abs(
            Decimal(number.replace(",", "").replace("−", "-"))
        ) == Decimal(1)
    except InvalidOperation:
        return False


def _power(
    exp: str, unit: _Unit, singular: bool, *, denominator: bool = False
) -> str:
    compact = re.sub(r"[\s^]", "", exp or "")
    name = unit.singular if singular else unit.plural
    if compact in {"2", "²"}:
        return f"{name} squared" if denominator else f"square {name}"
    if compact in {"3", "³"}:
        return f"{name} cubed" if denominator else f"cubic {name}"
    return name


def _measurement(match: Match[str]) -> str:
    number = match.group("number")
    unit = _UNITS[match.group("unit")]
    return f"{number} {_power(match.group('exp'), unit, _is_one(number))}"


def _compound(match: Match[str]) -> str:
    number = match.group("number")
    numerator = _power(
        match.group("numexp"),
        _UNITS[match.group("numerator")],
        _is_one(number),
    )
    # Denominators are grammatically singular regardless of the numerator.
    denominator = _power(
        match.group("denexp"),
        _UNITS[match.group("denominator")],
        True,
        denominator=True,
    )
    return f"{number} {numerator} per {denominator}"


_CURRENCY: Dict[str, Tuple[str, str]] = {
    "$": ("dollar", "dollars"),
    "€": ("euro", "euros"),
    "£": ("pound sterling", "pounds sterling"),
    "¥": ("yen", "yen"),
    "₩": ("won", "won"),
    "₹": ("rupee", "rupees"),
    "₽": ("ruble", "rubles"),
    "¢": ("cent", "cents"),
}
_CURRENCY_RE = re.compile(
    rf"(?<!\w)(?P<symbol>[{''.join(re.escape(x) for x in _CURRENCY)}])"
    rf"\s*(?P<number>{_NUMBER})(?!\w)"
)


def _currency(match: Match[str]) -> str:
    number = match.group("number")
    singular, plural = _CURRENCY[match.group("symbol")]
    return f"{number} {singular if _is_one(number) else plural}"


# All element names are present so common formulas and less-common scientific
# text use the same parser. Element symbols are never replaced in normal prose;
# only formula-shaped tokens (H2O, NaCl, O₂) or an explicit ``X(name)`` label
# are expanded.
_ELEMENTS: Dict[str, str] = {
    "H": "hydrogen", "He": "helium", "Li": "lithium", "Be": "beryllium",
    "B": "boron", "C": "carbon", "N": "nitrogen", "O": "oxygen", "F": "fluorine",
    "Ne": "neon", "Na": "sodium", "Mg": "magnesium", "Al": "aluminum",
    "Si": "silicon", "P": "phosphorus", "S": "sulfur", "Cl": "chlorine",
    "Ar": "argon", "K": "potassium", "Ca": "calcium", "Sc": "scandium",
    "Ti": "titanium", "V": "vanadium", "Cr": "chromium", "Mn": "manganese",
    "Fe": "iron", "Co": "cobalt", "Ni": "nickel", "Cu": "copper", "Zn": "zinc",
    "Ga": "gallium", "Ge": "germanium", "As": "arsenic", "Se": "selenium",
    "Br": "bromine", "Kr": "krypton", "Rb": "rubidium", "Sr": "strontium",
    "Y": "yttrium", "Zr": "zirconium", "Nb": "niobium", "Mo": "molybdenum",
    "Tc": "technetium", "Ru": "ruthenium", "Rh": "rhodium", "Pd": "palladium",
    "Ag": "silver", "Cd": "cadmium", "In": "indium", "Sn": "tin",
    "Sb": "antimony", "Te": "tellurium", "I": "iodine", "Xe": "xenon",
    "Cs": "cesium", "Ba": "barium", "La": "lanthanum", "Ce": "cerium",
    "Pr": "praseodymium", "Nd": "neodymium", "Pm": "promethium",
    "Sm": "samarium", "Eu": "europium", "Gd": "gadolinium", "Tb": "terbium",
    "Dy": "dysprosium", "Ho": "holmium", "Er": "erbium", "Tm": "thulium",
    "Yb": "ytterbium", "Lu": "lutetium", "Hf": "hafnium", "Ta": "tantalum",
    "W": "tungsten", "Re": "rhenium", "Os": "osmium", "Ir": "iridium",
    "Pt": "platinum", "Au": "gold", "Hg": "mercury", "Tl": "thallium",
    "Pb": "lead", "Bi": "bismuth", "Po": "polonium", "At": "astatine",
    "Rn": "radon", "Fr": "francium", "Ra": "radium", "Ac": "actinium",
    "Th": "thorium", "Pa": "protactinium", "U": "uranium", "Np": "neptunium",
    "Pu": "plutonium", "Am": "americium", "Cm": "curium", "Bk": "berkelium",
    "Cf": "californium", "Es": "einsteinium", "Fm": "fermium",
    "Md": "mendelevium", "No": "nobelium", "Lr": "lawrencium",
    "Rf": "rutherfordium", "Db": "dubnium", "Sg": "seaborgium",
    "Bh": "bohrium", "Hs": "hassium", "Mt": "meitnerium",
    "Ds": "darmstadtium", "Rg": "roentgenium", "Cn": "copernicium",
    "Nh": "nihonium", "Fl": "flerovium", "Mc": "moscovium",
    "Lv": "livermorium", "Ts": "tennessine", "Og": "oganesson",
}
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)([0-9₀₁₂₃₄₅₆₇₈₉]*)")
_FORMULA = re.compile(
    r"(?<![A-Za-z])(?:[A-Z][a-z]?[0-9₀₁₂₃₄₅₆₇₈₉]*){2,}(?![A-Za-z])|"
    r"(?<![A-Za-z])(?:[A-Z][a-z]?)[0-9₀₁₂₃₄₅₆₇₈₉]+(?![A-Za-z])"
)
_EXPLICIT_ELEMENT = re.compile(
    r"\b(?P<symbol>[A-Z][a-z]?)\s*\(\s*(?P<label>[A-Za-z][A-Za-z -]{2,30})\s*\)"
)
_COMMON_FORMULAS = {
    "H2": "hydrogen",
    "N2": "nitrogen",
    "O2": "oxygen",
    "O3": "ozone",
    "H2O": "water",
    "H2O2": "hydrogen peroxide",
    "CO": "carbon monoxide",
    "CO2": "carbon dioxide",
    "CH4": "methane",
    "NH3": "ammonia",
    "NaCl": "sodium chloride",
    "HCl": "hydrogen chloride",
    "H2SO4": "sulfuric acid",
    "HNO3": "nitric acid",
    "NaOH": "sodium hydroxide",
    "CaCO3": "calcium carbonate",
}


def _formula(match: Match[str]) -> str:
    source = match.group(0)
    common = _COMMON_FORMULAS.get(source.translate(_SUBSCRIPT))
    if common:
        return common
    pieces = _FORMULA_TOKEN.findall(source)
    if not pieces or "".join(symbol + count for symbol, count in pieces) != source:
        # The equality above uses unicode subscripts unchanged; compare a
        # translated form as well before rejecting it.
        translated = source.translate(_SUBSCRIPT)
        pieces = _FORMULA_TOKEN.findall(translated)
        if "".join(symbol + count for symbol, count in pieces) != translated:
            return source
    if any(symbol not in _ELEMENTS for symbol, _count in pieces):
        return source
    spoken = []
    for symbol, count in pieces:
        spoken.append(_ELEMENTS[symbol])
        if count:
            spoken.append(count.translate(_SUBSCRIPT))
    return " ".join(spoken)


def _explicit_element(match: Match[str]) -> str:
    # The written label is the author's intended reading. This intentionally
    # handles inputs such as "He (helium)" and even a mislabeled "H(helium)"
    # without inventing a different spoken phrase.
    return match.group("label").strip()


_ABBREVIATIONS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\be\.g\.(?=\s|$)", re.I), "for example"),
    (re.compile(r"\bi\.e\.(?=\s|$)", re.I), "that is"),
    (re.compile(r"\betc\.(?=\s|$)", re.I), "et cetera"),
    (re.compile(r"\bvs\.?(?=\s|$)", re.I), "versus"),
    (re.compile(r"\bapprox\.(?=\s|$)", re.I), "approximately"),
    (re.compile(r"\best\.(?=\s|$)", re.I), "estimated"),
    (re.compile(r"\bETA\b"), "estimated time of arrival"),
    (re.compile(r"\bNo\.\s*(?=\d)", re.I), "number "),
)


def _protect(text: str) -> Tuple[str, Callable[[str], str]]:
    values: Dict[str, str] = {}

    def stash(match: Match[str]) -> str:
        raw = match.group(0)
        if raw.startswith("```"):
            raw = raw[3:-3]
        elif raw.startswith("`"):
            raw = raw[1:-1]
        marker = f"\ue000{chr(0xE100 + len(values))}\ue001"
        values[marker] = raw
        return marker

    protected = _PROTECTED.sub(stash, text)

    def restore(value: str) -> str:
        for marker, raw in values.items():
            value = value.replace(marker, raw)
        return value

    return protected, restore


def normalize_for_tts(text: str) -> str:
    """Return a speakable copy of everyday written notation."""
    if not isinstance(text, str) or not text:
        return text
    value, restore = _protect(text)

    # Compact financial notation must be claimed before ``5m`` can look like
    # a five-meter measurement.
    value = re.sub(
        rf"(?<!\w)(?P<symbol>[$€£¥₩₹₽])\s*(?P<number>{_NUMBER})\s*"
        r"(?P<scale>k|m|bn|b)(?!\w)",
        lambda m: (
            f"{m.group('number')} "
            f"{'thousand' if m.group('scale').lower() == 'k' else 'million' if m.group('scale').lower() == 'm' else 'billion'} "
            f"{_CURRENCY[m.group('symbol')][1]}"
        ),
        value,
        flags=re.I,
    )

    # Common alternate rate notation: 20 m·s⁻¹ / 20 m s^-1.
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT_TOKEN})"
        rf"\s*[· ]\s*(?P<den>{_UNIT_TOKEN})\s*(?:\^?\s*[−-]?1|⁻¹)(?!\w)",
        lambda m: (
            f"{m.group('number')} {m.group('unit')}/{m.group('den')}"
        ),
        value,
    )

    # Feet/inches height notation must run before quote punctuation handling.
    value = re.sub(
        rf"(?<!\w)(?P<feet>\d+)\s*['′]\s*(?P<inches>\d+)\s*(?:[\"″])",
        lambda m: f"{m.group('feet')} feet {m.group('inches')} inches",
        value,
    )

    # Temperatures before plain degrees and before C/F are seen as units.
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*(?:°\s*C|℃|\bdegrees?\s+C\b)",
        lambda m: f"{m.group('number')} degrees Celsius",
        value,
        flags=re.I,
    )
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*(?:°\s*F|℉|\bdegrees?\s+F\b)",
        lambda m: f"{m.group('number')} degrees Fahrenheit",
        value,
        flags=re.I,
    )
    directions = {"N": "north", "S": "south", "E": "east", "W": "west"}
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*°\s*(?P<direction>[NSEW])\b",
        lambda m: (
            f"{m.group('number')} degrees "
            f"{directions[m.group('direction').upper()]}"
        ),
        value,
        flags=re.I,
    )
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*°(?!\s*[CF]\b)",
        lambda m: f"{m.group('number')} degrees",
        value,
    )

    value = _CURRENCY_RE.sub(_currency, value)
    value = re.sub(
        rf"(?P<number>{_NUMBER})\s*%",
        lambda m: f"{m.group('number')} percent",
        value,
    )

    # Scientific notation and powers.
    value = re.sub(
        rf"(?<![\w.])(?P<base>{_NUMBER})[eE](?P<exp>[+-]?\d+)(?!\w)",
        lambda m: (
            f"{m.group('base')} times ten to the "
            f"{'minus ' if m.group('exp').startswith('-') else ''}"
            f"{m.group('exp').lstrip('+-')}"
        ),
        value,
    )
    value = re.sub(
        r"(?<!\w)(?P<base>\d+(?:\.\d+)?)\s*\^\s*(?P<exp>[+-]?\d+)",
        lambda m: (
            f"{m.group('base')} to the "
            f"{'minus ' if m.group('exp').startswith('-') else ''}"
            f"{m.group('exp').lstrip('+-')} power"
        ),
        value,
    )

    value = _COMPOUND.sub(_compound, value)
    value = _MEASUREMENT.sub(_measurement, value)

    # Chemistry runs after measurements so 2 H is allowed to mean two henrys,
    # while H2 and H2O retain formula semantics.
    value = _EXPLICIT_ELEMENT.sub(_explicit_element, value)
    value = _FORMULA.sub(_formula, value)

    for pattern, replacement in _ABBREVIATIONS:
        value = pattern.sub(replacement, value)

    # Fractions, comparisons, dimensions, ranges, and high-frequency symbols.
    fractions = {
        "½": "one half", "⅓": "one third", "⅔": "two thirds",
        "¼": "one quarter", "¾": "three quarters", "⅕": "one fifth",
        "⅖": "two fifths", "⅗": "three fifths", "⅘": "four fifths",
        "⅛": "one eighth", "⅜": "three eighths", "⅝": "five eighths",
        "⅞": "seven eighths",
    }
    for glyph, spoken in fractions.items():
        value = value.replace(glyph, f" {spoken} ")
    value = re.sub(r"(?<=\d)\s*[x×]\s*(?=\d)", " by ", value)
    value = re.sub(r"(?<=\d)\s*[x×]\b", " times", value)
    value = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", " to ", value)
    value = value.replace("±", " plus or minus ")
    value = value.replace("≤", " less than or equal to ")
    value = value.replace("≥", " greater than or equal to ")
    value = value.replace("≠", " not equal to ")
    value = value.replace("≈", " approximately ")
    value = value.replace("→", " to ")
    value = value.replace("←", " from ")
    value = re.sub(r"(?<!\w)~\s*(?=\d)", "about ", value)
    value = re.sub(r"(?<!\w)#\s*(?=\d)", "number ", value)
    value = re.sub(r"\s*&\s*", " and ", value)
    value = re.sub(r"\s+@\s+", " at ", value)

    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r" *\n *", "\n", value).strip()
    return restore(value)


__all__ = ["normalize_for_tts"]

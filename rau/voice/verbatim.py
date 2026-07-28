"""Spans that text normalization must hand back untouched.

Code, URLs and email addresses mean exactly what they say. Expanding ``m`` to
"meters" inside a shell command, or transliterating a domain name, changes what
the listener is being told. Both the English and the Korean normalizers mask
these spans first and restore them last.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Match, Tuple

_PROTECTED = re.compile(
    r"```[\s\S]*?```|`[^`\n]+`|https?://[^\s<>()]+|www\.[^\s<>()]+|"
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"
)

_OPEN = ""
_CLOSE = ""


def protect(text: str) -> Tuple[str, Callable[[str], str]]:
    """Mask verbatim spans, returning the masked text and a restore function.

    Backticks are dropped along the way: they are markup for the reader, not
    something to pronounce.
    """
    values: Dict[str, str] = {}

    def stash(match: Match[str]) -> str:
        raw = match.group(0)
        if raw.startswith("```"):
            raw = raw[3:-3]
        elif raw.startswith("`"):
            raw = raw[1:-1]
        marker = f"{_OPEN}{chr(0xE100 + len(values))}{_CLOSE}"
        values[marker] = raw
        return marker

    masked = _PROTECTED.sub(stash, text)

    def restore(value: str) -> str:
        for marker, raw in values.items():
            value = value.replace(marker, raw)
        return value

    return masked, restore


__all__ = ["protect"]

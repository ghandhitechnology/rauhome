"""
What has happened at the table, shared by both halves of Rau.

The player agent reasons about moves; the face talker chats with the user. Each
needs to know what the other just did without sharing a model call, so both
read and write this ring buffer. Cleared when a hand is dealt or the table is
put away.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

#: How many entries to keep. Enough for a long hand without drowning the prompt.
CAPACITY = 60

_lock = threading.RLock()
_entries: List[Dict[str, Any]] = []

WHO_LABELS = {
    "rau": "Rau",
    "user": "Them",
    "table": "Table",
}


def clear() -> None:
    with _lock:
        _entries.clear()


def record(who: str, kind: str, text: str, *, at: Optional[float] = None) -> None:
    """
    Append one line. `who` is rau / user / table; `kind` is move, table_talk,
    user_chat, rau_chat, or event.
    """
    line = str(text or "").strip()
    if not line:
        return
    entry = {
        "who": who,
        "kind": kind,
        "text": line,
        "at": float(at if at is not None else time.time()),
    }
    with _lock:
        _entries.append(entry)
        overflow = len(_entries) - CAPACITY
        if overflow > 0:
            del _entries[:overflow]


def snapshot() -> List[Dict[str, Any]]:
    with _lock:
        return [dict(e) for e in _entries]


def tail(n: int = 24) -> str:
    """Formatted transcript for a model prompt. Empty string when nothing yet."""
    with _lock:
        recent = _entries[-max(0, n) :] if n else list(_entries)
    if not recent:
        return ""
    lines = ["## What has happened at the table"]
    for entry in recent:
        label = WHO_LABELS.get(entry["who"], entry["who"])
        kind = entry["kind"]
        if kind == "table_talk":
            lines.append(f"{label} (across the table): {entry['text']}")
        elif kind == "user_chat":
            lines.append(f"{label} said: {entry['text']}")
        elif kind == "rau_chat":
            lines.append(f"{label} replied: {entry['text']}")
        elif kind == "move":
            lines.append(f"{label} moved: {entry['text']}")
        else:
            lines.append(f"{label}: {entry['text']}")
    return "\n".join(lines) + "\n"

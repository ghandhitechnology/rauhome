"""
Surgical string edits for the agent.

`write_file` is the only other write path and it replaces the whole file, so
changing one line costs a full re-emission and any drift in that re-emission
silently overwrites working code. `edit_file` swaps an exact substring instead,
and refuses every case where it would have to guess:

* zero matches, or more than one without `replace_all`
* a file the agent has not read this session, or has read and then let change
  underneath it

Each refusal carries the counts and a nearby excerpt, because the model can
recover from "your anchor matched 3 times, here they are" and cannot recover
from a file that was quietly mangled.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import Any, Dict, List, Optional

from rau.agent.sandbox import PathEscape, resolve_in_root

EXCERPT_RADIUS = 3
MAX_REPORTED_MATCHES = 5


@dataclass(frozen=True)
class ReadStamp:
    """What the file looked like when the agent last saw it."""

    mtime_ns: int
    size: int


_reads: Dict[str, ReadStamp] = {}
_reads_lock = threading.Lock()


def _stamp(path: Path) -> Optional[ReadStamp]:
    try:
        st = path.stat()
    except OSError:
        return None
    return ReadStamp(mtime_ns=st.st_mtime_ns, size=st.st_size)


def note_read(path: Path) -> None:
    """Record that the agent has seen this file's current contents."""
    stamp = _stamp(path)
    if stamp is None:
        return
    with _reads_lock:
        _reads[str(path)] = stamp


def _seen_current(path: Path) -> tuple[bool, str]:
    with _reads_lock:
        known = _reads.get(str(path))
    if known is None:
        return False, (
            "file has not been read this session — call read_file on it before "
            "editing, so the edit is made against contents you have actually seen"
        )
    now = _stamp(path)
    if now is None:
        return False, "file disappeared after it was read"
    if now != known:
        return False, (
            "file changed since it was read — call read_file again before "
            "editing, or the edit will be made against stale contents"
        )
    return True, ""


def _read_verbatim(path: Path) -> str:
    """
    Read without newline translation.

    Universal newlines would hand back a CRLF file as LF, so an anchor carrying
    a real line ending could never match and saving the result would rewrite
    every line in the file as a side effect of a one-line edit.
    """
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_verbatim(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _excerpt(lines: List[str], center: int) -> str:
    """Numbered lines around a 1-based line number."""
    start = max(1, center - EXCERPT_RADIUS)
    end = min(len(lines), center + EXCERPT_RADIUS)
    return "\n".join(f"{i:>5}\t{lines[i - 1]}" for i in range(start, end + 1))


def _closest_excerpt(text: str, needle: str) -> str:
    """
    Best guess at where the model meant to point.

    Anchored on the first non-blank line of `old_string`: near-misses are almost
    always whitespace or a single renamed token, so the closest line by ratio is
    usually the intended site and seeing it is enough to fix the anchor.
    """
    probe = next((ln.strip() for ln in needle.splitlines() if ln.strip()), "")
    lines = text.splitlines()
    if not probe or not lines:
        return ""
    matcher = SequenceMatcher()
    matcher.set_seq2(probe)
    best_line, best_ratio = 0, 0.0
    for i, line in enumerate(lines, start=1):
        matcher.set_seq1(line.strip())
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_line, best_ratio = i, ratio
    if best_ratio < 0.5:
        return ""
    return _excerpt(lines, best_line)


def _match_indices(text: str, needle: str) -> List[int]:
    out: List[int] = []
    start = text.find(needle)
    while start != -1:
        out.append(start)
        start = text.find(needle, start + len(needle))
    return out


def _diff(before: str, after: str, path: Path) -> str:
    return "\n".join(
        list(
            unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
                n=2,
            )
        )[:60]
    )


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> Dict[str, Any]:
    try:
        target = resolve_in_root(path)
    except PathEscape as exc:
        return {"ok": False, "error": str(exc)}

    if not target.is_file():
        return {"ok": False, "error": "not found", "path": str(target)}

    if old_string == new_string:
        return {
            "ok": False,
            "error": "old_string and new_string are identical",
            "path": str(target),
        }
    if not old_string:
        return {
            "ok": False,
            "error": "old_string is empty — use write_file to create a file",
            "path": str(target),
        }

    seen, why = _seen_current(target)
    if not seen:
        return {"ok": False, "error": why, "path": str(target)}

    try:
        text = _read_verbatim(target)
    except UnicodeDecodeError:
        # `read_file` substitutes replacement characters so the model can look
        # at anything; writing that reading back would corrupt every byte it
        # could not decode, so a non-text file is refused rather than guessed at.
        return {
            "ok": False,
            "error": "not valid UTF-8 text — change it with a shell command instead",
            "path": str(target),
        }
    except OSError as exc:
        return {"ok": False, "error": f"could not read: {exc}", "path": str(target)}

    hits = _match_indices(text, old_string)

    if not hits:
        return {
            "ok": False,
            "error": "old_string not found",
            "path": str(target),
            "matches": 0,
            "nearest": _closest_excerpt(text, old_string),
        }

    if len(hits) > 1 and not replace_all:
        lines = text.splitlines()
        at = [_line_of(text, i) for i in hits]
        return {
            "ok": False,
            "error": (
                f"old_string matches {len(hits)} times — extend it with "
                "surrounding context until it is unique, or pass replace_all"
            ),
            "path": str(target),
            "matches": len(hits),
            "lines": at,
            "excerpts": [_excerpt(lines, n) for n in at[:MAX_REPORTED_MATCHES]],
        }

    updated = (
        text.replace(old_string, new_string)
        if replace_all
        else text.replace(old_string, new_string, 1)
    )
    try:
        _write_verbatim(target, updated)
    except OSError as exc:
        return {"ok": False, "error": f"could not write: {exc}", "path": str(target)}
    note_read(target)

    return {
        "ok": True,
        "path": str(target),
        "replacements": len(hits) if replace_all else 1,
        "diff": _diff(text, updated, target),
    }

"""Diary, traces, daily logs."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rau.paths import DAILY_DIR, DIARY_DIR, TRACES_DIR, ensure_dirs


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _stamp() -> str:
    return f"{datetime.now().strftime('%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


def _safe_file_part(value: str) -> str:
    """One safe filename component.

    The diary role can come from a tool call argument, so it must never carry
    a path separator (or enough length to break the filesystem) into the
    diary filename.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")
    return cleaned[:40] or "note"


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def append_diary(role: str, text: str, *, meta: Optional[Dict[str, Any]] = None) -> Path:
    ensure_dirs()
    day = DIARY_DIR / _today()
    day.mkdir(parents=True, exist_ok=True)
    role = _safe_file_part(role)
    path = day / f"{_stamp()}-{role}.md"
    body = [
        f"# {role}",
        f"time: {datetime.now().isoformat(timespec='seconds')}",
        "",
        text.strip(),
        "",
    ]
    if meta:
        body.extend(["```json", json.dumps(meta, indent=2), "```", ""])
    _atomic_text(path, "\n".join(body))
    return path


def append_trace(kind: str, payload: Dict[str, Any]) -> Path:
    ensure_dirs()
    path = TRACES_DIR / f"{_today()}-{_stamp()}-{kind}.json"
    _atomic_text(
        path,
        json.dumps({"ts": time.time(), "kind": kind, **payload}, indent=2) + "\n",
    )
    return path


def write_daily_log(day: str, content: str) -> Path:
    ensure_dirs()
    path = DAILY_DIR / f"{day}.md"
    _atomic_text(path, content.strip() + "\n")
    return path


def list_diary_day(day: Optional[str] = None) -> List[Path]:
    ensure_dirs()
    d = DIARY_DIR / (day or _today())
    if not d.exists():
        return []
    return sorted(d.glob("*.md"))


def read_diary_day(day: Optional[str] = None, limit: int = 200) -> str:
    parts: List[str] = []
    for p in list_diary_day(day)[-limit:]:
        parts.append(p.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def recent_context(max_chars: int = 6000) -> str:
    """Assemble recent diary for face/subagent context."""
    chunks: List[str] = []
    today = datetime.now().date()
    for offset in range(0, 3):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        text = read_diary_day(day)
        if text:
            chunks.append(f"## {day}\n\n{text}")
    blob = "\n\n".join(chunks)
    return blob[-max_chars:]


def purge_old_traces(ttl_days: int = 7) -> int:
    ensure_dirs()
    cutoff = time.time() - ttl_days * 86400
    removed = 0
    for p in TRACES_DIR.glob("*.json"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def summary() -> Dict[str, Any]:
    ensure_dirs()
    days = sorted([p.name for p in DIARY_DIR.iterdir() if p.is_dir()]) if DIARY_DIR.exists() else []
    dailies = sorted([p.name for p in DAILY_DIR.glob("*.md")]) if DAILY_DIR.exists() else []
    traces = list(TRACES_DIR.glob("*.json")) if TRACES_DIR.exists() else []
    return {
        "diary_days": days[-14:],
        "daily_logs": dailies[-14:],
        "trace_count": len(traces),
        "today_entries": len(list_diary_day()),
    }

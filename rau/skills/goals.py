"""Thread-safe persistence for Rau's single durable active goal."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

from rau.paths import ACTIVE_GOAL, ensure_dirs

_lock = threading.RLock()
MAX_GOAL_CHARS = 4000
MAX_NOTE_CHARS = 8000
MAX_NOTES = 200


def _read() -> Optional[Dict[str, Any]]:
    if not ACTIVE_GOAL.exists():
        return None
    try:
        data = json.loads(ACTIVE_GOAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not str(data.get("text") or "").strip():
        return None
    notes = data.get("notes")
    data["notes"] = notes if isinstance(notes, list) else []
    return data


def _write(data: Dict[str, Any]) -> None:
    ensure_dirs()
    tmp = ACTIVE_GOAL.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, ACTIVE_GOAL)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def get_goal() -> Optional[Dict[str, Any]]:
    with _lock:
        data = _read()
        return dict(data) if data else None


def set_goal(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "error": "empty goal"}
    if len(value) > MAX_GOAL_CHARS:
        return {"ok": False, "error": f"goal exceeds {MAX_GOAL_CHARS} characters"}
    now = time.time()
    with _lock:
        current = _read()
        goal = {
            "text": value,
            "created": current.get("created", now) if current else now,
            "updated": now,
            "notes": list(current.get("notes") or []) if current else [],
        }
        _write(goal)
        return goal


def clear_goal() -> Dict[str, Any]:
    with _lock:
        if not ACTIVE_GOAL.exists():
            return {"ok": True, "cleared": False, "archive": None}
        archive = ACTIVE_GOAL.with_name(f"cleared-{time.time_ns()}.json")
        try:
            os.replace(ACTIVE_GOAL, archive)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "cleared": True, "archive": str(archive)}


def add_note(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "error": "empty note"}
    if len(value) > MAX_NOTE_CHARS:
        return {"ok": False, "error": f"note exceeds {MAX_NOTE_CHARS} characters"}
    with _lock:
        goal = _read()
        if not goal:
            return {"ok": False, "error": "no active goal"}
        note = {"text": value, "created": time.time()}
        notes = list(goal.get("notes") or [])
        notes.append(note)
        goal["notes"] = notes[-MAX_NOTES:]
        goal["updated"] = note["created"]
        _write(goal)
        return {"ok": True, "goal": goal, "note": note}

"""Adaptive presence heartbeat — soft initiate with social backoff."""
from __future__ import annotations

import random
import threading
import time
from typing import Optional

from rau.events import BUS
from rau.memory.store import recent_context
from rau.providers.registry import load_settings
from rau import state

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def note_user_reply() -> None:
    state.update_presence(misses=0, last_user_ts=time.time(), muted_until=0.0)


def note_no_reply() -> None:
    settings = load_settings()
    threshold = int(settings.get("presence_backoff_after_misses") or 2)
    p = state.presence()
    misses = int(p.get("misses") or 0) + 1
    muted_until = 0.0
    if misses >= threshold:
        # back off for a while
        muted_until = time.time() + 30 * 60
        misses = 0
    state.update_presence(misses=misses, muted_until=muted_until)


def can_initiate() -> bool:
    p = state.presence()
    if time.time() < float(p.get("muted_until") or 0):
        return False
    snap = state.status_snapshot()
    if not snap.get("listening"):
        return False
    if snap.get("face_busy"):
        return False
    ht = snap.get("hard_task") or {}
    if ht.get("state") in ("running", "awaiting_confirm"):
        return False
    # don't spam
    if time.time() - float(p.get("last_initiate_ts") or 0) < 20 * 60:
        return False
    last_user = float(p.get("last_user_ts") or 0)
    # Never initiate before the first human turn (avoids boot chatter)
    if last_user <= 0:
        return False
    # need some silence after last user
    if time.time() - last_user < 12 * 60:
        return False
    return True


def maybe_nudge() -> None:
    if not can_initiate():
        return
    ctx = recent_context(2000)
    if "task" not in ctx.lower() and "friend" not in ctx.lower() and len(ctx) < 40:
        # still allow rare ambient hello
        if random.random() > 0.15:
            return
    line = (
        "Hey — I'm still here. Want to pick something up, "
        "or should I keep quiet a bit?"
    )
    state.update_presence(last_initiate_ts=time.time())
    BUS.emit("presence_nudge", text=line)
    state.push_control({"action": "speak", "text": line})


def heartbeat_loop() -> None:
    while not _stop.is_set():
        try:
            maybe_nudge()
            # progress reminders while hard task runs
            ht = state.get_hard_task()
            if ht.get("state") == "running":
                BUS.emit(
                    "hard_task_progress",
                    progress=ht.get("progress") or "still working",
                    id=ht.get("id"),
                )
        except Exception:
            pass
        _stop.wait(90)


def start_heartbeat() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=heartbeat_loop, daemon=True, name="rau-heart")
    _thread.start()


def stop_heartbeat() -> None:
    _stop.set()

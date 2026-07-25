"""Daily deep dreaming — compact diary into daily log + rewrite soul."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from rau.events import BUS
from rau.identity import store as identity_store
from rau.memory.store import purge_old_traces, read_diary_day, write_daily_log
from rau.paths import BACKSTORY_MD, IDENTITY_MD
from rau.providers.base import Message
from rau.providers.registry import chat_for_slot, load_settings
from rau import state

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _in_window(now: datetime, start: str, end: str) -> bool:
    def parse(hhmm: str):
        h, m = hhmm.split(":")
        return int(h), int(m)

    sh, sm = parse(start)
    eh, em = parse(end)
    minutes = now.hour * 60 + now.minute
    a = sh * 60 + sm
    b = eh * 60 + em
    if a <= b:
        return a <= minutes <= b
    return minutes >= a or minutes <= b


def should_defer() -> bool:
    snap = state.status_snapshot()
    if snap.get("face_busy"):
        return True
    ht = snap.get("hard_task") or {}
    if ht.get("state") in ("running", "awaiting_confirm"):
        return True
    return False


def run_dream(day: Optional[str] = None) -> dict:
    day = day or datetime.now().strftime("%Y-%m-%d")
    diary = read_diary_day(day)
    if not diary.strip():
        return {"ok": True, "skipped": True, "reason": "empty diary"}

    identity = identity_store.read_text(IDENTITY_MD)
    backstory = identity_store.read_text(BACKSTORY_MD)
    prev_soul = identity_store.load_soul()

    provider, slot = chat_for_slot("dream")
    prompt = (
        "You are Rau's deep dreaming process. Produce two sections:\n"
        "1) DAILY_LOG — markdown summary of the day's important memory.\n"
        "2) SOUL — a full rewritten soul.md for the living being Rau "
        "(one continuous self; no multi-agent talk).\n"
        "Separate them with a line containing only <<<SOUL>>>.\n\n"
        f"## identity.md\n{identity}\n\n"
        f"## backstory.md\n{backstory}\n\n"
        f"## previous soul.md\n{prev_soul}\n\n"
        f"## diary {day}\n{diary}\n"
    )
    result = provider.chat(
        [Message(role="user", content=prompt)],
        model=slot.get("model") or "deepseek/deepseek-v4-flash",
        max_tokens=int(slot.get("max_tokens") or 2048),
        temperature=float(slot.get("temperature") or 0.5),
        effort=str(slot.get("effort") or "medium"),
    )
    text = result.content or ""
    if "<<<SOUL>>>" in text:
        daily, soul = text.split("<<<SOUL>>>", 1)
    else:
        daily, soul = text, prev_soul

    write_daily_log(day, daily.strip() or f"# {day}\n\n(no summary)")
    if soul.strip():
        identity_store.write_soul(soul.strip(), backup=True)

    settings = load_settings()
    purge_old_traces(int(settings.get("trace_ttl_days") or 7))
    BUS.emit("dream_complete", day=day)
    return {"ok": True, "day": day, "daily_len": len(daily), "soul_len": len(soul)}


def dream_loop() -> None:
    settings = load_settings()
    start = settings.get("dream_window_start") or "02:00"
    end = settings.get("dream_window_end") or "05:00"
    last_day = ""
    while not _stop.is_set():
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        if (
            day != last_day
            and _in_window(now, start, end)
            and not should_defer()
        ):
            try:
                run_dream(day)
                last_day = day
            except Exception as e:
                BUS.emit("dream_error", error=str(e))
        _stop.wait(60)


def start_dreamer() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=dream_loop, daemon=True, name="rau-dream")
    _thread.start()


def stop_dreamer() -> None:
    _stop.set()

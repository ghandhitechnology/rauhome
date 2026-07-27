"""Daily deep dreaming — compact diary into daily log + rewrite soul."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from rau.events import BUS
from rau.identity import store as identity_store
from rau.memory.store import purge_old_traces, read_diary_day, write_daily_log
from rau.paths import BACKSTORY_MD, IDENTITY_MD
from rau.providers.base import Message
from rau.providers.registry import chat_for_slot, load_settings
from rau import state

_stop = threading.Event()
#: One dream at a time — the nightly tick and a manual /api/dream/run both
#: spend a paid provider call and rewrite soul.md.
_run_lock = threading.Lock()
_timer_state = {
    "last_day": "",
    "failure_day": "",
    "failures": 0,
    "next_retry": 0.0,
}


def _in_window(now: datetime, start: str, end: str) -> bool:
    def parse(hhmm: str):
        parts = str(hhmm or "").split(":")
        if len(parts) != 2:
            raise ValueError(f"invalid dream window time: {hhmm!r}")
        try:
            h, m = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError(f"invalid dream window time: {hhmm!r}") from exc
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"dream window time out of range: {hhmm!r}")
        return h, m

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
    if not _run_lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        if _stop.is_set():
            return {"ok": False, "status": "stopped"}
        manual = day is None
        day = day or datetime.now().strftime("%Y-%m-%d")
        settings = load_settings()
        # Retention must run even when the diary is empty, or quiet days let
        # traces grow without bound.
        purge_old_traces(int(settings.get("trace_ttl_days") or 7))
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
        if _stop.is_set():
            # Shutdown landed during the paid call; do not rewrite soul.md
            # while the process is exiting.
            return {"ok": False, "status": "stopped"}
        text = result.content or ""
        if "<<<SOUL>>>" in text:
            daily, soul = text.split("<<<SOUL>>>", 1)
        else:
            daily, soul = text, prev_soul

        write_daily_log(day, daily.strip() or f"# {day}\n\n(no summary)")
        if soul.strip():
            identity_store.write_soul(soul.strip(), backup=True)

        BUS.emit("dream_complete", day=day)
        if manual:
            # A successful manual run satisfies the scheduled dream for the
            # day it compacted — the tick's latch keys on the compacted day,
            # not the fire-day.
            _timer_state["last_day"] = day
        return {"ok": True, "day": day, "daily_len": len(daily), "soul_len": len(soul)}
    finally:
        _run_lock.release()


def start_dreamer() -> None:
    from rau.scheduler import SCHEDULER

    _stop.clear()
    SCHEDULER.register_timer(
        "dream", _dream_tick, interval_sec=60.0, initial_delay_sec=1.0
    )


def stop_dreamer() -> None:
    from rau.scheduler import SCHEDULER

    _stop.set()
    SCHEDULER.unregister_timer("dream")


def _dream_tick() -> None:
    settings = load_settings()
    start = settings.get("dream_window_start") or "02:00"
    end = settings.get("dream_window_end") or "05:00"
    day = ""
    try:
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        if day != _timer_state["failure_day"]:
            _timer_state.update(
                failure_day=day, failures=0, next_retry=0.0
            )
        # The window opens just after midnight: compact the day that
        # ended, not the near-empty diary of the day that just started.
        # The once-per-night latch keys on that compacted day, so a manual
        # run that already compacted it suppresses the tick.
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if (
            yesterday != _timer_state["last_day"]
            and int(_timer_state["failures"]) < 3
            and time.time() >= float(_timer_state["next_retry"])
            and _in_window(now, start, end)
            and not should_defer()
        ):
            result = run_dream(yesterday)
            if result.get("ok"):
                # Latch only a compaction that actually ran — latching on
                # already_running/stopped would suppress a dream that
                # never happened.
                _timer_state.update(last_day=yesterday, failures=0)
    except Exception as exc:
        failures = int(_timer_state["failures"]) + 1
        delay = 300 if failures == 1 else 1800
        _timer_state.update(
            failures=failures, next_retry=time.time() + delay
        )
        BUS.emit(
            "dream_error", day=day or None, attempt=failures, error=str(exc)
        )

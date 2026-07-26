"""Event-driven durable schedule coordinator."""
from __future__ import annotations

import math
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rau.control.store import ControlStore, control_store
from rau.events import BUS
from rau.scheduler.cron import CronError, CronSpec, nominal_key

TRIGGER_KINDS = ("once", "interval", "cron")
RESOURCE_PROFILES = ("eco", "balanced", "performance")
PERMISSION_POLICIES = ("readonly", "approval")
DEFAULT_TIMEZONE = "Asia/Seoul"
MAX_GOAL_CHARS = 100_000
MAX_INTERVAL_SEC = 366 * 24 * 3600
MIN_INTERVAL_SEC = 60
MAX_CATCHUP_SCAN = 100_000
RETRY_BACKOFF_SEC = (30, 120, 600)


def _timestamp(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a timestamp")
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{name} is required")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError as exc:
            raise ValueError(f"{name} must be ISO-8601 or epoch seconds") from exc
    else:
        raise ValueError(f"{name} must be ISO-8601 or epoch seconds")
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite timestamp")
    return parsed


def _timezone(name: Any) -> str:
    value = str(name or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {value}") from exc
    return value


def _normalize_trigger(
    trigger: Dict[str, Any], timezone_name: str, now: float
) -> Tuple[str, Dict[str, Any], float]:
    if not isinstance(trigger, dict):
        raise ValueError("trigger must be an object")
    kind = str(trigger.get("kind") or "").lower()
    if kind not in TRIGGER_KINDS:
        raise ValueError(f"trigger.kind must be one of {', '.join(TRIGGER_KINDS)}")
    if kind == "once":
        at = _timestamp(trigger.get("at"), "trigger.at")
        return kind, {"kind": kind, "at": at}, at
    if kind == "interval":
        try:
            seconds = int(trigger.get("seconds"))
        except (TypeError, ValueError) as exc:
            raise ValueError("trigger.seconds must be an integer") from exc
        if not MIN_INTERVAL_SEC <= seconds <= MAX_INTERVAL_SEC:
            raise ValueError(
                f"trigger.seconds must be between {MIN_INTERVAL_SEC} and {MAX_INTERVAL_SEC}"
            )
        anchor = _timestamp(trigger.get("anchor") or now, "trigger.anchor")
        if anchor <= now:
            elapsed = max(0.0, now - anchor)
            anchor += (math.floor(elapsed / seconds) + 1) * seconds
        return kind, {"kind": kind, "seconds": seconds, "anchor": anchor}, anchor
    expression = str(trigger.get("expression") or "").strip()
    spec = CronSpec.parse(expression)
    next_run = spec.next_after(now, timezone_name)
    return kind, {"kind": kind, "expression": spec.expression}, next_run


def _next_after(schedule: Dict[str, Any], timestamp: float) -> Optional[float]:
    trigger = schedule["trigger"]
    kind = schedule["trigger_kind"]
    if kind == "once":
        return None
    if kind == "interval":
        return timestamp + int(trigger["seconds"])
    return CronSpec.parse(trigger["expression"]).next_after(
        timestamp, schedule["timezone"]
    )


def _occurrence_key(schedule: Dict[str, Any], timestamp: float) -> str:
    if schedule["trigger_kind"] == "cron":
        return nominal_key(timestamp, schedule["timezone"])
    return f"utc:{int(timestamp * 1_000_000)}"


class SchedulerService:
    def __init__(self, store: ControlStore = control_store):
        self.store = store
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listener_registered = False
        self._timers: Dict[str, Dict[str, Any]] = {}
        self._timer_runs: Dict[str, Future[Any]] = {}
        self._timer_lock = threading.RLock()
        self._timer_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="rau-timer"
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.initialize()
        self._stop.clear()
        self._wake.clear()
        if not self._listener_registered:
            BUS.on("job_done", self._job_terminal)
            BUS.on("job_failed", self._job_terminal)
            self._listener_registered = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="rau-scheduler"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        if self._listener_registered:
            BUS.off("job_done", self._job_terminal)
            BUS.off("job_failed", self._job_terminal)
            self._listener_registered = False

    def wake(self) -> None:
        self._wake.set()

    def register_timer(
        self,
        name: str,
        callback: Any,
        *,
        interval_sec: float,
        initial_delay_sec: float = 0.0,
    ) -> None:
        with self._timer_lock:
            self._timers[str(name)] = {
                "callback": callback,
                "interval": max(1.0, float(interval_sec)),
                "next_at": time.time() + max(0.0, float(initial_delay_sec)),
            }
        self.wake()

    def unregister_timer(self, name: str) -> None:
        with self._timer_lock:
            self._timers.pop(str(name), None)
        self.wake()

    def create(self, body: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
        stamp = now or time.time()
        name = str(body.get("name") or "").strip()
        goal = str(body.get("goal") or "").strip()
        if not name:
            raise ValueError("name is required")
        if not goal or len(goal) > MAX_GOAL_CHARS:
            raise ValueError(f"goal must contain 1-{MAX_GOAL_CHARS} characters")
        tz = _timezone(body.get("timezone"))
        kind, trigger, next_run = _normalize_trigger(body.get("trigger"), tz, stamp)
        profile = str(body.get("resource_profile") or "balanced").lower()
        if profile not in RESOURCE_PROFILES:
            raise ValueError("invalid resource_profile")
        policy = str(body.get("permission_policy") or "approval").lower()
        if policy not in PERMISSION_POLICIES:
            raise ValueError("invalid permission_policy")
        record = {
            "id": str(uuid.uuid4()),
            "name": name[:200],
            "enabled": bool(body.get("enabled", True)),
            "goal": goal,
            "trigger_kind": kind,
            "trigger": trigger,
            "timezone": tz,
            "resource_profile": profile,
            "permission_policy": policy,
            "overlap_policy": "coalesce",
            "budget": self._budget(body.get("budget")),
            "next_run_at": next_run if body.get("enabled", True) else None,
            "revision": 1,
            "created": stamp,
            "updated": stamp,
        }
        saved = self.store.create_schedule(record)
        self.store.append_event("schedule_created", "schedule", saved["id"], saved)
        BUS.emit("schedule_changed", action="created", schedule=saved)
        self.wake()
        return saved

    def update(
        self, schedule_id: str, body: Dict[str, Any], *, now: Optional[float] = None
    ) -> Dict[str, Any]:
        current = self.store.get_schedule(schedule_id)
        if current is None:
            raise KeyError(schedule_id)
        stamp = now or time.time()
        merged = {**current, **body}
        tz = _timezone(merged.get("timezone"))
        trigger_input = body.get("trigger", current["trigger"])
        kind, trigger, next_run = _normalize_trigger(trigger_input, tz, stamp)
        changes: Dict[str, Any] = {
            "name": str(merged.get("name") or "").strip()[:200],
            "goal": str(merged.get("goal") or "").strip(),
            "enabled": bool(merged.get("enabled", True)),
            "trigger_kind": kind,
            "trigger": trigger,
            "timezone": tz,
            "resource_profile": str(
                merged.get("resource_profile") or "balanced"
            ).lower(),
            "permission_policy": str(
                merged.get("permission_policy") or "approval"
            ).lower(),
            "overlap_policy": "coalesce",
            "budget": self._budget(merged.get("budget")),
            "next_run_at": next_run if merged.get("enabled", True) else None,
            "last_nominal_at": None,
        }
        if not changes["name"] or not changes["goal"]:
            raise ValueError("name and goal are required")
        if changes["resource_profile"] not in RESOURCE_PROFILES:
            raise ValueError("invalid resource_profile")
        if changes["permission_policy"] not in PERMISSION_POLICIES:
            raise ValueError("invalid permission_policy")
        saved = self.store.update_schedule(schedule_id, changes)
        if saved is None:
            raise KeyError(schedule_id)
        self.store.append_event("schedule_updated", "schedule", schedule_id, saved)
        BUS.emit("schedule_changed", action="updated", schedule=saved)
        self.wake()
        return saved

    def delete(self, schedule_id: str) -> bool:
        deleted = self.store.delete_schedule(schedule_id)
        if deleted:
            self.store.append_event(
                "schedule_deleted", "schedule", schedule_id, {"id": schedule_id}
            )
            BUS.emit("schedule_changed", action="deleted", id=schedule_id)
            self.wake()
        return deleted

    def pause(self, schedule_id: str) -> Dict[str, Any]:
        value = self.store.update_schedule(
            schedule_id, {"enabled": False, "next_run_at": None}
        )
        if value is None:
            raise KeyError(schedule_id)
        BUS.emit("schedule_changed", action="paused", schedule=value)
        self.wake()
        return value

    def resume(self, schedule_id: str, *, now: Optional[float] = None) -> Dict[str, Any]:
        current = self.store.get_schedule(schedule_id)
        if current is None:
            raise KeyError(schedule_id)
        stamp = now or time.time()
        if current["trigger_kind"] == "once":
            next_run = float(current["trigger"]["at"])
        elif current["trigger_kind"] == "interval":
            seconds = int(current["trigger"]["seconds"])
            anchor = float(current["trigger"]["anchor"])
            if anchor <= stamp:
                anchor += (math.floor((stamp - anchor) / seconds) + 1) * seconds
            next_run = anchor
        else:
            next_run = CronSpec.parse(
                current["trigger"]["expression"]
            ).next_after(stamp, current["timezone"])
        value = self.store.update_schedule(
            schedule_id, {"enabled": True, "next_run_at": next_run}
        )
        assert value is not None
        BUS.emit("schedule_changed", action="resumed", schedule=value)
        self.wake()
        return value

    def run_now(self, schedule_id: str, *, now: Optional[float] = None) -> Dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id)
        if schedule is None:
            raise KeyError(schedule_id)
        if self.store.active_schedule_run(schedule_id):
            raise RuntimeError("schedule already has an active run")
        stamp = now or time.time()
        run = self.store.create_schedule_run(
            {
                "id": str(uuid.uuid4()),
                "schedule_id": schedule_id,
                "schedule_revision": int(schedule["revision"]),
                "nominal_at": stamp,
                "nominal_key": f"manual:{uuid.uuid4()}",
                "enqueued_at": stamp,
                "state": "queued",
            }
        )
        assert run is not None
        self._dispatch_queued()
        self.wake()
        return self.store.get_schedule_run(run["id"]) or run

    @staticmethod
    def _budget(value: Any) -> Dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        return {
            "max_runtime_sec": max(
                60, min(24 * 3600, int(raw.get("max_runtime_sec") or 3600))
            ),
            "max_turns": max(1, min(64, int(raw.get("max_turns") or 24))),
            "max_retries": max(0, min(3, int(raw.get("max_retries") or 3))),
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                BUS.emit("scheduler_error", error=str(exc)[:1000])
            next_at = self.store.next_schedule_time()
            with self._timer_lock:
                timer_at = min(
                    (float(timer["next_at"]) for timer in self._timers.values()),
                    default=None,
                )
            if timer_at is not None:
                next_at = timer_at if next_at is None else min(next_at, timer_at)
            timeout = 60.0 if next_at is None else max(
                0.1, min(60.0, next_at - time.time())
            )
            self._wake.wait(timeout)
            self._wake.clear()

    def tick(self, *, now: Optional[float] = None) -> None:
        stamp = now or time.time()
        self.store.expire_confirmations(now=stamp)
        for schedule in self.store.due_schedules(stamp):
            self._enqueue_due(schedule, stamp)
        self._dispatch_queued()
        self._dispatch_timers(stamp)
        # Pi is a demand-started optional backend. The scheduler timer is
        # already awake, so reuse it instead of adding another polling loop.
        try:
            from rau.pi.supervisor import PI_SUPERVISOR
            from rau.resources import current_profile

            PI_SUPERVISOR.stop_if_idle(
                float(current_profile()["pi_idle_timeout_sec"])
            )
        except Exception:
            pass

    def _dispatch_timers(self, now: float) -> None:
        with self._timer_lock:
            for name, timer in list(self._timers.items()):
                future = self._timer_runs.get(name)
                if future is not None and future.done():
                    self._timer_runs.pop(name, None)
                    future = None
                if float(timer["next_at"]) > now or future is not None:
                    continue
                # Advance before dispatch; slow maintenance never overlaps itself
                # and never blocks occurrence enqueueing.
                timer["next_at"] = now + float(timer["interval"])
                self._timer_runs[name] = self._timer_pool.submit(
                    self._run_timer, name, timer["callback"]
                )

    @staticmethod
    def _run_timer(name: str, callback: Any) -> None:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            BUS.emit("timer_error", timer=name, error=str(exc)[:1000])

    def _enqueue_due(self, schedule: Dict[str, Any], now: float) -> None:
        first = float(schedule["next_run_at"])
        latest = first
        count = 1
        cursor = first
        seen = {_occurrence_key(schedule, first)}
        next_at = _next_after(schedule, cursor)
        scanned = 0
        while next_at is not None and next_at <= now and scanned < MAX_CATCHUP_SCAN:
            key = _occurrence_key(schedule, next_at)
            if key not in seen:
                seen.add(key)
                latest = next_at
                count += 1
            cursor = next_at
            next_at = _next_after(schedule, cursor)
            scanned += 1

        pending = self.store.pending_schedule_run(schedule["id"])
        if pending is not None:
            self.store.update_schedule_run(
                pending["id"],
                coalesced_count=int(pending["coalesced_count"]) + count,
                missed_from=pending.get("missed_from") or first,
                missed_to=latest,
            )
        else:
            # When another occurrence is already executing, this queued record
            # is the one permitted catch-up. Dispatch holds it until the active
            # run reaches a terminal state.
            self.store.create_schedule_run(
                {
                    "id": str(uuid.uuid4()),
                    "schedule_id": schedule["id"],
                    "schedule_revision": int(schedule["revision"]),
                    "nominal_at": latest,
                    "nominal_key": _occurrence_key(schedule, latest),
                    "enqueued_at": now,
                    "state": "queued",
                    "coalesced_count": count,
                    "missed_from": first if count > 1 else None,
                    "missed_to": latest if count > 1 else None,
                }
            )

        changes: Dict[str, Any] = {
            "last_nominal_at": latest,
            "next_run_at": next_at,
        }
        if schedule["trigger_kind"] == "once":
            changes["enabled"] = False
        self.store.update_schedule(schedule["id"], changes, bump_revision=False)

    def _dispatch_queued(self) -> None:
        from rau.agent import orchestrator

        for run in self.store.queued_schedule_runs(limit=100):
            executing = self.store.executing_schedule_run(run["schedule_id"])
            if executing is not None and executing["id"] != run["id"]:
                continue
            schedule = self.store.get_schedule(run["schedule_id"])
            if schedule is None:
                self.store.update_schedule_run(run["id"], state="cancelled")
                continue
            if int(run["schedule_revision"]) != int(schedule["revision"]):
                self.store.update_schedule_run(
                    run["id"],
                    state="cancelled",
                    outcome={"reason": "schedule edited before dispatch"},
                )
                continue
            result = orchestrator.start_job(
                schedule["goal"],
                scheduled_run_id=run["id"],
                permission_policy=schedule["permission_policy"],
                resource_profile=schedule["resource_profile"],
                budget={
                    **schedule["budget"],
                    "attempt": int(run.get("attempt") or 0) + 1,
                },
            )
            if result.get("ok"):
                self.store.update_schedule_run(
                    run["id"],
                    state="running",
                    job_id=result["id"],
                    retry_at=None,
                    attempt=int(run.get("attempt") or 0) + 1,
                )
                BUS.emit(
                    "schedule_run_started",
                    schedule_id=schedule["id"],
                    run_id=run["id"],
                    job_id=result["id"],
                )
            elif result.get("reason") != "at_capacity":
                self.store.update_schedule_run(
                    run["id"],
                    state="failed",
                    outcome={"error": result.get("error") or "could not start job"},
                )

    def _job_terminal(self, event: Dict[str, Any]) -> None:
        job_id = str(event.get("id") or "")
        if not job_id:
            return
        run = self.store.schedule_run_for_job(job_id)
        if run is None:
            return
        raw_state = str(event.get("state") or "")
        error = str(event.get("error") or "")
        schedule = self.store.get_schedule(run["schedule_id"])
        attempt = int(run.get("attempt") or 0)
        max_retries = int((schedule or {}).get("budget", {}).get("max_retries") or 0)
        if (
            raw_state not in {"done", "completed", "cancelled"}
            and schedule is not None
            and attempt <= min(max_retries, len(RETRY_BACKOFF_SEC))
            and self._transient_failure(error)
        ):
            delay = RETRY_BACKOFF_SEC[max(0, attempt - 1)]
            self.store.update_schedule_run(
                run["id"],
                state="queued",
                job_id=None,
                retry_at=time.time() + delay,
                outcome={
                    "error": error,
                    "retry_in_sec": delay,
                    "strategy": (
                        f"attempt {attempt + 1}: rebuild provider context and "
                        "retry from the persisted plan"
                    ),
                },
            )
            BUS.emit(
                "schedule_run_retry",
                schedule_id=run["schedule_id"],
                run_id=run["id"],
                attempt=attempt + 1,
                retry_in_sec=delay,
            )
            self.wake()
            return
        state = {
            "done": "completed",
            "completed": "completed",
            "cancelled": "cancelled",
        }.get(raw_state, "failed")
        self.store.update_schedule_run(
            run["id"],
            state=state,
            outcome={
                "result": str(event.get("result") or ""),
                "error": error,
            },
        )
        BUS.emit(
            "schedule_run_finished",
            schedule_id=run["schedule_id"],
            run_id=run["id"],
            job_id=job_id,
            state=state,
        )
        self.wake()

    @staticmethod
    def _transient_failure(error: str) -> bool:
        text = error.lower()
        if "unknown_effect" in text or "unknown effect" in text:
            return False
        return any(
            marker in text
            for marker in (
                "timeout",
                "timed out",
                "rate limit",
                "temporar",
                "provider",
                "connection",
                "network",
                "unavailable",
                "overloaded",
            )
        )

    def status(self) -> Dict[str, Any]:
        thread = self._thread
        return {
            "running": bool(thread and thread.is_alive()),
            "next_run_at": self.store.next_schedule_time(),
            "schedules": len(self.store.list_schedules()),
            "queued_runs": len(self.store.queued_schedule_runs()),
        }


SCHEDULER = SchedulerService()

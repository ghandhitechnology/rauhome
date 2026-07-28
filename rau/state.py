"""Shared runtime state."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

_lock = threading.RLock()

_state: Dict[str, Any] = {
    "emotion": "idle",
    "text": "",
    "timestamp": time.time(),
    "listening": True,
    "face_busy": False,
    "voice_pipeline": False,
    "presence": {
        "misses": 0,
        "muted_until": 0.0,
        "last_user_ts": 0.0,
        "last_initiate_ts": 0.0,
        "reentry_pending": False,
        "reentry_tier": "none",
        "gap_sec": 0.0,
        "mood": {"label": "idle", "intensity": 0.0, "updated_at": 0.0},
        "heartbeat_events": [],
    },
}

_chat_log: List[Dict[str, Any]] = []
MAX_LOG = 100
_control_queue: deque[Dict[str, Any]] = deque(maxlen=256)
_browser_voice_sessions = 0
_listening_before_browser_voice: Optional[bool] = None

# Background jobs, newest ideas and oldest leftovers alike, keyed by job id.
_jobs: Dict[str, Dict[str, Any]] = {}
# Pending confirmations, keyed by the job waiting on them: one per job at most.
_confirms: Dict[str, Dict[str, Any]] = {}
MAX_JOBS = 40

ACTIVE_JOB_STATES = ("running", "awaiting_confirm")
TERMINAL_JOB_STATES = ("done", "failed", "cancelled")

_durable_enabled = False

_TO_DURABLE_STATE = {
    "running": "running",
    "awaiting_confirm": "awaiting_confirm",
    "done": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}
_FROM_DURABLE_STATE = {
    "queued": "running",
    "planning": "running",
    "running": "running",
    "verifying": "running",
    "awaiting_confirm": "awaiting_confirm",
    "completed": "done",
    "failed": "failed",
    "cancelled": "cancelled",
    "interrupted": "failed",
}

IDLE_HARD_TASK: Dict[str, Any] = {
    "state": "idle",
    "goal": "",
    "progress": "",
    "result": "",
    "id": None,
}

# Desktop pet visibility. Effective visible = not face_open and not user_hidden.
_pet: Dict[str, Any] = {
    "visible": True,
    "face_open": False,
    "user_hidden": False,
}


def _pet_effective() -> bool:
    return (not _pet["face_open"]) and (not _pet["user_hidden"])


def get_pet() -> Dict[str, Any]:
    with _lock:
        return {
            "visible": _pet_effective(),
            "face_open": bool(_pet["face_open"]),
            "user_hidden": bool(_pet["user_hidden"]),
        }


def set_pet_visibility(
    *,
    face_open: Optional[bool] = None,
    user_hidden: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update pet mutex flags and return the public snapshot."""
    with _lock:
        if face_open is not None:
            _pet["face_open"] = bool(face_open)
        if user_hidden is not None:
            _pet["user_hidden"] = bool(user_hidden)
        _pet["visible"] = _pet_effective()
        return {
            "visible": _pet["visible"],
            "face_open": bool(_pet["face_open"]),
            "user_hidden": bool(_pet["user_hidden"]),
        }


def get_emotion() -> Dict[str, Any]:
    with _lock:
        return _public_state()


def set_emotion(emotion: str, text: str = "") -> Dict[str, Any]:
    """Update presence emotion/text only — never appends to the chat log.

    Callers that want a visible reply must use add_log explicitly. Logging
    here used to double every spoken turn (add_log + set_emotion + speak).
    """
    with _lock:
        _state["emotion"] = emotion
        _state["text"] = text
        _state["timestamp"] = time.time()
        return _public_state()


def add_log(role: str, text: str, turn_id: Optional[str] = None) -> None:
    with _lock:
        entry = {"role": role, "text": text, "time": time.strftime("%H:%M:%S")}
        if turn_id:
            entry["turn_id"] = turn_id
        _chat_log.append(entry)
        if len(_chat_log) > MAX_LOG:
            del _chat_log[: len(_chat_log) - MAX_LOG]


def get_log() -> List[Dict[str, Any]]:
    with _lock:
        return list(_chat_log[-MAX_LOG:])


def push_control(cmd: Dict[str, Any]) -> None:
    with _lock:
        _control_queue.append(cmd)


def pop_control() -> Optional[Dict[str, Any]]:
    with _lock:
        if not _control_queue:
            return None
        return _control_queue.popleft()


def enable_durable_state() -> Dict[str, Any]:
    """Hydrate restart-visible jobs and enable persistence for future updates."""
    global _durable_enabled
    from rau.control import control_store

    control_store.initialize()
    interrupted = control_store.mark_unfinished_interrupted()
    loaded = control_store.load_jobs(limit=MAX_JOBS)
    with _lock:
        for durable in loaded:
            state_name = _FROM_DURABLE_STATE.get(
                str(durable.get("state") or ""), "failed"
            )
            result = str(durable.get("result") or "")
            if durable.get("state") == "interrupted" and not result:
                result = "Job interrupted by a process restart."
            _jobs[str(durable["id"])] = {
                "id": str(durable["id"]),
                "goal": str(durable.get("goal") or ""),
                "state": state_name,
                "lifecycle_state": str(durable.get("state") or ""),
                "progress": str(durable.get("progress") or ""),
                "result": result,
                "parent_id": durable.get("parent_id"),
                "depth": int(durable.get("depth") or 1),
                "executor": str(durable.get("executor") or "python"),
                "attempt": int(durable.get("attempt") or 0),
                "plan": durable.get("plan") or {},
                "budget": durable.get("budget") or {},
                "lease_owner": durable.get("lease_owner"),
                "lease_expires": durable.get("lease_expires"),
                "scheduled_run_id": durable.get("scheduled_run_id"),
                "origin_turn_id": durable.get("origin_turn_id"),
                "plan_revision": int(durable.get("plan_revision") or 1),
                "terminal_reason": str(durable.get("terminal_reason") or ""),
                "created": float(durable.get("created") or time.time()),
                "updated": float(durable.get("updated") or time.time()),
            }
        _trim_jobs()
        _durable_enabled = True
    return {"ok": True, "loaded": len(loaded), "interrupted": interrupted}


def durable_enabled() -> bool:
    return _durable_enabled


def _persist_job(job: Dict[str, Any]) -> None:
    if not _durable_enabled:
        return
    from rau.control import control_store

    durable = dict(job)
    lifecycle = str(job.get("lifecycle_state") or "")
    durable["state"] = (
        lifecycle
        if lifecycle
        in {
            "queued",
            "planning",
            "running",
            "verifying",
            "awaiting_confirm",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        }
        else _TO_DURABLE_STATE.get(str(job.get("state") or ""), "failed")
    )
    durable["lifecycle_state"] = durable["state"]
    control_store.upsert_job(durable)


def set_listening(on: bool) -> None:
    global _listening_before_browser_voice
    with _lock:
        if _browser_voice_sessions:
            # Remember the host pipeline's desired state for the final release,
            # but never let it resume underneath an active browser socket.
            _listening_before_browser_voice = bool(on)
            _state["listening"] = False
        else:
            _state["listening"] = bool(on)


def acquire_browser_voice() -> None:
    """Suspend the host mic until the last browser voice socket closes."""
    global _browser_voice_sessions, _listening_before_browser_voice
    with _lock:
        if _browser_voice_sessions == 0:
            _listening_before_browser_voice = bool(_state["listening"])
        _browser_voice_sessions += 1
        _state["listening"] = False


def release_browser_voice() -> None:
    """Release one browser voice lease without racing concurrent sockets."""
    global _browser_voice_sessions, _listening_before_browser_voice
    with _lock:
        if _browser_voice_sessions <= 0:
            return
        _browser_voice_sessions -= 1
        if _browser_voice_sessions == 0:
            if _listening_before_browser_voice is not None:
                _state["listening"] = _listening_before_browser_voice
            _listening_before_browser_voice = None


def set_face_busy(busy: bool) -> None:
    with _lock:
        _state["face_busy"] = busy


def set_voice_pipeline(on: bool) -> None:
    with _lock:
        _state["voice_pipeline"] = on


def create_job(
    job_id: str,
    goal: str,
    parent_id: Optional[str] = None,
    depth: int = 0,
    *,
    origin_turn_id: Optional[str] = None,
    plan_revision: int = 1,
) -> Dict[str, Any]:
    now = time.time()
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "goal": goal,
            "state": "running",
            "lifecycle_state": "running",
            "progress": "starting",
            "result": "",
            # Carried so a client can draw the tree; the single-slot hard_task
            # view stays flat and unaware of it.
            "parent_id": parent_id,
            "depth": depth,
            "origin_turn_id": origin_turn_id,
            "plan_revision": max(1, int(plan_revision)),
            "created": now,
            "updated": now,
        }
        _trim_jobs()
        view = _job_view(_jobs[job_id])
    _persist_job(view)
    return view


def update_job(job_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Apply a partial update; a finished job is immutable.

    A worker only checks its cancel flag between steps, so a cancel landing
    just before its next write would otherwise resurrect the job into
    "running" — holding a parallel slot and a permanently busy face forever.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return {}
        if job["state"] in TERMINAL_JOB_STATES:
            return _job_view(job)
        job.update(kwargs)
        if "state" in kwargs and "lifecycle_state" not in kwargs:
            job["lifecycle_state"] = _TO_DURABLE_STATE.get(
                str(kwargs["state"]), str(kwargs["state"])
            )
        job["updated"] = time.time()
        view = _job_view(job)
    _persist_job(view)
    return view


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _job_view(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    with _lock:
        return [
            _job_view(j) for j in sorted(_jobs.values(), key=lambda j: j["created"])
        ]


def get_hard_task() -> Dict[str, Any]:
    """Single-slot view of the job registry, for callers written before jobs.

    Live work outranks finished work: the face, heartbeat and dreamer all gate
    on this, and they must keep seeing "busy" while any job is still going even
    if a later-started one has already reported back.
    """
    with _lock:
        job = _current_job()
        if not job:
            return dict(IDLE_HARD_TASK)
        return {k: job[k] for k in ("id", "goal", "state", "progress", "result")}


def set_confirm(job_id: str, payload: Optional[Dict[str, Any]]) -> None:
    with _lock:
        if payload is None:
            _confirms.pop(job_id, None)
        else:
            _confirms[job_id] = dict(payload)
    if payload is not None and _durable_enabled:
        from rau.control import control_store

        control_store.save_confirmation(payload)


def get_confirm() -> Optional[Dict[str, Any]]:
    """Oldest pending confirm — whoever has been waiting on the user longest."""
    with _lock:
        job_id = _waiting_job_id()
        return dict(_confirms[job_id]) if job_id else None


def confirm_job_id(confirm_id: str) -> Optional[str]:
    with _lock:
        for job_id, payload in _confirms.items():
            if payload.get("id") == confirm_id:
                return job_id
        return None


def _job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    confirm = _confirms.get(job["id"])
    return {**job, "confirm": dict(confirm) if confirm else None}


def _waiting_job_id() -> Optional[str]:
    if not _confirms:
        return None
    return min(_confirms.items(), key=lambda kv: kv[1].get("created") or 0.0)[0]


def _current_job() -> Optional[Dict[str, Any]]:
    if not _jobs:
        return None
    active = [j for j in _jobs.values() if j["state"] in ACTIVE_JOB_STATES]
    if not active:
        return max(_jobs.values(), key=lambda j: j["updated"])
    # The slot must name the goal whose confirm get_confirm() hands out, or the
    # dashboard renders one job's question under another job's goal and the
    # answer lands on the wrong worker.
    waiting = _jobs.get(_waiting_job_id() or "")
    if waiting is not None and waiting["state"] in ACTIVE_JOB_STATES:
        return waiting
    return min(active, key=lambda j: j["created"])


def _trim_jobs() -> None:
    finished = sorted(
        (j for j in _jobs.values() if j["state"] not in ACTIVE_JOB_STATES),
        key=lambda j: j["updated"],
    )
    while len(_jobs) > MAX_JOBS and finished:
        stale = finished.pop(0)["id"]
        _jobs.pop(stale, None)
        _confirms.pop(stale, None)


def _public_state() -> Dict[str, Any]:
    return {**_state, "hard_task": get_hard_task(), "confirm": get_confirm()}


def presence() -> Dict[str, Any]:
    with _lock:
        return dict(_state["presence"])


def update_presence(**kwargs: Any) -> Dict[str, Any]:
    with _lock:
        _state["presence"].update(kwargs)
        return dict(_state["presence"])


def status_snapshot() -> Dict[str, Any]:
    with _lock:
        return {
            "emotion": _state["emotion"],
            "listening": _state["listening"],
            "face_busy": _state["face_busy"],
            "voice_pipeline": _state["voice_pipeline"],
            "hard_task": get_hard_task(),
            "confirm": get_confirm(),
            "jobs": list_jobs(),
            "presence": dict(_state["presence"]),
            "pet": {
                "visible": _pet_effective(),
                "face_open": bool(_pet["face_open"]),
                "user_hidden": bool(_pet["user_hidden"]),
            },
            "timestamp": time.time(),
        }

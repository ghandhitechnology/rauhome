"""Shared runtime state."""
from __future__ import annotations

import threading
import time
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
    },
}

_chat_log: List[Dict[str, Any]] = []
MAX_LOG = 100
_control_queue: List[Dict[str, Any]] = []
_browser_voice_sessions = 0
_listening_before_browser_voice: Optional[bool] = None

# Background jobs, newest ideas and oldest leftovers alike, keyed by job id.
_jobs: Dict[str, Dict[str, Any]] = {}
# Pending confirmations, keyed by the job waiting on them: one per job at most.
_confirms: Dict[str, Dict[str, Any]] = {}
MAX_JOBS = 40

ACTIVE_JOB_STATES = ("running", "awaiting_confirm")
TERMINAL_JOB_STATES = ("done", "failed", "cancelled")

IDLE_HARD_TASK: Dict[str, Any] = {
    "state": "idle",
    "goal": "",
    "progress": "",
    "result": "",
    "id": None,
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


def add_log(role: str, text: str) -> None:
    with _lock:
        _chat_log.append(
            {"role": role, "text": text, "time": time.strftime("%H:%M:%S")}
        )
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
        return _control_queue.pop(0)


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
) -> Dict[str, Any]:
    now = time.time()
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "goal": goal,
            "state": "running",
            "progress": "starting",
            "result": "",
            # Carried so a client can draw the tree; the single-slot hard_task
            # view stays flat and unaware of it.
            "parent_id": parent_id,
            "depth": depth,
            "created": now,
            "updated": now,
        }
        _trim_jobs()
        return _job_view(_jobs[job_id])


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
        job["updated"] = time.time()
        return _job_view(job)


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
            "timestamp": time.time(),
        }

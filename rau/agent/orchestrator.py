"""Background job registry + local subagent loop."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from rau.agent.compaction import maybe_compact, provider_summarizer
from rau.agent.danger import classify_tool
from rau.agent.tools import TOOL_SCHEMAS, run_tool
from rau.events import BUS
from rau.identity.store import load_soul
from rau.memory.store import append_diary, append_trace
from rau.providers.base import Message, tool_result_text
from rau.providers.registry import chat_for_slot, load_settings
from rau import state

DEFAULT_MAX_PARALLEL_JOBS = 3
#: Tokens a subagent run may occupy before its early turns are folded into a
#: summary. Sized for the frontier models this slot is meant to hold.
DEFAULT_CONTEXT_BUDGET = 100_000
#: The job the user asked for, plus one layer of children. That is enough to
#: split a question into parts and no more: every extra level multiplies the
#: fan-out, and nesting without a limit is a fork bomb billed by the token.
MAX_JOB_DEPTH = 2
#: How often a parent blocked on its children re-checks its own cancel flag.
CHILD_POLL_SEC = 0.2


@dataclass
class Job:
    """One background goal, possibly a sub-goal of another.

    Cancellation and confirmation live on the job rather than on the module so
    two goals running side by side can never read each other's signals.
    """

    id: str
    goal: str
    #: The job that fanned out into this one; None for work the user asked for.
    parent_id: Optional[str] = None
    #: 1 for a job the user asked for, one more per generation below it.
    depth: int = 1
    cancel: threading.Event = field(default_factory=threading.Event)
    #: Set once this job can no longer change state, so a parent waiting on its
    #: children wakes when they settle instead of polling the state store.
    finished: threading.Event = field(default_factory=threading.Event)
    confirm_ready: threading.Event = field(default_factory=threading.Event)
    confirm_decision: Optional[bool] = None
    #: Set while this job is blocked on the user; None the rest of the time.
    confirm_id: Optional[str] = None
    thread: Optional[threading.Thread] = None


_lock = threading.RLock()
_jobs: Dict[str, Job] = {}


def max_parallel_jobs() -> int:
    return max(
        1,
        int(load_settings().get("max_parallel_jobs") or DEFAULT_MAX_PARALLEL_JOBS),
    )


def start_job(goal: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
    """Begin a background goal, optionally beneath one already running."""
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "reason": "empty_goal", "error": "empty goal"}
    with _lock:
        _reap()
        depth = 1
        if parent_id:
            parent = _jobs.get(parent_id)
            if parent is None:
                return {
                    "ok": False,
                    "reason": "unknown_parent",
                    "error": "unknown parent job",
                    "parent_id": parent_id,
                }
            # A parent cancelled while it was deciding to fan out must not get
            # children: the sweep that killed it has already passed, so they
            # would run on with nobody to stop them or read their answers.
            if not _is_active(parent):
                return {
                    "ok": False,
                    "reason": "parent_finished",
                    "error": "parent job is no longer running",
                    "parent_id": parent_id,
                }
            depth = parent.depth + 1
            if depth > MAX_JOB_DEPTH:
                return {
                    "ok": False,
                    "reason": "too_deep",
                    "error": f"nesting is limited to depth {MAX_JOB_DEPTH}",
                    "parent_id": parent_id,
                }
        # The registry is flat, so this counts the whole tree rather than one
        # level of it: a child is a real provider call and costs what any other
        # job costs. Cap 3 means a parent plus two children, not three each.
        running = [j for j in _jobs.values() if _is_active(j)]
        cap = max_parallel_jobs()
        if len(running) >= cap:
            return {
                "ok": False,
                "reason": "at_capacity",
                "error": f"already running {len(running)} jobs (max {cap})",
                "task": state.get_hard_task(),
                "jobs": state.list_jobs(),
            }
        job = Job(id=str(uuid.uuid4()), goal=goal, parent_id=parent_id, depth=depth)
        _jobs[job.id] = job
        state.create_job(job.id, goal)
        # The tree edges ride along in the snapshot every reader already polls,
        # so a UI can nest the rows without a second endpoint to correlate.
        state.update_job(job.id, parent_id=parent_id, depth=depth)

    # The worker emits progress and confirm requests of its own, so it may not
    # start until this job's opening events are on the bus.
    _emit_hard_task(job, state="running")
    BUS.emit("job_started", id=job.id, goal=goal, parent_id=parent_id, depth=depth)
    threading.Thread(
        target=_job_thread,
        args=(job,),
        daemon=True,
        name=f"rau-job-{job.id[:8]}",
    ).start()
    return {
        "ok": True,
        "id": job.id,
        "goal": goal,
        "parent_id": parent_id,
        "depth": depth,
    }


def spawn_children(parent_id: str, goals: Iterable[str]) -> Dict[str, Any]:
    """Fan `parent_id` out into sub-goals and block until they settle.

    Blocking is the point. The parent asked these questions to get the answers
    back into its own context, and a call that returned ids would let it finish
    first and drop everything its children found.
    """
    with _lock:
        parent = _jobs.get(parent_id)
    if parent is None:
        return {"ok": False, "error": "unknown parent job", "parent_id": parent_id}

    children: List[Job] = []
    refused: List[Dict[str, Any]] = []
    for goal in goals:
        started = start_job(str(goal), parent_id=parent_id)
        if not started.get("ok"):
            refused.append(
                {
                    "goal": goal,
                    "reason": started.get("reason"),
                    "error": started.get("error"),
                }
            )
            continue
        with _lock:
            child = _jobs.get(started["id"])
        if child is not None:
            children.append(child)

    if not children:
        return {"ok": False, "error": "no sub-goal could start", "refused": refused}

    _emit_progress(parent, f"Split into {len(children)} sub-goals")
    for child in children:
        while not (child.finished.is_set() or parent.cancel.is_set()):
            child.finished.wait(timeout=CHILD_POLL_SEC)
    if parent.cancel.is_set():
        # Cancelling the parent already cancelled these, so there is nothing
        # worth reporting to a worker that is being torn down anyway.
        return {"ok": False, "error": "cancelled", "parent_id": parent_id}

    results = []
    for child in children:
        snap = state.get_job(child.id) or {}
        results.append(
            {
                "id": child.id,
                "goal": child.goal,
                "state": snap.get("state") or "unknown",
                "result": snap.get("result") or "",
            }
        )
    return {"ok": True, "children": results, "refused": refused}


def cancel_job(job_id: str) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "error": "unknown job", "id": job_id}
    return {"ok": True, "id": job_id, "cancelled": _cancel(job)}


def cancel_all() -> Dict[str, Any]:
    with _lock:
        jobs = list(_jobs.values())
    # Cancelling a parent takes its subtree with it, so a child reached later in
    # this sweep reports False and is named once, by the call that stopped it.
    return {"ok": True, "cancelled": [j.id for j in jobs if _cancel(j)]}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return state.get_job(job_id)


def list_jobs() -> List[Dict[str, Any]]:
    return state.list_jobs()


def resolve_confirm(approved: bool, confirm_id: Optional[str] = None) -> None:
    """Route a decision to the job that asked for it.

    Without an id — voice shortcuts, older clients — it lands on the oldest
    pending confirm, which is exactly the one the single-slot views show.
    """
    if confirm_id:
        job_id = state.confirm_job_id(confirm_id)
    else:
        pending = state.get_confirm()
        job_id = pending.get("job_id") if pending else None
    if not job_id:
        return
    with _lock:
        job = _jobs.get(job_id)
    if job:
        _decide_confirm(job, approved)


def start_hard_task(goal: str) -> Dict[str, Any]:
    return start_job(goal)


def cancel_hard_task() -> Dict[str, Any]:
    return cancel_all()


def redirect_hard_task(goal: str) -> Dict[str, Any]:
    """Drop everything in flight and pick up `goal` instead.

    The replacement is vetted first: a redirect the face botched into an empty
    goal would otherwise throw away every running job and start nothing.
    """
    if not (goal or "").strip():
        return {"ok": False, "reason": "empty_goal", "error": "empty goal"}
    cancelled = cancel_all()
    started = start_job(goal)
    if not started.get("ok"):
        return started
    return {
        "ok": True,
        "redirected_to": goal,
        "id": started["id"],
        "cancelled": cancelled["cancelled"],
    }


def _is_active(job: Job) -> bool:
    snap = state.get_job(job.id)
    return bool(snap) and snap.get("state") in state.ACTIVE_JOB_STATES


def _reap() -> None:
    """Forget jobs the state store has already aged out."""
    for job_id in [j for j in _jobs if state.get_job(j) is None]:
        _jobs.pop(job_id, None)


def _subtree(root: Job) -> List[Job]:
    """`root` and everything under it, deepest first. Call under the lock."""
    out: List[Job] = []
    for child in [j for j in _jobs.values() if j.parent_id == root.id]:
        out.extend(_subtree(child))
    out.append(root)
    return out


def _cancel(job: Job) -> bool:
    """Stop a live job and everything it spawned. False if nothing was live.

    Children outliving their parent is the failure people find on an invoice:
    the UI shows the task stopped while workers nobody is tracking keep calling
    the provider. So the subtree is claimed in one pass under the lock, and
    `start_job` refuses a parent that is no longer active — a spawn racing the
    sweep is therefore either swept with it or rejected outright.

    Claiming under the lock also keeps a double cancel, or a cancel chasing a
    job that just reported back, from rewriting a settled result and announcing
    a second ending for it.
    """
    with _lock:
        doomed = [j for j in _subtree(job) if _is_active(j)]
        for j in doomed:
            j.cancel.set()
            state.set_confirm(j.id, None)
            state.update_job(j.id, state="cancelled", progress="cancelled by user")
    for j in doomed:
        _decide_confirm(j, False)
        j.finished.set()
        _emit_hard_task(j, state="cancelled")
        BUS.emit("job_done", id=j.id, goal=j.goal, state="cancelled", result="")
    return bool(doomed)


def _decide_confirm(job: Job, approved: bool) -> None:
    job.confirm_decision = bool(approved)
    job.confirm_ready.set()


def _emit_hard_task(job: Job, **fields: Any) -> None:
    """Lifecycle for the single-slot view, which only ever means the top job.

    A child announcing that it started or finished would tell the face and the
    dashboard that the whole hard task had begun or ended, while its parent —
    the goal the user actually named — was still working.
    """
    if job.parent_id is None:
        BUS.emit("hard_task", id=job.id, goal=job.goal, **fields)


def _await_confirm(job: Job, summary: str, timeout: float) -> bool:
    """Block this job until the user confirms/denies or timeout. True if approved."""
    cid = str(uuid.uuid4())
    job.confirm_decision = None
    job.confirm_ready.clear()
    payload = {
        "id": cid,
        "job_id": job.id,
        "summary": summary,
        "timeout": timeout,
        "created": time.time(),
    }
    state.set_confirm(job.id, payload)
    BUS.emit("confirm_request", **payload)
    state.update_job(job.id, state="awaiting_confirm", progress=summary)

    # Also push voice-facing control hint
    state.push_control({"action": "ask_confirm", "summary": summary, "id": cid})

    ok = job.confirm_ready.wait(timeout=timeout)
    state.set_confirm(job.id, None)
    approved = ok and job.confirm_decision is True
    BUS.emit("confirm_result", id=cid, job_id=job.id, approved=approved)
    return approved


def _emit_progress(job: Job, progress: str) -> None:
    BUS.emit("hard_task_progress", id=job.id, progress=progress)
    BUS.emit("job_progress", id=job.id, goal=job.goal, progress=progress)


def _job_thread(job: Job) -> None:
    """
    Outer safety net for the worker thread.

    `_run_subagent` handles its own failures, but it reads settings before
    entering that try block — and anything raised before it (or from a future
    edit above it) would otherwise escape to the thread bootstrap and strand
    the job in `running` forever, with the concurrency slot never released.
    """
    try:
        _run_subagent(job)
    except Exception as e:  # noqa: BLE001 — last line of defence for a thread
        if job.cancel.is_set():
            return
        msg = f"Hard task crashed: {e}"
        state.set_confirm(job.id, None)
        state.update_job(job.id, state="failed", progress="error", result=msg)
        _emit_hard_task(job, state="failed", result=msg)
        BUS.emit("job_failed", id=job.id, goal=job.goal, error=msg)
    finally:
        # However this ended, a parent waiting on this job has its answer.
        job.finished.set()


def _run_subagent(job: Job) -> None:
    settings = load_settings()
    timeout = float(settings.get("confirm_timeout_sec") or 45)
    progress_every = float(settings.get("hard_task_progress_interval_sec") or 25)
    budget = int(settings.get("subagent_context_budget") or DEFAULT_CONTEXT_BUDGET)
    last_progress = time.time()
    goal = job.goal

    try:
        provider, slot = chat_for_slot("subagent")
        soul = load_soul()
        messages = [
            Message(
                role="system",
                content=(
                    soul
                    + "\n\nYou are Rau's silent inner worker. Never address the user directly "
                    "as a separate character. Use tools to accomplish the goal. "
                    "Call finish(summary) when done. Prefer memory_write for lasting notes."
                ),
            ),
            Message(role="user", content=f"Hard task goal:\n{goal}"),
        ]

        final_summary = ""
        summarize = provider_summarizer("dream")
        for step in range(24):
            # Cancellation already wrote the cancelled state and its events.
            if job.cancel.is_set():
                return

            state.update_job(job.id, state="running", progress=f"step {step+1}")
            if time.time() - last_progress >= progress_every:
                _emit_progress(job, f"Still working on: {goal[:120]}")
                last_progress = time.time()

            # Two dozen steps of clamped tool output will outgrow any window.
            # The goal itself lives in the oldest turn, so the front is folded
            # into a briefing rather than dropped — a run that forgets what it
            # was asked to do is worse than one that ran out of room.
            messages = maybe_compact(messages, summarize, budget=budget)

            result = provider.chat(
                messages,
                model=slot.get("model") or "openai/gpt-5.6-sol",
                max_tokens=int(slot.get("max_tokens") or 4096),
                temperature=float(slot.get("temperature") or 0.3),
                tools=TOOL_SCHEMAS,
                effort=str(slot.get("effort") or "high"),
            )

            if result.content or result.tool_calls:
                messages.append(
                    Message(
                        role="assistant",
                        content=result.content,
                        tool_calls=list(result.tool_calls) or None,
                    )
                )

            if not result.tool_calls:
                # no tools — treat content as summary if present
                if result.content:
                    final_summary = result.content
                break

            for tc in result.tool_calls:
                if job.cancel.is_set():
                    return
                needs, summary = classify_tool(tc.name, tc.arguments)
                # A worker is never told its own job id, so the link that binds
                # anything it spawns to itself — and to the cancel that reaches
                # both — travels beside the call rather than through the model.
                if needs:
                    approved = _await_confirm(job, summary or tc.name, timeout)
                    if not approved:
                        tool_result = {
                            "ok": False,
                            "error": "user denied or confirm timed out",
                        }
                    else:
                        state.update_job(
                            job.id, state="running", progress=f"running {tc.name}"
                        )
                        tool_result = run_tool(tc.name, tc.arguments, job_id=job.id)
                else:
                    tool_result = run_tool(tc.name, tc.arguments, job_id=job.id)

                append_trace(
                    "tool",
                    {"name": tc.name, "args": tc.arguments, "result_ok": tool_result.get("ok")},
                )
                _emit_progress(job, f"Inner work: {tc.name}")

                messages.append(
                    Message(
                        role="tool",
                        content=tool_result_text(tool_result),
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

                if tool_result.get("finished"):
                    final_summary = str(tool_result.get("summary") or "")
                    break
            else:
                continue
            break

        if job.cancel.is_set():
            return

        if not final_summary:
            final_summary = "I finished the deep work, but the summary was thin."

        append_diary("task", final_summary, meta={"goal": goal, "id": job.id})
        state.update_job(job.id, state="done", progress="done", result=final_summary)
        _emit_hard_task(job, state="done", result=final_summary)
        BUS.emit("job_done", id=job.id, goal=goal, state="done", result=final_summary)
        # Ask face to weave result. A child's answer is never spoken on its own:
        # it goes back to the parent as a tool result, and the parent's summary
        # is what the user hears.
        if job.parent_id is None:
            state.push_control(
                {
                    "action": "weave_result",
                    "goal": goal,
                    "result": final_summary,
                }
            )
    except Exception as e:
        if job.cancel.is_set():
            return
        msg = f"Hard task failed: {e}"
        append_diary("task_error", msg, meta={"goal": goal})
        state.set_confirm(job.id, None)
        state.update_job(job.id, state="failed", progress="error", result=msg)
        _emit_hard_task(job, state="failed", result=msg)
        BUS.emit("job_failed", id=job.id, goal=goal, error=msg)
        if job.parent_id is None:
            state.push_control({"action": "weave_result", "goal": goal, "result": msg})

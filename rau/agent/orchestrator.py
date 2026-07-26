"""Background job registry + local subagent loop."""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from rau.agent.compaction import maybe_compact, provider_summarizer
from rau.agent.danger import classify_tool
from rau.agent.tools import run_tool
from rau.events import BUS
from rau.identity.store import load_soul
from rau.memory.store import append_diary, append_trace
from rau.providers.base import Message, tool_result_images, tool_result_text
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
MAX_CHILD_GOALS = 8
MAX_GOAL_CHARS = 100_000
_WORKERS = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="rau-worker",
)


class _WorkerHandle:
    """Thread-compatible facade retained for callers while using a real pool."""

    def __init__(self, future: Future[Any]):
        self.future = future

    def join(self, timeout: Optional[float] = None) -> None:
        try:
            self.future.result(timeout=timeout)
        except TimeoutError:
            return

    def is_alive(self) -> bool:
        return not self.future.done()


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
    scheduled_run_id: Optional[str] = None
    permission_policy: str = ""
    resource_profile: str = "balanced"
    budget: Dict[str, Any] = field(default_factory=dict)
    executor: str = "python"
    step_id: Optional[str] = None
    step: Any = None
    completion: Dict[str, Any] = field(default_factory=dict)
    coordinating_children: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    #: Set once this job can no longer change state, so a parent waiting on its
    #: children wakes when they settle instead of polling the state store.
    finished: threading.Event = field(default_factory=threading.Event)
    confirm_ready: threading.Event = field(default_factory=threading.Event)
    confirm_decision: Optional[bool] = None
    #: Set while this job is blocked on the user; None the rest of the time.
    confirm_id: Optional[str] = None
    thread: Optional[_WorkerHandle] = None


_lock = threading.RLock()
_jobs: Dict[str, Job] = {}


def max_parallel_jobs() -> int:
    from rau.resources import current_profile

    try:
        configured = int(
            load_settings().get("max_parallel_jobs")
            or current_profile()["max_parallel_jobs"]
        )
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_PARALLEL_JOBS
    return min(16, max(1, configured))


def _validated_goal(goal: Any) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not isinstance(goal, str):
        return None, {
            "ok": False,
            "reason": "invalid_goal",
            "error": "goal must be a string",
        }
    goal = goal.strip()
    if not goal:
        return None, {"ok": False, "reason": "empty_goal", "error": "empty goal"}
    if len(goal) > MAX_GOAL_CHARS:
        return None, {
            "ok": False,
            "reason": "goal_too_large",
            "error": f"goal exceeds {MAX_GOAL_CHARS} characters",
        }
    return goal, None


def start_job(
    goal: str,
    parent_id: Optional[str] = None,
    *,
    scheduled_run_id: Optional[str] = None,
    permission_policy: str = "",
    resource_profile: str = "balanced",
    budget: Optional[Dict[str, Any]] = None,
    executor: str = "auto",
) -> Dict[str, Any]:
    """Begin a background goal, optionally beneath one already running."""
    from rau.permissions import jobs_allowed

    # A schedule's authority was confirmed when it was created or expanded,
    # and its per-run permission policy still gates every tool below. Global
    # foreground "subagents read-only" mode must not silently disable durable
    # read-only schedules after a restart.
    if not jobs_allowed() and scheduled_run_id is None:
        return {
            "ok": False,
            "reason": "readonly",
            "error": "subagents are in read-only mode — cannot start jobs",
        }
    validated_goal, error = _validated_goal(goal)
    if error is not None:
        return error
    assert validated_goal is not None
    goal = validated_goal
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
            scheduled_run_id = scheduled_run_id or parent.scheduled_run_id
            permission_policy = permission_policy or parent.permission_policy
            resource_profile = resource_profile or parent.resource_profile
            budget = budget or parent.budget
            if executor == "auto":
                executor = parent.executor
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
        # A cancelled job can still be unwinding a provider request. It no
        # longer appears active to the UI, but it continues to consume a worker
        # and possibly provider capacity until its thread actually exits.
        running = [j for j in _jobs.values() if _occupies_slot(j)]
        cap = max_parallel_jobs()
        if len(running) >= cap:
            return {
                "ok": False,
                "reason": "at_capacity",
                "error": f"already running {len(running)} jobs (max {cap})",
                "task": state.get_hard_task(),
                "jobs": state.list_jobs(),
            }
        from rau.agent.executors import select_executor
        from rau.agent.protocol import AgentPlan

        selected_executor = select_executor(goal, executor)
        job = Job(
            id=str(uuid.uuid4()),
            goal=goal,
            parent_id=parent_id,
            depth=depth,
            scheduled_run_id=scheduled_run_id,
            permission_policy=permission_policy,
            resource_profile=resource_profile
            if resource_profile in {"eco", "balanced", "performance"}
            else "balanced",
            budget=dict(budget or {}),
            executor=selected_executor,
        )
        plan = AgentPlan.single(
            job.id,
            goal,
            executor=selected_executor,
            budget=job.budget,
        )
        job.step_id = plan.steps[0].id
        job.step = plan.steps[0]
        _jobs[job.id] = job
        state.create_job(job.id, goal)
        # The tree edges ride along in the snapshot every reader already polls,
        # so a UI can nest the rows without a second endpoint to correlate.
        state.update_job(
            job.id,
            parent_id=parent_id,
            depth=depth,
            scheduled_run_id=scheduled_run_id,
            permission_policy=permission_policy,
            resource_profile=job.resource_profile,
            budget=job.budget,
            executor=selected_executor,
            plan=plan.to_dict(),
            lifecycle_state="planning",
            lease_owner=f"{os.getpid()}:{job.id}",
            lease_expires=time.time() + 120.0,
        )
        if state.durable_enabled():
            from rau.control import control_store

            control_store.upsert_step(plan.steps[0].to_dict())
    # The worker emits progress and confirm requests of its own, so it may not
    # start until this job's opening events are on the bus.
    _emit_hard_task(job, state="running")
    BUS.emit("job_started", id=job.id, goal=goal, parent_id=parent_id, depth=depth)
    job.thread = _WorkerHandle(_WORKERS.submit(_job_thread, job))
    return {
        "ok": True,
        "id": job.id,
        "goal": goal,
        "parent_id": parent_id,
        "depth": depth,
        "scheduled_run_id": scheduled_run_id,
        "resource_profile": job.resource_profile,
        "executor": selected_executor,
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

    if isinstance(goals, (str, bytes)):
        return {"ok": False, "error": "goals must be an array of strings"}
    requested = list(goals)
    if not requested:
        return {"ok": False, "error": "at least one sub-goal is required"}
    if len(requested) > MAX_CHILD_GOALS:
        return {
            "ok": False,
            "error": f"at most {MAX_CHILD_GOALS} sub-goals may be spawned at once",
        }

    children: List[Job] = []
    refused: List[Dict[str, Any]] = []
    parent.coordinating_children = True
    for goal in requested:
        if not isinstance(goal, str):
            refused.append(
                {
                    "goal": repr(goal)[:200],
                    "reason": "invalid_goal",
                    "error": "sub-goal must be a string",
                }
            )
            continue
        started = start_job(goal, parent_id=parent_id)
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
        parent.coordinating_children = False
        return {"ok": False, "error": "no sub-goal could start", "refused": refused}

    _emit_progress(parent, f"Split into {len(children)} sub-goals")
    for child in children:
        while not (child.finished.is_set() or parent.cancel.is_set()):
            child.finished.wait(timeout=CHILD_POLL_SEC)
    parent.coordinating_children = False
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
    resolved_id = confirm_id
    if confirm_id:
        job_id = state.confirm_job_id(confirm_id)
    else:
        pending = state.get_confirm()
        job_id = pending.get("job_id") if pending else None
        resolved_id = pending.get("id") if pending else None
    if not job_id:
        return
    if resolved_id and state.durable_enabled():
        from rau.control import control_store

        if not control_store.decide_confirmation(resolved_id, approved):
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
    from rau.permissions import jobs_allowed

    if not jobs_allowed():
        return {
            "ok": False,
            "reason": "readonly",
            "error": "subagents are in read-only mode — cannot redirect jobs",
        }
    validated_goal, error = _validated_goal(goal)
    if error is not None:
        return error
    assert validated_goal is not None
    goal = validated_goal
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
    return snap is not None and snap.get("state") in state.ACTIVE_JOB_STATES


def _occupies_slot(job: Job) -> bool:
    """Whether a job still owns execution capacity, including cancel unwind."""
    snap = state.get_job(job.id)
    if job.coordinating_children:
        return False
    if snap is not None and snap.get("state") == "awaiting_confirm":
        # A parked confirmation owns no provider/tool capacity. Its lightweight
        # waiter may remain alive without starving unrelated scheduled work.
        return False
    if _is_active(job):
        return True
    return bool(job.thread and job.thread.is_alive())


def _reap() -> None:
    """Forget jobs the state store has already aged out."""
    for job_id in [
        j for j, job in _jobs.items() if state.get_job(j) is None and not _occupies_slot(job)
    ]:
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


def _await_confirm(
    job: Job,
    summary: str,
    timeout: float,
    *,
    tool: str = "",
    arguments: Optional[Dict[str, Any]] = None,
) -> bool:
    """Block this job until the user confirms/denies or timeout. True if approved."""
    cid = str(uuid.uuid4())
    job.confirm_decision = None
    job.confirm_ready.clear()
    payload = {
        "id": cid,
        "job_id": job.id,
        "summary": summary,
        "tool": tool,
        "arguments": arguments or {},
        "timeout": timeout,
        "created": time.time(),
        "expires": time.time() + timeout,
    }
    state.set_confirm(job.id, payload)
    BUS.emit("confirm_request", **payload)
    state.update_job(
        job.id,
        state="awaiting_confirm",
        progress=summary,
        lease_owner=None,
        lease_expires=None,
    )

    # Also push voice-facing control hint
    state.push_control({"action": "ask_confirm", "summary": summary, "id": cid})

    ok = job.confirm_ready.wait(timeout=timeout)
    state.set_confirm(job.id, None)
    approved = ok and job.confirm_decision is True
    if state.durable_enabled() and not ok:
        from rau.control import control_store

        control_store.decide_confirmation(cid, False)
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
    _renew_job_lease(job)
    _update_step(job, state_name="running", attempt=1)
    try:
        from rau.agent.executors import get_executor

        runner = _run_pi_subagent if job.executor == "pi" else _run_subagent
        get_executor(job.executor).start(job.step, runner=lambda: runner(job))
    except Exception as e:  # noqa: BLE001 — last line of defence for a thread
        if job.cancel.is_set():
            return
        msg = f"Hard task crashed: {e}"
        state.set_confirm(job.id, None)
        state.update_job(job.id, state="failed", progress="error", result=msg)
        _emit_hard_task(job, state="failed", result=msg)
        BUS.emit("job_failed", id=job.id, goal=job.goal, error=msg)
    finally:
        snapshot = state.get_job(job.id) or {}
        if snapshot.get("state") in state.ACTIVE_JOB_STATES:
            if job.cancel.is_set():
                state.set_confirm(job.id, None)
                state.update_job(
                    job.id, state="cancelled", progress="cancelled", result=""
                )
                _emit_hard_task(job, state="cancelled")
                BUS.emit(
                    "job_done",
                    id=job.id,
                    goal=job.goal,
                    state="cancelled",
                    result="",
                )
            else:
                msg = "Hard task failed: worker exited without a terminal result"
                state.set_confirm(job.id, None)
                state.update_job(
                    job.id, state="failed", progress="error", result=msg
                )
                _emit_hard_task(job, state="failed", result=msg)
                BUS.emit("job_failed", id=job.id, goal=job.goal, error=msg)
        # However this ended, a parent waiting on this job has its answer.
        settled = state.get_job(job.id) or {}
        final_state = {
            "done": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(str(settled.get("state") or ""), "interrupted")
        _update_step(
            job,
            state_name=final_state,
            result={
                "summary": str(settled.get("result") or ""),
                "outcome": final_state,
                **job.completion,
            },
            terminal_reason=str(settled.get("terminal_reason") or ""),
        )
        if state.durable_enabled():
            from rau.control import control_store

            control_store.release_job_lease(job.id)
        job.finished.set()


def _run_subagent(job: Job) -> None:
    settings = load_settings()
    timeout = _bounded_number(settings.get("confirm_timeout_sec"), 45.0, 0.1, 600.0)
    if job.scheduled_run_id:
        timeout = 24 * 3600.0
    progress_every = _bounded_number(
        settings.get("hard_task_progress_interval_sec"), 25.0, 0.1, 3600.0
    )
    budget = int(
        _bounded_number(
            settings.get("subagent_context_budget"),
            float(DEFAULT_CONTEXT_BUDGET),
            1000.0,
            2_000_000.0,
        )
    )
    last_progress = time.time()
    goal = job.goal
    max_steps = max(1, min(64, int(job.budget.get("max_turns") or 24)))
    max_runtime = max(
        60.0, min(24 * 3600.0, float(job.budget.get("max_runtime_sec") or 3600))
    )
    deadline = time.monotonic() + max_runtime

    try:
        provider, slot = chat_for_slot("subagent")
        from rau.agent.executors import tools_for_goal

        step_tools = tools_for_goal(goal)
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
        exhausted = True
        for step in range(max_steps):
            # Cancellation already wrote the cancelled state and its events.
            if job.cancel.is_set():
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"subagent runtime budget of {max_runtime:g}s exhausted")

            _renew_job_lease(job)
            state.update_job(job.id, state="running", progress=f"step {step+1}")
            if time.time() - last_progress >= progress_every:
                _emit_progress(job, f"Still working on: {goal[:120]}")
                last_progress = time.time()

            # Two dozen steps of clamped tool output will outgrow any window.
            # The goal itself lives in the oldest turn, so the front is folded
            # into a briefing rather than dropped — a run that forgets what it
            # was asked to do is worse than one that ran out of room.
            messages = maybe_compact(messages, summarize, budget=budget)

            max_tokens = int(slot.get("max_tokens") or 4096)
            from rau.agent.executors import routed_effort
            from rau.resources import profile_policy

            effort = routed_effort(
                goal,
                configured=str(slot.get("effort") or "medium"),
                attempt=int(job.budget.get("attempt") or 1),
                profile=job.resource_profile,
            )
            worker_limit = int(
                profile_policy(job.resource_profile)["worker_max_tokens"]
            )
            max_tokens = min(max_tokens, worker_limit)
            if job.resource_profile == "eco":
                max_tokens = min(max_tokens, 2048)
            elif job.resource_profile == "performance":
                max_tokens = min(8192, max(max_tokens, 4096))
            result = provider.chat(
                messages,
                model=slot.get("model") or "openai/gpt-5.6-sol",
                max_tokens=max_tokens,
                temperature=float(slot.get("temperature") or 0.3),
                tools=step_tools,
                effort=effort,
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
                else:
                    raise RuntimeError("provider returned an empty response")
                exhausted = False
                break

            for tc in result.tool_calls:
                if job.cancel.is_set():
                    return
                arguments = (
                    tc.arguments
                    if isinstance(tc.arguments, dict)
                    else {"_raw": tc.arguments}
                )
                from rau.permissions import deny_result

                decision = _job_tool_decision(job, tc.name, arguments)
                needs, summary = classify_tool(tc.name, arguments)
                # A worker is never told its own job id, so the link that binds
                # anything it spawns to itself — and to the cancel that reaches
                # both — travels beside the call rather than through the model.
                if decision == "deny":
                    tool_result = deny_result(tc.name)
                elif decision == "confirm":
                    approved = _await_confirm(
                        job,
                        summary or tc.name,
                        timeout,
                        tool=tc.name,
                        arguments=arguments,
                    )
                    if not approved:
                        tool_result = {
                            "ok": False,
                            "error": "user denied or confirm timed out",
                        }
                    else:
                        _renew_job_lease(job)
                        state.update_job(
                            job.id, state="running", progress=f"running {tc.name}"
                        )
                        approved_arguments = dict(arguments)
                        if tc.name in {"computer_act", "cua_action"}:
                            # This marker is injected only after the exact
                            # persisted tool arguments were approved. It is
                            # absent from the public schema, so a model cannot
                            # self-authorize a secure target.
                            approved_arguments["_interactive_confirmed"] = True
                        tool_result = _execute_tool(
                            job,
                            tc.id,
                            tc.name,
                            approved_arguments,
                            needs,
                        )
                else:
                    # allow — including bypass of tools that would need confirm
                    if needs:
                        state.update_job(
                            job.id, state="running", progress=f"running {tc.name}"
                        )
                    tool_result = _execute_tool(
                        job, tc.id, tc.name, arguments, needs
                    )

                if job.cancel.is_set():
                    return
                if tool_result.get("finished"):
                    completion = tool_result.get("completion")
                    validation_error = _completion_validation_error(completion)
                    if validation_error:
                        tool_result = {
                            "ok": False,
                            "finished": False,
                            "error": validation_error,
                            "revision_required": True,
                        }
                        _update_step(
                            job,
                            state_name="running",
                            attempt=step + 2,
                            strategy=(
                                f"revision {step + 2}: gather explicit evidence "
                                f"after verifier rejection: {validation_error}"
                            ),
                        )

                append_trace(
                    "tool",
                    {
                        "name": tc.name,
                        "args": _trace_arguments(arguments),
                        "result_ok": tool_result.get("ok"),
                    },
                )
                _emit_progress(job, f"Inner work: {tc.name}")

                images = tool_result_images(tool_result)
                messages.append(
                    Message(
                        role="tool",
                        content=tool_result_text(tool_result),
                        tool_call_id=tc.id,
                        name=tc.name,
                        images=images or None,
                    )
                )

                if tool_result.get("finished"):
                    final_summary = str(tool_result.get("summary") or "")
                    completion = tool_result.get("completion")
                    if isinstance(completion, dict):
                        job.completion = dict(completion)
                    if not final_summary.strip():
                        raise RuntimeError("finish requires a non-empty summary")
                    exhausted = False
                    break
            else:
                continue
            break

        if job.cancel.is_set():
            return

        if exhausted:
            raise RuntimeError(f"subagent step budget of {max_steps} exhausted")
        if not final_summary:
            raise RuntimeError("subagent finished without a summary")

        state.update_job(
            job.id,
            state="running",
            lifecycle_state="verifying",
            progress="verifying result",
        )
        _update_step(
            job,
            state_name="verifying",
            evidence=[
                {"kind": "completion_summary", "present": True},
                *[
                    {"kind": "verification", "detail": item}
                    for item in job.completion.get("verification", [])
                ],
            ],
        )
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


def _bounded_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    if not minimum <= parsed <= maximum:
        return default
    return parsed


def _job_tool_decision(
    job: Job, name: str, arguments: Dict[str, Any]
) -> str:
    """Scheduled authority is explicit and never inherits global bypass."""
    from rau.permissions import is_readonly_allowed, tool_decision

    if not job.scheduled_run_id:
        return tool_decision("subagents", name, arguments)
    if job.permission_policy == "readonly":
        return "allow" if is_readonly_allowed(name, arguments) else "deny"
    needs, _ = classify_tool(name, arguments)
    return "confirm" if needs else "allow"


def _renew_job_lease(job: Job) -> None:
    state.update_job(
        job.id,
        lease_owner=f"{os.getpid()}:{job.id}",
        lease_expires=time.time() + 120.0,
    )


def _execute_tool(
    job: Job,
    call_id: str,
    name: str,
    arguments: Dict[str, Any],
    mutation: bool,
) -> Dict[str, Any]:
    """Execute once across retries/restarts, preserving uncertain effects."""
    if not state.durable_enabled():
        return run_tool(name, arguments, job_id=job.id, cancel=job.cancel)
    from rau.control import control_store

    key = f"{job.id}:{job.step_id or 'step'}:{call_id or name}"
    claim = control_store.claim_idempotency(
        key,
        f"tool:{name}",
        {"name": name, "arguments": arguments},
    )
    status = str(claim.get("status") or "")
    if status in {"completed", "failed"}:
        prior = claim.get("result")
        if isinstance(prior, dict):
            return dict(prior)
        return {
            "ok": status == "completed",
            "result" if status == "completed" else "error": prior,
        }
    if status in {"in_progress", "unknown_effect"}:
        _update_step(job, state_name="awaiting_confirm", effect_state="unknown")
        return {
            "ok": False,
            "error": "unknown_effect: this external action may already have occurred",
            "unknown_effect": True,
            "requires_review": True,
        }
    if status == "conflict":
        return {
            "ok": False,
            "error": "idempotency key was reused with different arguments",
        }

    try:
        result = run_tool(name, arguments, job_id=job.id, cancel=job.cancel)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    uncertain = mutation and not bool(result.get("ok"))
    disposition = (
        "unknown_effect"
        if uncertain
        else ("completed" if result.get("ok") else "failed")
    )
    control_store.settle_idempotency(key, disposition, result)
    if uncertain:
        _update_step(job, state_name="awaiting_confirm", effect_state="unknown")
        result = {
            **result,
            "unknown_effect": True,
            "requires_review": True,
        }
    return result


def _completion_validation_error(completion: Any) -> str:
    if not isinstance(completion, dict):
        return "finish must provide the structured completion contract"
    summary = str(completion.get("summary") or "").strip()
    if not summary:
        return "completion summary is required"
    outcome = str(completion.get("outcome") or "completed")
    if outcome in {"failed", "blocked"}:
        blockers = completion.get("blockers") or []
        detail = "; ".join(str(item) for item in blockers[:3])
        raise RuntimeError(detail or summary)
    mutations = completion.get("mutations") or []
    verification = completion.get("verification") or []
    if mutations and not verification:
        return "mutations were reported without verification evidence"
    return ""


def _trace_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Keep tool traces useful without persisting model-supplied payloads."""
    sensitive = {
        "content",
        "text",
        "old_string",
        "new_string",
        "tools",
        "command",
        "cmd",
        "password",
        "token",
        "api_key",
    }
    traced: Dict[str, Any] = {}
    for key, value in arguments.items():
        if key.lower() in sensitive:
            size = len(value) if hasattr(value, "__len__") else None
            traced[key] = f"<redacted{f':{size}' if size is not None else ''}>"
        elif isinstance(value, str):
            traced[key] = value[:300]
        elif isinstance(value, (int, float, bool)) or value is None:
            traced[key] = value
        else:
            traced[key] = f"<{type(value).__name__}>"
    return traced


def _update_step(
    job: Job,
    *,
    state_name: str,
    result: Optional[Dict[str, Any]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    attempt: Optional[int] = None,
    terminal_reason: str = "",
    effect_state: Optional[str] = None,
    strategy: Optional[str] = None,
) -> None:
    if not state.durable_enabled() or not job.step_id:
        return
    from rau.control import control_store

    current = control_store.list_steps(job.id)
    step = next((item for item in current if item["id"] == job.step_id), None)
    if step is None:
        return
    step["state"] = state_name
    step["updated"] = time.time()
    if result is not None:
        step["result"] = result
    if evidence is not None:
        step["evidence"] = evidence
    if attempt is not None:
        step["attempt"] = attempt
    if terminal_reason:
        step["terminal_reason"] = terminal_reason
    if effect_state is not None:
        step["effect_state"] = effect_state
    if strategy is not None:
        step["strategy"] = strategy
    control_store.upsert_step(step)


def _run_pi_subagent(job: Job) -> None:
    """Project a supervised Pi run onto Rau's durable job lifecycle."""
    import os

    from rau.paths import ROOT
    from rau.pi import ConfirmRequest, RunSpec
    from rau.pi.supervisor import PI_SUPERVISOR

    goal = job.goal
    try:
        client = PI_SUPERVISOR.ensure_running()
        settings = load_settings()
        pi_provider = str(
            os.environ.get("PI_PROVIDER")
            or settings.get("pi_provider")
            or ""
        ).strip()
        pi_model = str(
            os.environ.get("PI_MODEL")
            or settings.get("pi_model")
            or ""
        ).strip()
        if not pi_provider or not pi_model:
            raise RuntimeError(
                "Pi executor requires PI_PROVIDER and PI_MODEL (or matching settings)"
            )

        def progress(line: str) -> None:
            if job.cancel.is_set():
                return
            _renew_job_lease(job)
            state.update_job(
                job.id,
                state="running",
                lifecycle_state="running",
                progress=line[:500] or "Pi working",
            )
            _emit_progress(job, line[:500] or "Pi working")

        def confirm(request: ConfirmRequest) -> bool:
            return _await_confirm(
                job,
                request.summary or request.tool,
                24 * 3600.0 if job.scheduled_run_id else 45.0,
                tool=request.tool,
                arguments=request.input,
            )

        max_turns = max(1, min(64, int(job.budget.get("max_turns") or 24)))
        runtime_ms = int(
            max(
                60.0,
                min(
                    24 * 3600.0,
                    float(job.budget.get("max_runtime_sec") or 3600),
                ),
            )
            * 1000
        )
        spec = RunSpec(
            goal=goal,
            cwd=str(ROOT),
            provider=pi_provider,
            model=pi_model,
            system_prompt=(
                load_soul()
                + "\n\nYou are Rau's silent coding worker. Complete the goal, "
                "verify it, then report outcome, artifacts, mutations, verification, "
                "blockers, and remaining risks."
            ),
            max_turns=max_turns,
            run_timeout_ms=runtime_ms,
            confirm_timeout_ms=24 * 3600 * 1000
            if job.scheduled_run_id
            else 45_000,
        )
        result = client.run(
            spec,
            on_progress=progress,
            on_confirm=confirm,
            cancel=job.cancel,
        )
        PI_SUPERVISOR.touch()
        if job.cancel.is_set() or result.state == "cancelled":
            return
        if not result.ok:
            raise RuntimeError(result.error or result.result or "Pi worker failed")
        summary = result.result.strip()
        if not summary:
            raise RuntimeError("Pi worker finished without a summary")
        job.completion = {
            **result.completion,
            "pi_session_path": result.session_path,
        }
        state.update_job(
            job.id,
            state="running",
            lifecycle_state="verifying",
            progress="verifying Pi result",
        )
        _update_step(
            job,
            state_name="verifying",
            evidence=[{"kind": "pi_completion", "present": True}],
        )
        append_diary(
            "task",
            summary,
            meta={"goal": goal, "id": job.id, "executor": "pi"},
        )
        state.update_job(job.id, state="done", progress="done", result=summary)
        _emit_hard_task(job, state="done", result=summary)
        BUS.emit("job_done", id=job.id, goal=goal, state="done", result=summary)
        if job.parent_id is None:
            state.push_control(
                {"action": "weave_result", "goal": goal, "result": summary}
            )
    except Exception as exc:  # noqa: BLE001
        if job.cancel.is_set():
            return
        message = f"Hard task failed: {exc}"
        append_diary(
            "task_error", message, meta={"goal": goal, "executor": "pi"}
        )
        state.update_job(job.id, state="failed", progress="error", result=message)
        _emit_hard_task(job, state="failed", result=message)
        BUS.emit("job_failed", id=job.id, goal=goal, error=message)

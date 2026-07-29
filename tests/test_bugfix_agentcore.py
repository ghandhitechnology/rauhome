"""Regression tests for agent-orchestration-core bugfixes.

Covers: child resource-profile inheritance, fan-out slot-flag hygiene,
step-runner contract dispatch, pi aggregate turn-budget accounting, the
job state a timed-out or answered confirmation leaves behind, the panels
note on a finished job's summary, cancel-vs-done event ordering, retry
classification of budget exhaustion, pi confirm timeouts, spawn_children
deadlines, durable confirmation settling, deny-only stale confirm-id
fallback, and prompt cancel_all unwinding.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau import state  # noqa: E402
from rau.agent import orchestrator  # noqa: E402
from rau.control import control_store  # noqa: E402
from rau.events import BUS  # noqa: E402
from rau.pi.client import PiSidecarError, RunResult  # noqa: E402
from rau.providers.base import ChatResult, ToolCall  # noqa: E402


def _quick(job: orchestrator.Job) -> str:
    """One-argument stand-in runner: settle the job without any provider."""
    state.update_job(job.id, state="done", progress="done", result="ok")
    return "ok"


class ResourceProfileInheritanceTests(unittest.TestCase):
    def tearDown(self) -> None:
        orchestrator.cancel_all()
        with orchestrator._lock:
            jobs = list(orchestrator._jobs.values())
        for job in jobs:
            if job.thread is not None:
                job.thread.join(timeout=2)

    def test_child_inherits_parent_profile_and_default_stays_balanced(self) -> None:
        with (
            patch.object(orchestrator, "_run_subagent", _quick),
            patch.object(orchestrator, "max_parallel_jobs", return_value=5),
            patch.object(orchestrator, "append_diary"),
            patch.object(orchestrator, "append_trace"),
        ):
            parent = orchestrator.start_job("parent goal", resource_profile="eco")
            self.assertTrue(parent["ok"], str(parent))
            child = orchestrator.start_job("child goal", parent_id=parent["id"])
            self.assertTrue(child["ok"], str(child))
            top = orchestrator.start_job("top goal")
            self.assertTrue(top["ok"], str(top))
            with orchestrator._lock:
                child_job = orchestrator._jobs[child["id"]]
                top_job = orchestrator._jobs[top["id"]]
            self.assertEqual(child_job.resource_profile, "eco")
            self.assertEqual(top_job.resource_profile, "balanced")
            snap = state.get_job(child["id"]) or {}
            self.assertEqual(snap.get("resource_profile"), "eco")


class SpawnChildrenFlagTests(unittest.TestCase):
    def tearDown(self) -> None:
        orchestrator.cancel_all()
        with orchestrator._lock:
            jobs = list(orchestrator._jobs.values())
        for job in jobs:
            if job.thread is not None:
                job.thread.join(timeout=2)

    def test_coordinating_flag_survives_a_fanout_exception(self) -> None:
        with (
            patch.object(orchestrator, "_run_subagent", _quick),
            patch.object(orchestrator, "append_diary"),
            patch.object(orchestrator, "append_trace"),
        ):
            parent = orchestrator.start_job("parent goal")
            self.assertTrue(parent["ok"], str(parent))
        with orchestrator._lock:
            parent_job = orchestrator._jobs[parent["id"]]
        with (
            patch.object(
                orchestrator, "start_job", side_effect=RuntimeError("planner exploded")
            ),
            self.assertRaisesRegex(RuntimeError, "planner exploded"),
        ):
            orchestrator.spawn_children(parent["id"], ["child goal"])
        self.assertFalse(parent_job.coordinating_children)


class StepRunnerContractTests(unittest.TestCase):
    def test_internal_typeerror_does_not_rerun_the_whole_step(self) -> None:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        calls: list = []

        def new_style(job, *, step_goal=None, dependency_results=None, finalize=True):
            calls.append(step_goal)
            raise TypeError("inner() got an unexpected keyword argument 'bogus'")

        with self.assertRaisesRegex(TypeError, "unexpected keyword"):
            orchestrator._invoke_step_runner(new_style, job, "goal", {})
        self.assertEqual(calls, ["goal"], "runner must execute exactly once")

    def test_legacy_one_argument_adapters_still_work(self) -> None:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        calls: list = []

        def legacy(job):
            calls.append(job.id)
            return "done"

        result = orchestrator._invoke_step_runner(legacy, job, "goal", {})
        self.assertEqual(result, "done")
        self.assertEqual(calls, [job.id])

    def test_mock_wrapped_legacy_runner_still_falls_back(self) -> None:
        """A MagicMock side_effect accepts any signature yet wraps one arg."""
        from unittest.mock import MagicMock

        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        calls: list = []

        def hold(job):
            calls.append(job.id)
            return "ok"

        result = orchestrator._invoke_step_runner(
            MagicMock(side_effect=hold), job, "goal", {}
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls, [job.id])


class _FakePiClient:
    def __init__(self, snapshot):
        self.spec = None
        self._snapshot = snapshot

    def run(self, spec, **_kwargs):
        self.spec = spec
        return RunResult(id="run-1", state="done", result="fixed it")

    def snapshot(self, run_id):
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


class _FakePiSupervisor:
    def __init__(self, client):
        self._client = client

    def ensure_running(self):
        return self._client

    def touch(self) -> None:
        return None


class PiTurnBudgetTests(unittest.TestCase):
    def _run_pi(self, snapshot, budget_turns=10):
        job = orchestrator.Job(
            id=str(uuid.uuid4()),
            goal="fix the bug",
            budget={"max_turns": budget_turns},
        )
        state.create_job(job.id, job.goal)
        client = _FakePiClient(snapshot)
        with (
            patch("rau.pi.supervisor.PI_SUPERVISOR", _FakePiSupervisor(client)),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.dict(os.environ, {"PI_PROVIDER": "p", "PI_MODEL": "m"}),
        ):
            summary = orchestrator._run_pi_subagent(job, finalize=False)
        return job, client, summary

    def test_unspent_reserved_turns_are_refunded(self) -> None:
        job, client, summary = self._run_pi({"turns": 3})
        self.assertEqual(summary, "fixed it")
        self.assertEqual(client.spec.max_turns, 10)
        self.assertEqual(
            job.turns_used, 3, "later plan steps must inherit the unspent budget"
        )

    def test_unknown_spend_keeps_the_full_charge(self) -> None:
        job, _client, summary = self._run_pi(PiSidecarError("sidecar gone"))
        self.assertEqual(summary, "fixed it")
        self.assertEqual(job.turns_used, 10)


class ConfirmStateTests(unittest.TestCase):
    def test_timeout_leaves_the_job_running_not_parked(self) -> None:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        state.create_job(job.id, job.goal)
        approved = orchestrator._await_confirm(job, "Do the thing", 0.2)
        self.assertFalse(approved)
        snap = state.get_job(job.id) or {}
        self.assertEqual(snap.get("state"), "running")
        self.assertIsNone(snap.get("confirm"))

    def test_approval_leaves_the_job_running_not_parked(self) -> None:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        state.create_job(job.id, job.goal)
        with orchestrator._lock:
            orchestrator._jobs[job.id] = job
        decider = threading.Timer(0.1, lambda: orchestrator.resolve_confirm(True))
        decider.start()
        try:
            approved = orchestrator._await_confirm(job, "Do the thing", 5.0)
        finally:
            decider.join()
            with orchestrator._lock:
                orchestrator._jobs.pop(job.id, None)
        self.assertTrue(approved)
        snap = state.get_job(job.id) or {}
        self.assertEqual(snap.get("state"), "running")


def _join_all_jobs() -> None:
    orchestrator.cancel_all()
    with orchestrator._lock:
        jobs = list(orchestrator._jobs.values())
    for job in jobs:
        if job.thread is not None:
            job.thread.join(timeout=2)


class PanelsNoteTests(unittest.TestCase):
    """The finished job's summary must name what it put on the wall (A1)."""

    def setUp(self) -> None:
        # Same isolation as test_room_life: the wall is rows in a process-wide
        # store, so point it at a throwaway database for the test.
        self._tmp = tempfile.TemporaryDirectory(prefix="rau-panels-")
        self._real_path = control_store.path
        self._real_ready = control_store._ready  # noqa: SLF001
        control_store.path = Path(self._tmp.name) / "control.db"
        control_store._ready = False  # noqa: SLF001 — forces re-initialize
        control_store.initialize()

    def tearDown(self) -> None:
        _join_all_jobs()
        control_store.path = self._real_path
        control_store._ready = self._real_ready  # noqa: SLF001
        self._tmp.cleanup()

    def test_final_summary_names_what_the_job_put_on_the_wall(self) -> None:
        from rau.agent.tools import run_tool

        def runner(job: orchestrator.Job) -> str:
            run_tool(
                "show_panel",
                {"title": "Wall Report", "html": "<p>1</p>"},
                job_id=job.id,
            )
            return "Counted everything."

        with (
            patch.object(orchestrator, "_run_subagent", runner),
            patch.object(orchestrator, "append_diary"),
            patch.object(orchestrator, "append_trace"),
        ):
            started = orchestrator.start_job("count and show")
            self.assertTrue(started["ok"], str(started))
            with orchestrator._lock:
                job = orchestrator._jobs[started["id"]]
            job.thread.join(timeout=5)
        snap = state.get_job(started["id"]) or {}
        self.assertEqual(snap.get("state"), "done")
        self.assertIn("Counted everything.", snap.get("result") or "")
        self.assertIn("Wall Report", snap.get("result") or "")


class NonDurableToolFailureTests(unittest.TestCase):
    def test_tool_exception_becomes_a_model_visible_error(self) -> None:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        with (
            patch.object(state, "durable_enabled", return_value=False),
            patch.object(
                orchestrator, "run_tool", side_effect=RuntimeError("tool exploded")
            ),
        ):
            result = orchestrator._execute_tool(job, "call-1", "memory_read", {}, False)
        self.assertFalse(result["ok"])
        self.assertIn("tool exploded", result["error"])


class CancelBeforeDoneTests(unittest.TestCase):
    """A cancel landing during finalization must not see done events (A5)."""

    def tearDown(self) -> None:
        _join_all_jobs()

    def test_cancel_during_finalization_emits_no_done(self) -> None:
        events: list = []
        holder: dict = {}

        def capture(event: dict) -> None:
            events.append(event)

        def runner(job: orchestrator.Job) -> str:
            holder["job"] = job
            return "ok"

        def trip_cancel(job_id: str, summary: str) -> str:
            holder["job"].cancel.set()
            return summary

        BUS.on("job_done", capture)
        BUS.on("hard_task", capture)
        try:
            with (
                patch.object(orchestrator, "_run_subagent", runner),
                patch.object(
                    orchestrator, "_with_panels_note", side_effect=trip_cancel
                ),
                patch.object(orchestrator, "append_diary"),
                patch.object(orchestrator, "append_trace"),
            ):
                started = orchestrator.start_job("finish then cancel")
                self.assertTrue(started["ok"], str(started))
                with orchestrator._lock:
                    job = orchestrator._jobs[started["id"]]
                job.thread.join(timeout=5)
        finally:
            BUS.off("job_done", capture)
            BUS.off("hard_task", capture)
        self.assertFalse(
            [e for e in events if e.get("state") == "done"],
            f"done events emitted after cancel: {events}",
        )


class FinishContractAttemptTests(unittest.TestCase):
    """A rejected finish contract must not rewrite the plan attempt (A6)."""

    def test_failed_finish_contract_leaves_attempt_alone(self) -> None:
        class FinishThenDone:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, *_args: object, **_kwargs: object) -> ChatResult:
                self.calls += 1
                if self.calls == 1:
                    return ChatResult(
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="t1",
                                name="finish",
                                arguments={
                                    "summary": "did it",
                                    "mutations": ["wrote a file"],
                                },
                            )
                        ],
                    )
                return ChatResult(content="all done")

        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        state.create_job(job.id, job.goal)
        with (
            patch.object(
                orchestrator,
                "chat_for_slot",
                return_value=(FinishThenDone(), {"model": "test"}),
            ),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.object(
                orchestrator, "provider_summarizer", return_value=lambda _x: "s"
            ),
            patch.object(
                orchestrator,
                "maybe_compact",
                side_effect=lambda msgs, *_a, **_k: list(msgs),
            ),
            patch.object(orchestrator, "_job_tool_decision", return_value="allow"),
            patch.object(orchestrator, "_update_step") as update_step,
            patch.object(orchestrator, "append_trace"),
            patch.object(orchestrator, "append_diary"),
        ):
            summary = orchestrator._run_subagent(job, finalize=False)
        self.assertEqual(summary, "all done")
        revision_calls = [
            call
            for call in update_step.call_args_list
            if call.kwargs.get("state_name") == "running"
        ]
        self.assertTrue(revision_calls, "the rejection never reached _update_step")
        for call in revision_calls:
            self.assertNotIn(
                "attempt",
                call.kwargs,
                "the provider-turn counter must not pollute the plan attempt",
            )
            self.assertIn("verifier rejection", call.kwargs.get("strategy") or "")


class RetryableBudgetTests(unittest.TestCase):
    def test_budget_exhaustion_is_not_retryable(self) -> None:
        self.assertFalse(
            orchestrator._retryable_failure(
                "aggregate provider turn budget of 24 exhausted"
            )
        )
        self.assertFalse(
            orchestrator._retryable_failure("subagent step budget of 24 exhausted")
        )
        self.assertFalse(
            orchestrator._retryable_failure("subagent runtime budget of 60s exhausted")
        )

    def test_transient_provider_errors_stay_retryable(self) -> None:
        self.assertTrue(orchestrator._retryable_failure("provider timeout"))
        self.assertTrue(orchestrator._retryable_failure("connection reset by peer"))

    def test_resource_exhausted_rate_limit_stays_retryable(self) -> None:
        # Only the specific budget phrases above are permanent; a transient
        # RESOURCE_EXHAUSTED-style 429 must not be caught by them.
        self.assertTrue(
            orchestrator._retryable_failure(
                "provider 429 RESOURCE_EXHAUSTED: rate limit exceeded"
            )
        )


class _ConfirmCapturingPiClient(_FakePiClient):
    def run(self, spec, **kwargs):
        self.spec = spec
        on_confirm = kwargs.get("on_confirm")
        if on_confirm is not None:
            on_confirm(SimpleNamespace(summary="sure?", tool="bash", input={}))
        return RunResult(id="run-1", state="done", result="fixed it")


class PiConfirmTimeoutTests(unittest.TestCase):
    """The pi path honors confirm_timeout_sec like _run_subagent does (A8)."""

    def _run_pi(self, *, scheduled: bool, settings: dict) -> tuple:
        job = orchestrator.Job(
            id=str(uuid.uuid4()),
            goal="fix the bug",
            budget={"max_turns": 5},
            scheduled_run_id="sched-1" if scheduled else None,
        )
        state.create_job(job.id, job.goal)
        client = _ConfirmCapturingPiClient({"turns": 1})
        captured: dict = {}

        def fake_await(job, summary, timeout, **_kwargs):
            captured["timeout"] = timeout
            return True

        with (
            patch("rau.pi.supervisor.PI_SUPERVISOR", _FakePiSupervisor(client)),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.object(orchestrator, "load_settings", return_value=settings),
            patch("rau.permissions.mode_for", return_value="auto"),
            patch.object(orchestrator, "_await_confirm", fake_await),
            patch.dict(os.environ, {"PI_PROVIDER": "p", "PI_MODEL": "m"}),
        ):
            summary = orchestrator._run_pi_subagent(job, finalize=False)
        self.assertEqual(summary, "fixed it")
        return captured, client

    def test_configured_confirm_timeout_is_honored(self) -> None:
        captured, client = self._run_pi(
            scheduled=False, settings={"confirm_timeout_sec": 120}
        )
        self.assertEqual(captured["timeout"], 120.0)
        self.assertEqual(client.spec.confirm_timeout_ms, 120_000)

    def test_default_confirm_timeout_is_45_seconds(self) -> None:
        captured, client = self._run_pi(scheduled=False, settings={})
        self.assertEqual(captured["timeout"], 45.0)
        self.assertEqual(client.spec.confirm_timeout_ms, 45_000)

    def test_scheduled_runs_keep_their_24h_window(self) -> None:
        captured, client = self._run_pi(
            scheduled=True, settings={"confirm_timeout_sec": 120}
        )
        self.assertEqual(captured["timeout"], 24 * 3600.0)
        self.assertEqual(client.spec.confirm_timeout_ms, 24 * 3600 * 1000)

    def test_full_bypass_disables_pi_confirmations(self) -> None:
        job = orchestrator.Job(
            id=str(uuid.uuid4()),
            goal="fix the bug",
            budget={"max_turns": 5},
        )
        state.create_job(job.id, job.goal)
        client = _ConfirmCapturingPiClient({"turns": 1})

        with (
            patch("rau.pi.supervisor.PI_SUPERVISOR", _FakePiSupervisor(client)),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.object(orchestrator, "load_settings", return_value={}),
            patch("rau.permissions.mode_for", return_value="bypass"),
            patch.object(orchestrator, "_await_confirm") as await_confirm,
            patch.dict(os.environ, {"PI_PROVIDER": "p", "PI_MODEL": "m"}),
        ):
            summary = orchestrator._run_pi_subagent(job, finalize=False)

        self.assertEqual(summary, "fixed it")
        self.assertEqual(client.spec.confirm_tools, [])
        await_confirm.assert_not_called()

    def test_scheduled_run_also_honors_full_bypass(self) -> None:
        job = orchestrator.Job(
            id=str(uuid.uuid4()),
            goal="fix the bug",
            budget={"max_turns": 5},
            scheduled_run_id="sched-1",
        )
        state.create_job(job.id, job.goal)
        client = _ConfirmCapturingPiClient({"turns": 1})

        with (
            patch("rau.pi.supervisor.PI_SUPERVISOR", _FakePiSupervisor(client)),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.object(orchestrator, "load_settings", return_value={}),
            patch("rau.permissions.mode_for", return_value="bypass"),
            patch.object(orchestrator, "_await_confirm") as await_confirm,
            patch.dict(os.environ, {"PI_PROVIDER": "p", "PI_MODEL": "m"}),
        ):
            orchestrator._run_pi_subagent(job, finalize=False)

        self.assertEqual(client.spec.confirm_tools, [])
        await_confirm.assert_not_called()


class SpawnChildrenDeadlineTests(unittest.TestCase):
    """A blocked parent still dies by its own runtime deadline (A9)."""

    def tearDown(self) -> None:
        _join_all_jobs()

    def test_parent_wait_loop_honors_its_own_deadline(self) -> None:
        release = threading.Event()

        def hold(job: orchestrator.Job) -> str:
            release.wait(timeout=10)
            return "done"

        with (
            patch.object(orchestrator, "_run_subagent", hold),
            patch.object(orchestrator, "_with_panels_note", lambda _id, s: s),
            patch.object(orchestrator, "append_diary"),
            patch.object(orchestrator, "append_trace"),
        ):
            parent = orchestrator.start_job("parent goal")
            self.assertTrue(parent["ok"], str(parent))
            with orchestrator._lock:
                parent_job = orchestrator._jobs[parent["id"]]
            parent_job.deadline_monotonic = time.monotonic() - 1
            began = time.monotonic()
            result = orchestrator.spawn_children(parent["id"], ["child goal"])
            elapsed = time.monotonic() - began
            release.set()
        self.assertLess(elapsed, 3, "the wait loop ignored the parent's deadline")
        self.assertTrue(result.get("ok"), str(result))
        self.assertEqual(
            (result.get("children") or [{}])[0].get("state"),
            "running",
            "the deadline, not a finished child, must end the wait",
        )


class ConfirmDurableSettleTests(unittest.TestCase):
    """A wait ending without a yes settles the durable row too (A10)."""

    def _await_with_decision(self, approved: bool) -> dict:
        job = orchestrator.Job(id=str(uuid.uuid4()), goal="g")
        state.create_job(job.id, job.goal)
        store = SimpleNamespace(calls=[])
        with (
            patch.object(state, "durable_enabled", return_value=True),
            patch("rau.control.control_store") as mock_store,
        ):
            mock_store.decide_confirmation.side_effect = (
                lambda cid, decision: store.calls.append((cid, decision)) or True
            )
            decider = threading.Timer(
                0.1, lambda: orchestrator._decide_confirm(job, approved)
            )
            decider.start()
            try:
                result = orchestrator._await_confirm(job, "Do the thing", 5.0)
            finally:
                decider.join()
        store.calls.append(("approved", result))
        return store.calls

    def test_cancel_or_deny_settles_the_durable_row(self) -> None:
        calls = self._await_with_decision(False)
        self.assertEqual(calls[-1], ("approved", False))
        self.assertEqual(len(calls) - 1, 1, "decide_confirmation must run once")
        self.assertFalse(calls[0][1])

    def test_approval_does_not_double_decide(self) -> None:
        calls = self._await_with_decision(True)
        self.assertEqual(calls[-1], ("approved", True))
        self.assertEqual(
            len(calls) - 1,
            0,
            "resolve_confirm already settled the row; _await_confirm must not",
        )


class ResolveConfirmFallbackTests(unittest.TestCase):
    """A stale confirm_id retargets only a deny, never an approval (A11)."""

    def setUp(self) -> None:
        self.older = orchestrator.Job(id=str(uuid.uuid4()), goal="old")
        self.newer = orchestrator.Job(id=str(uuid.uuid4()), goal="new")
        state.create_job(self.older.id, self.older.goal)
        state.create_job(self.newer.id, self.newer.goal)
        with orchestrator._lock:
            orchestrator._jobs[self.older.id] = self.older
            orchestrator._jobs[self.newer.id] = self.newer
        state.set_confirm(
            self.older.id,
            {"id": "cid-old", "job_id": self.older.id, "created": time.time() - 10},
        )
        state.set_confirm(
            self.newer.id,
            {"id": "cid-new", "job_id": self.newer.id, "created": time.time()},
        )

    def tearDown(self) -> None:
        state.set_confirm(self.older.id, None)
        state.set_confirm(self.newer.id, None)
        with orchestrator._lock:
            orchestrator._jobs.pop(self.older.id, None)
            orchestrator._jobs.pop(self.newer.id, None)

    def test_stale_deny_lands_on_the_oldest_pending(self) -> None:
        # A deny is fail-safe: cancelling a confirm the caller never saw
        # grants nothing, so the fallback stays for the deny path.
        orchestrator.resolve_confirm(False, confirm_id="cid-gone")
        self.assertFalse(self.older.confirm_decision)
        self.assertTrue(self.older.confirm_ready.is_set())
        self.assertIsNone(self.newer.confirm_decision)

    def test_stale_approval_never_retargets_another_confirm(self) -> None:
        # Corrected contract: an approval meant for a confirm that just timed
        # out must not authorize a different pending confirm the caller never
        # saw — the stale approve is a no-op instead of a fallback.
        orchestrator.resolve_confirm(True, confirm_id="cid-gone")
        self.assertIsNone(self.older.confirm_decision)
        self.assertIsNone(self.newer.confirm_decision)
        self.assertFalse(self.older.confirm_ready.is_set())
        self.assertFalse(self.newer.confirm_ready.is_set())

    def test_live_confirm_id_routes_to_its_own_job(self) -> None:
        orchestrator.resolve_confirm(False, confirm_id="cid-new")
        self.assertFalse(self.newer.confirm_decision)
        self.assertIsNone(self.older.confirm_decision)


class CancelAllPromptTests(unittest.TestCase):
    """cancel_all wakes confirm waiters instead of parking them (A12)."""

    def tearDown(self) -> None:
        _join_all_jobs()

    def test_cancel_all_wakes_a_confirm_waiter_immediately(self) -> None:
        entered = threading.Event()
        outcome: dict = {}

        def runner(job: orchestrator.Job) -> None:
            entered.set()
            outcome["approved"] = orchestrator._await_confirm(job, "allow?", 30.0)

        with (
            patch.object(orchestrator, "_run_subagent", runner),
            patch.object(orchestrator, "append_diary"),
            patch.object(orchestrator, "append_trace"),
        ):
            started = orchestrator.start_job("needs confirm")
            self.assertTrue(started["ok"], str(started))
            self.assertTrue(entered.wait(timeout=2))
            # Cancel must land after the waiter is parked, not while the
            # runner is still on its way into _await_confirm.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not state.get_confirm():
                time.sleep(0.01)
            self.assertIsNotNone(state.get_confirm())
            began = time.monotonic()
            cancelled = orchestrator.cancel_all()
            with orchestrator._lock:
                job = orchestrator._jobs[started["id"]]
            job.thread.join(timeout=2)
            elapsed = time.monotonic() - began
        self.assertIn(started["id"], cancelled["cancelled"])
        self.assertIs(outcome.get("approved"), False)
        self.assertLess(elapsed, 1.0, "the confirm waiter outlived the cancel")


if __name__ == "__main__":
    unittest.main(verbosity=2)

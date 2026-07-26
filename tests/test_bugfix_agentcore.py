"""Regression tests for agent-orchestration-core bugfixes.

Covers: child resource-profile inheritance, fan-out slot-flag hygiene,
step-runner contract dispatch, pi aggregate turn-budget accounting, and the
job state a timed-out or answered confirmation leaves behind.
"""
from __future__ import annotations

import os
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau import state  # noqa: E402
from rau.agent import orchestrator  # noqa: E402
from rau.pi.client import PiSidecarError, RunResult  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)

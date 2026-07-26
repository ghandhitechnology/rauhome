"""Regression tests for control-plane restart recovery gaps.

A crash can persist a terminal job before the scheduler settles the matching
schedule_run. Recovery must not leave that run in an active state, because
`executing_schedule_run` would hold back every later occurrence forever.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from rau.control.store import ControlStore


class RestartRecoveryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-control-bugfix-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.now = time.time()
        self.store.create_schedule(
            {
                "id": "sched",
                "name": "report",
                "goal": "read status",
                "trigger_kind": "interval",
                "trigger": {"seconds": 60},
                "timezone": "UTC",
            }
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, run_id: str, **changes) -> None:
        run = {
            "id": run_id,
            "schedule_id": "sched",
            "schedule_revision": 1,
            "nominal_at": self.now,
            "nominal_key": run_id,
            "state": "running",
        }
        run.update(changes)
        self.assertIsNotNone(self.store.create_schedule_run(run))

    def test_restart_closes_run_whose_job_already_finished(self):
        self._run("run-terminal", job_id="job")
        self.store.upsert_job(
            {
                "id": "job",
                "goal": "read status",
                "state": "completed",
                "scheduled_run_id": "run-terminal",
            }
        )
        self._run("run-queued", state="queued", job_id=None)

        self.store.mark_unfinished_interrupted(now=self.now + 1)

        run = self.store.get_schedule_run("run-terminal")
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "interrupted")
        self.assertIn("finished job", run["outcome"]["reason"])
        # Nothing is left "executing", so the queued catch-up can dispatch.
        self.assertIsNone(self.store.executing_schedule_run("sched"))
        queued = self.store.get_schedule_run("run-queued")
        self.assertIsNotNone(queued)
        self.assertEqual(queued["state"], "queued")

    def test_restart_closes_run_whose_job_row_is_missing(self):
        self._run("run-ghost", job_id="ghost-job")

        self.store.mark_unfinished_interrupted(now=self.now + 1)

        run = self.store.get_schedule_run("run-ghost")
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "interrupted")
        self.assertIsNone(self.store.executing_schedule_run("sched"))

    def test_restart_still_interrupts_run_with_active_job_first(self):
        self._run("run-active", job_id="job")
        self.store.upsert_job(
            {
                "id": "job",
                "goal": "read status",
                "state": "running",
                "scheduled_run_id": "run-active",
            }
        )

        self.store.mark_unfinished_interrupted(now=self.now + 1)

        run = self.store.get_schedule_run("run-active")
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "interrupted")
        self.assertIn("execution began", run["outcome"]["reason"])
        job = next(job for job in self.store.load_jobs() if job["id"] == "job")
        self.assertEqual(job["state"], "interrupted")


if __name__ == "__main__":
    unittest.main()

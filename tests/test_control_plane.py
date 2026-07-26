from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from rau.computer.session import ComputerSessionManager
from rau.control.store import ControlStore
from rau.scheduler.cron import CronSpec, nominal_key
from rau.scheduler.service import SchedulerService


class ControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-control-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_wal_and_global_computer_lease(self):
        self.assertEqual(self.store.schema_status()["schema_version"], 3)
        first = self.store.create_computer_session(
            {"id": "one", "state": "active", "deadline": time.time() + 60}
        )
        self.assertEqual(first["state"], "active")
        with self.assertRaisesRegex(RuntimeError, "owns the machine"):
            self.store.create_computer_session(
                {"id": "two", "state": "acting", "deadline": time.time() + 60}
            )

    def test_confirmation_rejects_changed_arguments(self):
        now = time.time()
        self.store.save_confirmation(
            {
                "id": "confirm",
                "job_id": "job",
                "tool": "computer_act",
                "arguments": {"action": "click", "x": 10},
                "summary": "click",
                "created": now,
                "expires": now + 60,
            }
        )
        self.assertFalse(
            self.store.decide_confirmation(
                "confirm", True, arguments={"action": "click", "x": 11}
            )
        )
        self.assertTrue(
            self.store.decide_confirmation(
                "confirm", True, arguments={"action": "click", "x": 10}
            )
        )
        self.assertFalse(self.store.decide_confirmation("confirm", True))

    def test_idempotency_replays_result_and_flags_unknown_effect(self):
        request = {"tool": "send", "to": "one@example.test"}
        self.assertEqual(
            self.store.claim_idempotency("key", "tool:send", request)["status"],
            "claimed",
        )
        self.assertEqual(
            self.store.claim_idempotency("key", "tool:send", request)["status"],
            "in_progress",
        )
        self.store.settle_idempotency("key", "unknown_effect", {"ok": False})
        self.assertEqual(
            self.store.claim_idempotency("key", "tool:send", request)["status"],
            "unknown_effect",
        )
        self.assertEqual(
            self.store.claim_idempotency(
                "key", "tool:send", {"tool": "send", "to": "other@example.test"}
            )["status"],
            "conflict",
        )

    def test_restart_requeues_only_unstarted_schedule_and_flags_uncertain_effects(self):
        now = time.time()
        scheduler = SchedulerService(self.store)
        schedule = scheduler.create(
            {
                "name": "restart report",
                "goal": "read status",
                "trigger": {"kind": "once", "at": now + 60},
            },
            now=now,
        )
        run = self.store.create_schedule_run(
            {
                "id": "run",
                "schedule_id": schedule["id"],
                "schedule_revision": schedule["revision"],
                "nominal_at": now,
                "nominal_key": "restart",
                "state": "running",
                "job_id": "job",
            }
        )
        self.assertIsNotNone(run)
        self.store.upsert_job(
            {
                "id": "job",
                "goal": "read status",
                "state": "planning",
                "scheduled_run_id": "run",
            }
        )
        self.store.upsert_step(
            {
                "id": "step",
                "job_id": "job",
                "ordinal": 0,
                "title": "read status",
                "state": "running",
            }
        )
        self.store.claim_idempotency(
            "job:tool-call", "tool:computer_act", {"action": "click"}
        )
        self.store.save_confirmation(
            {
                "id": "pending",
                "job_id": "job",
                "tool": "computer_act",
                "arguments": {"action": "click"},
                "expires": now + 60,
            }
        )
        self.store.create_computer_session(
            {
                "id": "computer",
                "job_id": "job",
                "step_id": "step",
                "state": "acting",
                "lease_expires": now + 60,
                "deadline": now + 60,
            }
        )

        self.assertEqual(self.store.mark_unfinished_interrupted(now=now + 1), 1)
        recovered_run = self.store.get_schedule_run("run")
        self.assertEqual(recovered_run["state"], "queued")
        self.assertIsNone(recovered_run["job_id"])
        recovered_job = next(
            job for job in self.store.load_jobs() if job["id"] == "job"
        )
        self.assertEqual(recovered_job["state"], "interrupted")
        recovered_step = self.store.list_steps("job")[0]
        self.assertEqual(recovered_step["state"], "interrupted")
        self.assertEqual(recovered_step["effect_state"], "unknown")
        self.assertFalse(
            self.store.decide_confirmation(
                "pending", True, arguments={"action": "click"}
            )
        )
        recovered_computer = self.store.get_computer_session("computer")
        self.assertEqual(recovered_computer["state"], "awaiting_review")
        self.assertEqual(recovered_computer["effect_state"], "unknown")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-scheduler-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.scheduler = SchedulerService(self.store)
        # These unit tests inspect durable enqueue semantics without starting a
        # real provider worker.
        self.scheduler._dispatch_queued = lambda: None

    def tearDown(self):
        self.tmp.cleanup()

    def test_interval_catchup_coalesces_and_deduplicates_restart_tick(self):
        now = 1_750_000_000.0
        schedule = self.scheduler.create(
            {
                "name": "hourly",
                "goal": "read a report",
                "trigger": {"kind": "interval", "seconds": 60, "anchor": now},
            },
            now=now,
        )
        self.store.update_schedule(
            schedule["id"], {"next_run_at": now - 300}, bump_revision=False
        )
        self.scheduler.tick(now=now)
        runs = self.store.list_schedule_runs(schedule["id"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["coalesced_count"], 6)
        self.scheduler.tick(now=now)
        self.assertEqual(len(self.store.list_schedule_runs(schedule["id"])), 1)

    def test_overlap_coalesces_into_active_run(self):
        now = 1_750_000_000.0
        schedule = self.scheduler.create(
            {
                "name": "minute",
                "goal": "read status",
                "trigger": {"kind": "interval", "seconds": 60, "anchor": now},
            },
            now=now,
        )
        self.store.update_schedule(
            schedule["id"], {"next_run_at": now}, bump_revision=False
        )
        self.scheduler.tick(now=now)
        first = self.store.list_schedule_runs(schedule["id"])[0]
        self.store.update_schedule(
            schedule["id"], {"next_run_at": now + 60}, bump_revision=False
        )
        self.scheduler.tick(now=now + 60)
        runs = self.store.list_schedule_runs(schedule["id"])
        self.assertEqual(len(runs), 1)
        self.assertGreater(runs[0]["coalesced_count"], first["coalesced_count"])

    def test_running_schedule_accumulates_exactly_one_pending_catchup(self):
        now = 1_750_000_000.0
        schedule = self.scheduler.create(
            {
                "name": "minute",
                "goal": "read status",
                "trigger": {"kind": "interval", "seconds": 60, "anchor": now},
            },
            now=now,
        )
        self.store.update_schedule(
            schedule["id"], {"next_run_at": now}, bump_revision=False
        )
        self.scheduler.tick(now=now)
        first = self.store.list_schedule_runs(schedule["id"])[0]
        self.store.update_schedule_run(first["id"], state="running", job_id="job")

        self.store.update_schedule(
            schedule["id"], {"next_run_at": now + 60}, bump_revision=False
        )
        self.scheduler.tick(now=now + 60)
        self.store.update_schedule(
            schedule["id"], {"next_run_at": now + 120}, bump_revision=False
        )
        self.scheduler.tick(now=now + 120)

        runs = self.store.list_schedule_runs(schedule["id"])
        self.assertEqual(len(runs), 2)
        pending = next(run for run in runs if run["state"] == "queued")
        self.assertEqual(pending["coalesced_count"], 2)
        self.assertEqual(
            self.store.executing_schedule_run(schedule["id"])["id"], first["id"]
        )

    def test_edit_cancels_old_queued_occurrence(self):
        now = 1_750_000_000.0
        schedule = self.scheduler.create(
            {
                "name": "once",
                "goal": "old goal",
                "trigger": {"kind": "once", "at": now - 1},
            },
            now=now,
        )
        self.scheduler.tick(now=now)
        run = self.store.list_schedule_runs(schedule["id"])[0]
        self.assertEqual(run["state"], "queued")
        updated = self.scheduler.update(
            schedule["id"], {"goal": "new goal"}, now=now
        )
        self.assertGreater(updated["revision"], run["schedule_revision"])
        self.assertEqual(
            self.store.get_schedule_run(run["id"])["state"], "cancelled"
        )

    def test_cron_dst_repeated_minute_has_one_nominal_key(self):
        spec = CronSpec.parse("30 1 * * *")
        start = datetime(2025, 11, 2, 0, 0, tzinfo=timezone.utc).timestamp()
        first = spec.next_after(start, "America/New_York")
        second = spec.next_after(first, "America/New_York")
        self.assertNotEqual(first, second)
        self.assertEqual(
            nominal_key(first, "America/New_York"),
            nominal_key(second, "America/New_York"),
        )

    def test_cron_nonexistent_time_advances_to_next_valid_day(self):
        spec = CronSpec.parse("30 2 * * *")
        start = datetime(2025, 3, 9, 0, 0, tzinfo=timezone.utc).timestamp()
        occurrence = spec.next_after(start, "America/New_York")
        local = datetime.fromtimestamp(
            occurrence, tz=timezone.utc
        ).astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((local.month, local.day, local.hour, local.minute), (3, 10, 2, 30))

    def test_transient_retry_classification_never_replays_unknown_effect(self):
        self.assertTrue(
            self.scheduler._transient_failure("provider connection timed out")
        )
        self.assertFalse(
            self.scheduler._transient_failure(
                "provider timeout after unknown_effect"
            )
        )


class FakeComputer:
    def __init__(self):
        self.window_id = 7
        self.bounds = {"x": 10, "y": 20, "width": 800, "height": 600}
        self.displays = [
            {
                "display_id": 1,
                "x": 0,
                "y": 0,
                "width": 1440,
                "height": 900,
            }
        ]
        self.actions = []
        self.nodes = [
            {
                "id": "save",
                "role": "AXButton",
                "title": "Save",
                "label": "",
                "identifier": "save",
                "value": "",
                "secure": False,
                "frame": {"x": 100, "y": 100, "width": 80, "height": 30},
            }
        ]

    def capture(self, **_kwargs):
        return {
            "ok": True,
            "image_b64": "aW1hZ2U=",
            "mime": "image/png",
            "width": 800,
            "height": 600,
            "window_id": self.window_id,
            "window_bounds": dict(self.bounds),
            "title": "Document",
            "app": "Editor",
            "bundle_id": "test.editor",
            "display_id": 1,
            "displays": list(self.displays),
        }

    def inspect(self, **kwargs):
        handles = {node["id"]: object() for node in self.nodes}
        return list(self.nodes), handles if kwargs.get("include_handles") else {}

    def action(self, request, **_kwargs):
        self.actions.append(dict(request))
        return {"ok": True, "action": request["action"]}


class ComputerSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-computer-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.fake = FakeComputer()
        self.manager = ComputerSessionManager(
            self.store,
            capture=self.fake.capture,
            inspect=self.fake.inspect,
            action=self.fake.action,
        )
        self.session = self.manager.start(app="Editor")

    def tearDown(self):
        self.tmp.cleanup()

    def test_semantic_press_then_fresh_verification(self):
        observed = self.manager.observe(self.session["id"])
        self.assertTrue(observed["ok"])
        with patch("rau.computer.session._seconds_since_user_input", return_value=None), patch(
            "rau.computer.session._semantic_press", return_value=(True, "")
        ):
            result = self.manager.act(
                self.session["id"],
                {
                    "action": "click",
                    "target": {"kind": "semantic", "identifier": "save"},
                    "postcondition": {
                        "kind": "exists",
                        "target": {"identifier": "save"},
                    },
                },
            )
        self.assertTrue(result["verified"])
        self.assertNotEqual(
            result["observation"]["id"], observed["observation"]["id"]
        )

    def test_visual_target_rejects_stale_observation(self):
        observed = self.manager.observe(self.session["id"])["observation"]
        result = self.manager.act(
            self.session["id"],
            {
                "action": "click",
                "target": {
                    "kind": "visual",
                    "observation_id": "stale",
                    "x": 10,
                    "y": 10,
                },
            },
        )
        self.assertFalse(result["ok"])
        self.assertIn("stale", result["error"])
        self.assertEqual(self.fake.actions, [])
        self.assertTrue(observed["id"])

    def test_moved_window_invalidates_target(self):
        observed = self.manager.observe(self.session["id"])["observation"]
        self.fake.bounds["x"] = 40
        result = self.manager.act(
            self.session["id"],
            {
                "action": "click",
                "target": {
                    "kind": "visual",
                    "observation_id": observed["id"],
                    "x": 10,
                    "y": 10,
                },
            },
        )
        self.assertFalse(result["ok"])
        self.assertIn("changed", result["error"])
        self.assertEqual(self.fake.actions, [])

    def test_secure_target_requires_internal_exact_confirmation_marker(self):
        self.fake.nodes = [
            {
                **self.fake.nodes[0],
                "id": "password",
                "identifier": "password",
                "role": "AXSecureTextField",
                "secure": True,
            }
        ]
        self.manager.observe(self.session["id"])
        request = {
            "action": "click",
            "target": {"kind": "semantic", "identifier": "password"},
        }
        result = self.manager.act(self.session["id"], request)
        self.assertTrue(result["secure"])
        with patch(
            "rau.computer.session._semantic_press", return_value=(True, "")
        ):
            approved = self.manager.act(
                self.session["id"],
                {**request, "_interactive_confirmed": True},
            )
        self.assertTrue(approved["ok"])

    def test_unknown_effect_can_be_reobserved_and_recovered_by_assertion(self):
        self.manager.observe(self.session["id"])
        self.store.update_computer_session(
            self.session["id"],
            state="awaiting_review",
            effect_state="unknown",
        )
        self.assertTrue(self.manager.observe(self.session["id"])["ok"])
        recovered = self.manager.assert_condition(
            self.session["id"],
            {"kind": "exists", "target": {"identifier": "save"}},
        )
        self.assertTrue(recovered["ok"])
        self.assertEqual(
            self.store.get_computer_session(self.session["id"])["state"],
            "active",
        )


if __name__ == "__main__":
    unittest.main()

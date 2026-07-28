"""Regression tests for the capabilities stability pass.

C1: list_confirmations(state="pending") must not offer expired gates that
    decide_confirmation would reject anyway.
C2: the MCP client reloads config/mcp.json on mtime change, surfaces config
    errors in status(), and marks non-composio servers as unsupported.
C3: skills flagged `always` are injected into every prepared face turn.
C4: ControlStore.prune(cutoff) deletes terminal history and keeps live rows.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import rau.mcp.client as mcp_client
import rau.skills.loader as skills_loader
from rau.control.store import ControlStore
from rau.skills.runtime import prepare_turn

DAY = 24 * 3600.0


class PendingConfirmationListingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-stability-confirm-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def _save(self, confirm_id: str, *, created: float, expires: float) -> None:
        self.store.save_confirmation(
            {
                "id": confirm_id,
                "job_id": "job",
                "tool": "computer_act",
                "arguments": {"action": "click"},
                "summary": confirm_id,
                "created": created,
                "expires": expires,
            }
        )

    def test_pending_listing_hides_expired_gates(self):
        self._save("live", created=self.now, expires=self.now + 3600)
        self._save("stale", created=self.now - 20, expires=self.now - 10)

        pending = self.store.list_confirmations(state="pending")
        self.assertEqual([row["id"] for row in pending], ["live"])
        # Unfiltered listings still show the row for audit purposes.
        everything = self.store.list_confirmations()
        self.assertEqual({row["id"] for row in everything}, {"live", "stale"})

    def test_expired_gate_still_visible_under_expired_filter(self):
        self._save("stale", created=self.now - 20, expires=self.now - 10)
        self.store.expire_confirmations(now=self.now)

        expired = self.store.list_confirmations(state="expired")
        self.assertEqual([row["id"] for row in expired], ["stale"])
        self.assertEqual(self.store.list_confirmations(state="pending"), [])


class ControlPruneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-stability-prune-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.now = time.time()
        self.old = self.now - 30 * DAY
        self.cutoff = self.now - 7 * DAY
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

    def _age(self, table: str, row_id: str, stamp: float) -> None:
        if table == "confirmations":
            assignments = "created=?, decided=?"
            params = (stamp, stamp, row_id)
        elif table == "control_events":
            assignments = "created=?"
            params = (stamp, row_id)
        else:
            assignments = "created=?, updated=?"
            params = (stamp, stamp, row_id)
        key = {"control_events": "seq", "idempotency": "key"}.get(table, "id")
        with self.store._connect() as db:
            db.execute(
                f"UPDATE {table} SET {assignments} WHERE {key}=?", params
            )

    def _count(self, table: str) -> int:
        with self.store._connect() as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_prune_deletes_terminal_history_and_keeps_live_rows(self):
        self.store.upsert_job(
            {
                "id": "job-done",
                "goal": "old",
                "state": "completed",
                "created": self.old,
                "updated": self.old,
            }
        )
        self.store.upsert_step(
            {"id": "step-done", "job_id": "job-done", "ordinal": 1, "title": "t"}
        )
        self.store.upsert_job(
            {
                "id": "job-live",
                "goal": "live",
                "state": "running",
                "created": self.old,
                "updated": self.old,
            }
        )
        self.store.upsert_step(
            {"id": "step-live", "job_id": "job-live", "ordinal": 1, "title": "t"}
        )
        for run_id, state in (("run-done", "completed"), ("run-queued", "queued")):
            self.store.create_schedule_run(
                {
                    "id": run_id,
                    "schedule_id": "sched",
                    "schedule_revision": 1,
                    "nominal_at": self.old,
                    "nominal_key": run_id,
                    "state": state,
                }
            )
            self._age("schedule_runs", run_id, self.old)
        self._age("steps", "step-done", self.old)
        self._age("steps", "step-live", self.old)

        self.store.save_confirmation(
            {
                "id": "confirm-decided",
                "job_id": "job-done",
                "tool": "computer_act",
                "arguments": {},
                "summary": "old decided",
                "created": self.old,
                "expires": self.old + 3600,
            }
        )
        self.assertTrue(
            self.store.decide_confirmation("confirm-decided", True, now=self.old)
        )
        self.store.save_confirmation(
            {
                "id": "confirm-expired",
                "job_id": "job-done",
                "tool": "computer_act",
                "arguments": {},
                "summary": "old expired",
                "created": self.old,
                "expires": self.old + 5,
            }
        )
        self.store.expire_confirmations(now=self.old + 10)
        self.store.save_confirmation(
            {
                "id": "confirm-pending",
                "job_id": "job-live",
                "tool": "computer_act",
                "arguments": {},
                "summary": "still pending",
                "created": self.old,
                "expires": self.now + 3600,
            }
        )

        old_event = self.store.append_event(
            "job_done", "job", "job-done", {"state": "completed"}
        )
        self._age("control_events", str(old_event), self.old)
        self.store.append_event("job_started", "job", "job-live", {})

        self.assertEqual(
            self.store.claim_idempotency("old-key", "step", {"a": 1})["status"],
            "claimed",
        )
        self._age("idempotency", "old-key", self.old)
        self.assertEqual(
            self.store.claim_idempotency("new-key", "step", {"b": 2})["status"],
            "claimed",
        )

        counts = self.store.prune(self.cutoff)

        self.assertEqual(counts["jobs"], 1)
        self.assertEqual(counts["steps"], 1)
        self.assertEqual(counts["schedule_runs"], 1)
        self.assertEqual(counts["confirmations"], 2)
        self.assertEqual(counts["control_events"], 1)
        self.assertEqual(counts["idempotency"], 1)
        # Live rows survive even though they are older than the cutoff.
        self.assertEqual(self._count("jobs"), 1)
        self.assertEqual(
            [step["id"] for step in self.store.list_steps("job-live")],
            ["step-live"],
        )
        run = self.store.get_schedule_run("run-queued")
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "queued")
        self.assertEqual(
            [row["id"] for row in self.store.list_confirmations()],
            ["confirm-pending"],
        )
        # The pruned idempotency key can be claimed again as new work.
        self.assertEqual(
            self.store.claim_idempotency("old-key", "step", {"a": 1})["status"],
            "claimed",
        )
        self.assertEqual(self._count("control_events"), 1)

    def test_prune_respects_cutoff_for_terminal_rows(self):
        self.store.upsert_job(
            {"id": "job-recent", "goal": "recent", "state": "completed"}
        )
        counts = self.store.prune(self.cutoff)
        self.assertEqual(counts["jobs"], 0)
        self.assertEqual(self._count("jobs"), 1)


class MCPClientConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-stability-mcp-")
        self.config = Path(self.tmp.name) / "mcp.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, payload, *, mtime_ns: int) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.config.write_text(text, encoding="utf-8")
        os.utime(self.config, ns=(mtime_ns, mtime_ns))

    def test_status_reflects_config_edits_without_restart(self):
        self._write(
            {"servers": {"composio": {"enabled": False}}}, mtime_ns=1_000
        )
        with (
            patch.object(mcp_client, "MCP_CONFIG", self.config),
            patch.object(mcp_client, "get_secret", lambda name: "key"),
        ):
            client = mcp_client.MCPClient()
            self.assertFalse(client.status()["servers"]["composio"]["enabled"])
            # Same client, edited file: no restart required.
            self._write(
                {"servers": {"composio": {"enabled": True}}}, mtime_ns=2_000
            )
            self.assertTrue(client.status()["servers"]["composio"]["enabled"])
            # The tool path reads the same live config.
            self.assertTrue(client.cfg["servers"]["composio"]["enabled"])

    def test_malformed_config_error_is_surfaced(self):
        self._write("{not json", mtime_ns=1_000)
        with (
            patch.object(mcp_client, "MCP_CONFIG", self.config),
            patch.object(mcp_client, "get_secret", lambda name: "key"),
        ):
            client = mcp_client.MCPClient()
            status = client.status()
        self.assertEqual(status["servers"], {})
        self.assertIn("invalid MCP config", status.get("error", ""))

    def test_non_composio_servers_are_marked_unsupported(self):
        self._write(
            {
                "servers": {
                    "composio": {"enabled": True},
                    "filesystem": {"enabled": True, "type": "stdio"},
                }
            },
            mtime_ns=1_000,
        )
        with (
            patch.object(mcp_client, "MCP_CONFIG", self.config),
            patch.object(mcp_client, "get_secret", lambda name: "key"),
        ):
            status = mcp_client.MCPClient().status()
        self.assertTrue(status["servers"]["composio"]["supported"])
        other = status["servers"]["filesystem"]
        self.assertFalse(other["supported"])
        self.assertIn("unsupported", other["error"])


class AlwaysSkillInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rau-stability-skills-")
        self.skills_dir = Path(self.tmp.name)
        self._write_skill("focus", always=True)
        self._write_skill("sporadic", always=False)
        self._patch = patch.object(skills_loader, "SKILLS_DIR", self.skills_dir)
        self._patch.start()
        self._saved_cache = (
            skills_loader._cache_signature,
            skills_loader._cache_skills,
        )
        skills_loader._cache_signature = ()
        skills_loader._cache_skills = ()

    def tearDown(self):
        skills_loader._cache_signature, skills_loader._cache_skills = (
            self._saved_cache
        )
        self._patch.stop()
        self.tmp.cleanup()

    def _write_skill(self, name: str, *, always: bool) -> None:
        path = self.skills_dir / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {name} skill\n"
            f"always: {'true' if always else 'false'}\n"
            "---\n\n"
            f"Body of the {name} skill.\n",
            encoding="utf-8",
        )

    def test_plain_turn_injects_only_always_skills(self):
        prep = prepare_turn("hello there")
        self.assertIn("## Always-on skills", prep.system_extra)
        self.assertIn("Active skill: focus", prep.system_extra)
        self.assertIn("Body of the focus skill.", prep.system_extra)
        self.assertNotIn("sporadic", prep.system_extra)

    def test_slash_invocation_does_not_duplicate_invoked_skill(self):
        prep = prepare_turn("/focus do the thing")
        self.assertEqual(prep.activate, ["focus"])
        self.assertEqual(prep.system_extra.count("Active skill: focus"), 1)
        self.assertNotIn("sporadic", prep.system_extra)

    def test_meta_commands_still_short_circuit(self):
        prep = prepare_turn("/skills")
        self.assertTrue(prep.immediate_reply.startswith("Available skills:"))


if __name__ == "__main__":
    unittest.main()

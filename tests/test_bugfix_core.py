"""Regression tests for bug fixes in rau's top-level core modules."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SafeUrlTests(unittest.TestCase):
    """urlsplit defers port validation to attribute access; a non-numeric
    port used to raise ValueError out of sanitize_activity and crash the
    activity plane mid-span."""

    def test_non_numeric_port_does_not_crash(self) -> None:
        from rau.activity import sanitize_activity

        public = sanitize_activity({"url": "http://example.com:abc/path?token=secret"})
        self.assertEqual(public["url"], "http://example.com/path")

    def test_bad_port_still_strips_query_and_userinfo(self) -> None:
        from rau.activity import sanitize_activity

        public = sanitize_activity(
            {"url": "https://user:pass@example.com:abc/path?token=secret"}
        )
        encoded = repr(public)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("?token=", encoded)

    def test_valid_port_is_kept(self) -> None:
        from rau.activity import sanitize_activity

        public = sanitize_activity({"url": "http://example.com:8080/path?token=x"})
        self.assertEqual(public["url"], "http://example.com:8080/path")


class DoctorSchemaTests(unittest.TestCase):
    """The database-migrations check hardcoded schema v2 while the store
    migrated to v3, so doctor reported FAIL on every healthy install."""

    def _run_doctor_with_schema(self, schema_version: int) -> dict:
        from rau import doctor

        control_store = mock.Mock()
        control_store.schema_status.return_value = {
            "schema_version": schema_version,
            "path": "test.db",
        }
        scheduler = mock.Mock()
        scheduler.status.return_value = {"running": True, "next_run_at": None}
        pi = mock.Mock()
        pi.health.return_value = {"ok": True}
        pi.enabled.return_value = False
        launch = {"ok": True, "installed": True, "loaded": True, "path": "x"}
        with mock.patch("rau.control.control_store", control_store), mock.patch(
            "rau.scheduler.SCHEDULER", scheduler
        ), mock.patch("rau.pi.supervisor.PI_SUPERVISOR", pi), mock.patch(
            "rau.computer.cua.cua_status",
            return_value={
                "accessibility": True,
                "screen_recording": True,
                "displays": [1],
            },
        ), mock.patch(
            "rau.providers.registry.provider_status",
            return_value={"kimi": {"configured": True}},
        ), mock.patch(
            "rau.launch_agent.status", return_value=launch
        ), mock.patch.object(
            sys, "platform", "linux"
        ):
            return doctor.run_doctor()

    def _database_check(self, report: dict) -> dict:
        return next(c for c in report["checks"] if c["name"] == "database migrations")

    def test_current_schema_passes(self) -> None:
        from rau.control.store import SCHEMA_VERSION

        report = self._run_doctor_with_schema(SCHEMA_VERSION)
        check = self._database_check(report)
        self.assertTrue(check["ok"], check)

    def test_stale_or_newer_schema_fails(self) -> None:
        from rau.control.store import SCHEMA_VERSION

        report = self._run_doctor_with_schema(SCHEMA_VERSION + 99)
        check = self._database_check(report)
        self.assertFalse(check["ok"], check)


class WriteReportTests(unittest.TestCase):
    """A failed write used to leave the `.tmp` sibling behind; the atomic
    replace pattern now unlinks it like env.py and launch_agent.py do."""

    def test_report_round_trip_leaves_no_tmp(self) -> None:
        from rau.power import write_report

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            write_report(target, {"label": "idle", "median_cpu_percent": 1.5})
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["label"], "idle"
            )
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_failed_write_cleans_up_tmp(self) -> None:
        from rau.power import write_report

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            with mock.patch(
                "rau.power.Path.write_text", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    write_report(target, {"label": "idle"})
            self.assertEqual(list(Path(tmp).iterdir()), [])


class LaunchAgentDefinitionTests(unittest.TestCase):
    def test_hub_mode_uses_hub_entrypoint(self) -> None:
        from rau import launch_agent

        plist = launch_agent.definition(mode="hub", no_audio=True)
        self.assertEqual(plist["ProgramArguments"][-1], "hub")
        self.assertNotIn("--no-audio", plist["ProgramArguments"])

    def test_all_mode_keeps_no_audio_flag(self) -> None:
        from rau import launch_agent

        plist = launch_agent.definition(mode="all", no_audio=True)
        self.assertEqual(plist["ProgramArguments"][-2:], ["all", "--no-audio"])


if __name__ == "__main__":
    unittest.main()

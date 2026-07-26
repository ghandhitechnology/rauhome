"""Per-scope permission modes: auto / bypass / readonly."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ToolDecisionTests(unittest.TestCase):
    def tearDown(self) -> None:
        from rau import permissions as perm

        with mock.patch.object(perm, "get_permissions", return_value=dict(perm.DEFAULT_PERMISSIONS)):
            pass

    def _with_modes(self, **modes: str):
        from rau import permissions as perm

        base = dict(perm.DEFAULT_PERMISSIONS)
        base.update(modes)
        return mock.patch.object(perm, "get_permissions", return_value=base)

    def test_auto_shell_confirms(self) -> None:
        from rau.permissions import tool_decision

        with self._with_modes(subagents="auto"):
            self.assertEqual(
                tool_decision("subagents", "run_shell", {"command": "ls"}),
                "confirm",
            )
            self.assertEqual(
                tool_decision("subagents", "read_file", {"path": "README.md"}),
                "allow",
            )

    def test_bypass_allows_shell(self) -> None:
        from rau.permissions import tool_decision

        with self._with_modes(subagents="bypass", room="bypass", heartbeats="bypass"):
            self.assertEqual(
                tool_decision("subagents", "run_shell", {"command": "ls"}),
                "allow",
            )

    def test_readonly_denies_shell_allows_read(self) -> None:
        from rau.permissions import tool_decision

        with self._with_modes(room="readonly", subagents="readonly", heartbeats="readonly"):
            self.assertEqual(
                tool_decision("room", "run_shell", {"command": "ls"}),
                "deny",
            )
            self.assertEqual(
                tool_decision("room", "read_file", {"path": "x"}),
                "allow",
            )
            self.assertEqual(
                tool_decision("room", "memory_write", {"text": "nope"}),
                "deny",
            )


class HeartbeatNudgeTests(unittest.TestCase):
    def test_maybe_nudge_skipped_when_readonly(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import permissions as perm

        with mock.patch.object(perm, "mode_for", return_value="readonly"):
            with mock.patch.object(presence_mod, "can_initiate") as can:
                presence_mod.maybe_nudge()
                can.assert_not_called()

    def test_maybe_nudge_checks_initiate_when_auto(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import permissions as perm

        with mock.patch.object(perm, "mode_for", return_value="auto"):
            with mock.patch.object(presence_mod, "can_initiate", return_value=False) as can:
                presence_mod.maybe_nudge()
                can.assert_called_once()


class JobsReadonlyTests(unittest.TestCase):
    def test_start_job_blocked(self) -> None:
        from rau.agent import orchestrator
        from rau import permissions as perm

        with mock.patch.object(perm, "mode_for", return_value="readonly"):
            result = orchestrator.start_job("do a thing")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("reason"), "readonly")


class BypassSkipConfirmTests(unittest.TestCase):
    def test_decision_bypass_skips_confirm_path(self) -> None:
        """Bypass mode never returns confirm — orchestrator will not await."""
        from rau.permissions import tool_decision

        with mock.patch(
            "rau.permissions.get_permissions",
            return_value={
                "subagents": "bypass",
                "room": "bypass",
                "heartbeats": "bypass",
            },
        ):
            self.assertEqual(
                tool_decision("subagents", "run_shell", {"command": "echo hi"}),
                "allow",
            )


class PersistPermissionsTests(unittest.TestCase):
    def test_set_global_mode_locksteps_scopes(self) -> None:
        from rau import permissions as perm
        from rau.providers import registry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with mock.patch.object(registry, "SETTINGS_CONFIG", path):
                with mock.patch.object(registry, "_settings", {}):
                    out = perm.set_permissions({"mode": "readonly"})
                    self.assertEqual(out["room"], "readonly")
                    self.assertEqual(out["subagents"], "readonly")
                    self.assertEqual(out["heartbeats"], "readonly")
                    self.assertEqual(perm.global_mode(out), "readonly")
                    loaded = perm.get_permissions()
                    self.assertEqual(loaded["subagents"], "readonly")


if __name__ == "__main__":
    unittest.main()

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

    def test_scheduled_subagent_also_skips_confirm_in_full_bypass(self) -> None:
        from rau.agent import orchestrator

        job = orchestrator.Job(
            id="scheduled-bypass-test",
            goal="run maintenance",
            scheduled_run_id="schedule-1",
            permission_policy="approval",
        )
        with mock.patch("rau.permissions.mode_for", return_value="bypass"):
            self.assertEqual(
                orchestrator._job_tool_decision(
                    job, "run_shell", {"command": "echo hi"}
                ),
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


class ScopeIsolationTests(unittest.TestCase):
    """Each scope answers for itself, and never grants more than it was asked."""

    def _stored(self, **modes: str):
        from rau import permissions as perm

        base = dict(perm.DEFAULT_PERMISSIONS)
        base.update(modes)
        return mock.patch.object(perm, "get_permissions", return_value=base)

    def test_a_loose_room_does_not_loosen_the_subagents(self) -> None:
        """
        The security-relevant case: `mode_for` used to return the global mode
        whatever scope it was handed, so read-only subagents inherited the
        room's bypass and ran shell commands with no confirmation at all.
        """
        from rau.permissions import mode_for, tool_decision

        with self._stored(room="bypass", subagents="readonly"):
            self.assertEqual(mode_for("subagents"), "readonly")
            self.assertEqual(mode_for("room"), "bypass")
            self.assertEqual(
                tool_decision("subagents", "run_shell", {"command": "rm -rf /"}),
                "deny",
            )
            self.assertEqual(
                tool_decision("room", "run_shell", {"command": "rm -rf /"}),
                "allow",
            )

    def test_a_tight_room_does_not_tighten_the_heartbeats(self) -> None:
        from rau.permissions import heartbeat_nudge_allowed, jobs_allowed

        with self._stored(room="readonly", subagents="auto", heartbeats="auto"):
            self.assertTrue(jobs_allowed())
            self.assertTrue(heartbeat_nudge_allowed())

    def test_an_unknown_scope_fails_closed_to_auto(self) -> None:
        from rau.permissions import mode_for

        with self._stored(room="bypass", subagents="bypass", heartbeats="bypass"):
            self.assertEqual(mode_for("does_not_exist"), "auto")

    def test_global_mode_only_reports_bypass_when_every_scope_bypasses(self) -> None:
        from rau.permissions import global_mode

        # "Full bypass" is a global promise: a mixed configuration must not
        # display it while one of its scopes can still ask for permission.
        self.assertEqual(
            global_mode({"room": "auto", "subagents": "bypass", "heartbeats": "readonly"}),
            "auto",
        )
        self.assertEqual(
            global_mode({"room": "readonly", "subagents": "auto", "heartbeats": "readonly"}),
            "auto",
        )
        self.assertEqual(
            global_mode({"room": "bypass", "subagents": "bypass", "heartbeats": "bypass"}),
            "bypass",
        )
        self.assertEqual(
            global_mode({"room": "auto", "subagents": "auto", "heartbeats": "auto"}),
            "auto",
        )

    def test_explicit_per_scope_writes_are_kept_as_written(self) -> None:
        from rau import permissions as perm
        from rau.providers import registry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with mock.patch.object(registry, "SETTINGS_CONFIG", path):
                with mock.patch.object(registry, "_settings", {}):
                    out = perm.set_permissions(
                        {"subagents": "bypass", "room": "readonly"}
                    )
                    # Previously both collapsed onto whichever scope was listed
                    # first, silently discarding the other half of the request.
                    self.assertEqual(out["subagents"], "bypass")
                    self.assertEqual(out["room"], "readonly")
                    self.assertEqual(out["heartbeats"], "auto")
                    self.assertEqual(perm.get_permissions()["subagents"], "bypass")


class ReadonlyAllowlistTests(unittest.TestCase):
    def test_unknown_tools_are_denied_rather_than_allowed(self) -> None:
        from rau.permissions import is_readonly_allowed

        for name in ("run_shell", "write_file", "edit_file", "some_new_tool", ""):
            self.assertFalse(is_readonly_allowed(name), name)

    def test_inspection_tools_are_allowed(self) -> None:
        from rau.permissions import is_readonly_allowed

        for name in ("read_file", "memory_read", "list_skills", "body_choreography"):
            self.assertTrue(is_readonly_allowed(name), name)

    def test_remote_tools_allow_only_payload_free_lookups(self) -> None:
        from rau.permissions import is_readonly_allowed

        # Search forwards model-written query text to a remote API — an
        # exfiltration channel, not a lookup — so read-only refuses it.
        self.assertFalse(is_readonly_allowed("composio_search", {"query": "x"}))
        self.assertFalse(is_readonly_allowed("composio_gmail_search"))
        self.assertTrue(is_readonly_allowed("composio_gmail_list"))
        self.assertTrue(is_readonly_allowed("mcp_calendar_status"))
        self.assertFalse(is_readonly_allowed("composio_gmail_send"))
        self.assertFalse(is_readonly_allowed("mcp_calendar_create_event"))

    def test_computer_use_allows_looking_but_not_touching(self) -> None:
        from rau.permissions import is_readonly_allowed

        self.assertTrue(is_readonly_allowed("cua_action", {"action": "screenshot"}))
        self.assertFalse(is_readonly_allowed("cua_action", {"action": "click"}))
        self.assertFalse(is_readonly_allowed("cua_action", {"action": "type"}))

    def test_bare_computer_observe_is_refused(self) -> None:
        from rau.permissions import is_readonly_allowed

        # Without a session_id the call starts a session and seizes the single
        # machine lease — a mutation read-only mode must not make.
        self.assertFalse(is_readonly_allowed("computer_observe", {}))
        self.assertFalse(is_readonly_allowed("computer_observe", {"session_id": " "}))
        self.assertTrue(is_readonly_allowed("computer_observe", {"session_id": "s1"}))


class ExfiltrationGateTests(unittest.TestCase):
    """The read-secrets-then-search-away chain is broken in every mode."""

    def _with_modes(self, **modes: str):
        from rau import permissions as perm

        base = dict(perm.DEFAULT_PERMISSIONS)
        base.update(modes)
        return mock.patch.object(perm, "get_permissions", return_value=base)

    def test_secret_reads_await_confirmation_in_auto(self) -> None:
        from rau.permissions import tool_decision

        # Pure classification: none of these paths is ever opened.
        with self._with_modes(subagents="auto"):
            self.assertEqual(
                tool_decision("subagents", "read_file", {"path": ".env"}),
                "confirm",
            )
            self.assertEqual(
                tool_decision("subagents", "read_file", {"path": "secrets/keys.json"}),
                "confirm",
            )
            self.assertEqual(
                tool_decision("subagents", "read_file", {"path": "README.md"}),
                "allow",
            )

    def test_readonly_denies_search_outright(self) -> None:
        from rau.permissions import tool_decision

        with self._with_modes(room="readonly", subagents="readonly", heartbeats="readonly"):
            self.assertEqual(
                tool_decision("room", "composio_search", {"query": "anything"}),
                "deny",
            )

    def test_readonly_denies_bare_observe_through_the_decision_layer(self) -> None:
        from rau.permissions import tool_decision

        with self._with_modes(room="readonly", subagents="readonly", heartbeats="readonly"):
            self.assertEqual(
                tool_decision("room", "computer_observe", {}),
                "deny",
            )
            self.assertEqual(
                tool_decision("room", "computer_observe", {"session_id": "s1"}),
                "allow",
            )


if __name__ == "__main__":
    unittest.main()

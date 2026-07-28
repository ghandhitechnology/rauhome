"""
Stability regressions for the Pi sidecar bridge.

The spawned sidecar must not inherit provider credentials beyond the one its
own configured provider needs (PI1), and a supervisor-spawned sidecar gets a
fresh bearer token so no other local process can drive it (PI3). A
hand-started tokenless sidecar keeps working untouched.

Nothing here touches the network or spawns a real process; both are fakes.

Run: python -m unittest tests.test_stability_pi -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.pi.supervisor import PiSupervisor, _sidecar_env  # noqa: E402, SLF001


class SidecarEnvTests(unittest.TestCase):
    def _env(self, variables: dict, settings: dict | None = None) -> dict:
        with mock.patch.dict(os.environ, variables, clear=True), mock.patch(
            "rau.pi.supervisor.load_settings", return_value=settings or {}
        ):
            return _sidecar_env()

    def test_provider_credentials_are_scrubbed(self) -> None:
        env = self._env(
            {
                "PATH": "/usr/bin:/bin",
                "HOME": "/home/test",
                "OPENAI_API_KEY": "sk-openai",
                "DEEPSEEK_API_KEY": "sk-deepseek",
                "ELEVENLABS_API_KEY": "sk-eleven",
                "GENERIC_TOKEN": "tok",
                "APP_PASSWORD": "pw",
                "MY_CREDENTIAL": "cr",
                "SOME_SECRET": "se",
                "AUTHORIZATION": "Bearer x",
                "AWS_SESSION_TOKEN": "aws",
                "PI_SIDECAR_PORT": "8791",
                "PI_SIDECAR_TOKEN": "sidecar-tok",
            }
        )
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        self.assertEqual(env["HOME"], "/home/test")
        self.assertEqual(env["PI_SIDECAR_PORT"], "8791")
        self.assertEqual(env["PI_SIDECAR_TOKEN"], "sidecar-tok")
        for leaked in (
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "ELEVENLABS_API_KEY",
            "GENERIC_TOKEN",
            "APP_PASSWORD",
            "MY_CREDENTIAL",
            "SOME_SECRET",
            "AUTHORIZATION",
            "AWS_SESSION_TOKEN",
        ):
            self.assertNotIn(leaked, env)

    def test_configured_provider_keeps_only_its_own_key(self) -> None:
        env = self._env(
            {
                "PI_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant",
                "OPENAI_API_KEY": "sk-openai",
            }
        )
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), "sk-ant")
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_provider_falls_back_to_settings(self) -> None:
        env = self._env(
            {"OPENROUTER_API_KEY": "sk-or"},
            settings={"pi_provider": "openrouter"},
        )
        self.assertEqual(env.get("OPENROUTER_API_KEY"), "sk-or")

    def test_unknown_or_faux_provider_keeps_no_keys(self) -> None:
        for provider in ("faux", "not-a-provider"):
            env = self._env({"PI_PROVIDER": provider, "OPENAI_API_KEY": "sk"})
            self.assertNotIn("OPENAI_API_KEY", env)


class _FakeProc:
    def poll(self) -> None:
        return None


class _FakeClient:
    """First probe reports no sidecar; the post-spawn poll reports healthy."""

    instances: list = []

    def __init__(self, *_args, token=None, **_kwargs) -> None:
        self.token = token if token is not None else os.environ.get("PI_SIDECAR_TOKEN", "")
        _FakeClient.instances.append(self)

    def available(self) -> bool:
        return len(_FakeClient.instances) > 1


class EnsureRunningSpawnTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.instances = []
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "pi-sidecar" / "src").mkdir(parents=True)
        (root / "pi-sidecar" / "src" / "server.mjs").write_text("// stub\n")
        (root / "pi-sidecar" / "node_modules").mkdir()
        self.root = root

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_spawn_scrubs_env_and_injects_a_bearer_token(self) -> None:
        supervisor = PiSupervisor()
        with mock.patch.dict(
            os.environ,
            {"PI_EXECUTOR_ENABLED": "1", "OPENAI_API_KEY": "sk-openai"},
            clear=False,
        ), mock.patch("rau.pi.supervisor.ROOT", self.root), mock.patch(
            "rau.pi.supervisor.PiSidecar", _FakeClient
        ), mock.patch(
            "rau.pi.supervisor.load_settings", return_value={}
        ), mock.patch(
            "rau.pi.supervisor.shutil.which", return_value="/usr/bin/node"
        ), mock.patch(
            "rau.pi.supervisor.subprocess.Popen", return_value=_FakeProc()
        ) as spawn:
            client = supervisor.ensure_running(timeout=2.0)
            token = os.environ.get("PI_SIDECAR_TOKEN", "")
        self.assertGreaterEqual(len(token), 32)
        self.assertIs(client, _FakeClient.instances[-1])
        self.assertEqual(client.token, token)
        child_env = spawn.call_args.kwargs["env"]
        self.assertEqual(child_env["PI_SIDECAR_TOKEN"], token)
        self.assertNotIn("OPENAI_API_KEY", child_env)

    def test_env_token_is_not_rewritten_for_a_running_sidecar(self) -> None:
        supervisor = PiSupervisor()
        _FakeClient.instances = []

        class HealthyClient(_FakeClient):
            def available(self) -> bool:
                return True

        with mock.patch.dict(
            os.environ,
            {"PI_EXECUTOR_ENABLED": "1", "PI_SIDECAR_TOKEN": "manual-token"},
            clear=False,
        ), mock.patch("rau.pi.supervisor.PiSidecar", HealthyClient), mock.patch(
            "rau.pi.supervisor.subprocess.Popen"
        ) as spawn:
            client = supervisor.ensure_running(timeout=2.0)
            token = os.environ["PI_SIDECAR_TOKEN"]
        spawn.assert_not_called()
        self.assertEqual(token, "manual-token")
        self.assertEqual(client.token, "manual-token")


if __name__ == "__main__":
    unittest.main()

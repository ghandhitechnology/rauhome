"""Focused, credential-free hardening tests for agent execution layers."""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau import state  # noqa: E402
from rau.agent import orchestrator  # noqa: E402
from rau.agent.danger import classify_tool  # noqa: E402
from rau.agent.tools import run_tool  # noqa: E402
from rau.computer.cua import execute_action  # noqa: E402
from rau.mcp.client import MCPClient  # noqa: E402
from rau.pi.client import PiSidecar, PiSidecarError, RunSpec  # noqa: E402
from rau.providers.anthropic_compat import _parse_anthropic_result  # noqa: E402
from rau.providers import openai_compat  # noqa: E402
from rau.providers.base import (  # noqa: E402
    ChatResult,
    Message,
    ToolCall,
    messages_to_openai,
    parse_tool_calls_openai,
)
from rau.providers.registry import _default_models, _validated_models  # noqa: E402
from rau.providers.openai_compat import OpenAICompatProvider  # noqa: E402


class AgentToolTests(unittest.TestCase):
    def test_confirmation_gate_covers_shell_bypasses_external_actions_and_cua_case(
        self,
    ) -> None:
        self.assertTrue(
            classify_tool("run_shell", {"command": "printf x > existing.py"})[0]
        )
        self.assertTrue(
            classify_tool("run_shell", {"command": "printf x >> existing.py"})[0]
        )
        self.assertTrue(
            classify_tool(
                "composio_execute",
                {"tools": [{"name": "unknown_future_write_action"}]},
            )[0]
        )
        self.assertTrue(classify_tool("cua_action", {"action": "CLICK"})[0])

    def test_missing_shell_sandbox_fails_closed(self) -> None:
        from rau.agent.sandbox import NO_SANDBOX_WARNING

        with (
            patch(
                "rau.agent.tools.shell_argv",
                return_value=(["/bin/sh", "-c", "printf unsafe"], NO_SANDBOX_WARNING),
            ),
            patch("rau.agent.tools.allow_unconfined_shell", return_value=False),
            patch("rau.agent.tools.subprocess.Popen") as popen,
        ):
            result = run_tool("run_shell", {"command": "printf unsafe"})
        self.assertFalse(result["ok"])
        self.assertIn("refusing", result["error"])
        popen.assert_not_called()

    def test_shell_cancel_stops_process_tree_promptly(self) -> None:
        cancel = threading.Event()
        threading.Timer(0.15, cancel.set).start()
        started = time.monotonic()
        result = run_tool("run_shell", {"command": "sleep 30"}, cancel=cancel)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(result["ok"])
        self.assertTrue(result["cancelled"])

    def test_shell_timeout_is_a_tool_error_not_an_exception(self) -> None:
        started = time.monotonic()
        result = run_tool(
            "run_shell", {"command": "sleep 30", "timeout_sec": 1}
        )
        self.assertLess(time.monotonic() - started, 4)
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])

    def test_malformed_tool_arguments_are_refused(self) -> None:
        result = run_tool("run_shell", {"_raw": '{"command":'})
        self.assertFalse(result["ok"])
        self.assertIn("malformed", result["error"])
        self.assertFalse(run_tool("read_file", ["README.md"])["ok"])  # type: ignore[arg-type]

    def test_computer_wait_is_bounded_and_cancellable(self) -> None:
        cancel = threading.Event()
        threading.Timer(0.05, cancel.set).start()
        started = time.monotonic()
        result = execute_action({"action": "wait", "seconds": 20}, cancel)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(result["cancelled"])
        self.assertFalse(execute_action({"action": "wait", "seconds": -1})["ok"])
        injected = execute_action(
            {"action": "key", "key": 'x"\nend tell\ndo shell script "id"'}
        )
        self.assertFalse(injected["ok"])


class AgentLifecycleTests(unittest.TestCase):
    def test_invalid_redirect_does_not_cancel_live_work(self) -> None:
        with (
            patch.object(orchestrator, "cancel_all") as cancel_all,
            patch.object(orchestrator, "start_job") as start_job,
        ):
            result = orchestrator.redirect_hard_task(
                "x" * (orchestrator.MAX_GOAL_CHARS + 1)
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "goal_too_large")
        cancel_all.assert_not_called()
        start_job.assert_not_called()


class ProviderEventTests(unittest.TestCase):
    def test_stream_bytes_and_line_length_are_bounded(self) -> None:
        provider = OpenAICompatProvider("test", "https://invalid", "TEST_KEY")
        event = (
            b"data: "
            + json.dumps(
                {"choices": [{"delta": {"content": "x" * 4096}}]}
            ).encode()
            + b"\n"
        )
        oversized_stream = io.BytesIO(
            event * (openai_compat.MAX_RESPONSE_BYTES // len(event) + 2)
        )
        with (
            patch.object(provider, "_key", return_value="secret"),
            patch.object(provider, "_open", return_value=oversized_stream),
        ):
            with self.assertRaisesRegex(RuntimeError, "stream exceeded"):
                list(
                    provider.chat_stream(
                        [Message(role="user", content="x")],
                        model="test",
                    )
                )

        oversized_line = io.BytesIO(
            b"data: " + b"x" * (openai_compat.MAX_STREAM_LINE_BYTES + 1)
        )
        with (
            patch.object(provider, "_key", return_value="secret"),
            patch.object(provider, "_open", return_value=oversized_line),
        ):
            with self.assertRaisesRegex(RuntimeError, "stream line exceeded"):
                list(
                    provider.chat_stream(
                        [Message(role="user", content="x")],
                        model="test",
                    )
                )

    def test_malformed_stream_event_flood_is_bounded(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                line = (
                    b'data: {"choices":[{"delta":{"tool_calls":"not-an-array"}}]}\n'
                )
                return iter([line] * 17)

        provider = OpenAICompatProvider("test", "https://invalid", "TEST_KEY")
        with (
            patch.object(provider, "_key", return_value="secret"),
            patch.object(provider, "_open", return_value=Response()),
        ):
            with self.assertRaisesRegex(RuntimeError, "too many malformed"):
                list(
                    provider.stream_turn(
                        [Message(role="user", content="x")],
                        model="test",
                    )
                )

    def test_duplicate_tool_call_ids_are_demoted_instead_of_mispaired(self) -> None:
        duplicate = [
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="same", name="read_file", arguments={"path": "a"}),
                    ToolCall(id="same", name="read_file", arguments={"path": "b"}),
                ],
            ),
            Message(
                role="tool",
                content='{"ok": true}',
                tool_call_id="same",
                name="read_file",
            ),
        ]
        wire = messages_to_openai(duplicate)
        self.assertFalse(any(item.get("tool_calls") for item in wire))
        self.assertTrue(any("[tool read_file]" in str(item.get("content")) for item in wire))

    def test_model_selection_rejects_unknown_provider_and_invalid_limits(self) -> None:
        config = _default_models()
        config["subagent"]["provider"] = "not-a-provider"
        with self.assertRaisesRegex(ValueError, "unknown provider"):
            _validated_models(config)

        config = _default_models()
        config["subagent"]["max_tokens"] = -1
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            _validated_models(config)

        config = _default_models()
        config["subagent"]["model"] = "custom/provider-model"
        self.assertEqual(
            _validated_models(config)["subagent"]["model"], "custom/provider-model"
        )

    def test_openai_malformed_arguments_are_non_executable(self) -> None:
        calls = parse_tool_calls_openai(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "run_shell",
                                        "arguments": '{"command":',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
        self.assertEqual(calls[0].arguments, {"_raw": '{"command":'})
        self.assertFalse(run_tool(calls[0].name, calls[0].arguments)["ok"])

    def test_anthropic_non_object_input_is_non_executable(self) -> None:
        result = _parse_anthropic_result(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "c1",
                        "name": "run_shell",
                        "input": ["echo unsafe"],
                    }
                ]
            }
        )
        self.assertEqual(result.tool_calls[0].arguments, {"_raw": ["echo unsafe"]})


class _MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "bad call"}}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


class MCPTests(unittest.TestCase):
    def test_json_rpc_error_is_not_reported_as_success(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MCPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        client = MCPClient()
        client.cfg = {
            "servers": {
                "composio": {
                    "enabled": True,
                    "url": f"http://127.0.0.1:{server.server_port}/mcp",
                    "api_key_env": "TEST_KEY",
                }
            }
        }
        with (
            patch("rau.mcp.client.get_secret", return_value="secret"),
            patch("rau.mcp.client.append_trace"),
        ):
            result = client.composio_search("anything")
        self.assertFalse(result["ok"])
        self.assertIn("bad call", result["error"])

    def test_non_tls_non_loopback_endpoint_is_refused(self) -> None:
        client = MCPClient()
        client.cfg = {
            "servers": {
                "composio": {
                    "enabled": True,
                    "url": "http://example.com/mcp",
                    "api_key_env": "TEST_KEY",
                }
            }
        }
        with patch("rau.mcp.client.get_secret", return_value="secret"):
            result = client.composio_search("anything")
        self.assertFalse(result["ok"])
        self.assertIn("unsafe", result["error"])


class _PiHandler(BaseHTTPRequestHandler):
    cancelled = False

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/runs/run-1/events"):
            payload = (
                b"data: {malformed}\n\n"
                b"data: {\"seq\":1,\"type\":\"state\",\"progress\":\"working\"}\n\n"
                b"data: {\"seq\":2,\"type\":\"result\",\"state\":\"done\",\"result\":\"ok\",\"error\":\"\"}\n\n"
                b"data: {\"seq\":3,\"type\":\"close\"}\n\n"
            )
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/runs/run-1":
            self._json({"id": "run-1", "state": "done", "result": "ok", "error": ""})
            return
        self._json({"ok": True})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        if self.path == "/runs":
            self._json({"id": "run-1", "state": "running"}, 201)
        elif self.path == "/runs/run-1/cancel":
            type(self).cancelled = True
            self._json({"cancelled": True, "state": "cancelled"})
        else:
            self._json({"accepted": True})

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


class PiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _PiHandler.cancelled = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _PiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = PiSidecar(
            f"http://127.0.0.1:{self.server.server_port}",
            timeout=2,
            stream_timeout=2,
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_malformed_sse_frame_is_skipped(self) -> None:
        progress: list[str] = []
        result = self.client.run(RunSpec(goal="x"), on_progress=progress.append)
        self.assertTrue(result.ok)
        self.assertEqual(result.result, "ok")
        self.assertEqual(progress, ["working"])

    def test_callback_failure_cancels_remote_run(self) -> None:
        with self.assertRaises(PiSidecarError):
            self.client.run(
                RunSpec(goal="x"),
                on_progress=lambda _value: (_ for _ in ()).throw(RuntimeError("boom")),
            )
        self.assertTrue(_PiHandler.cancelled)

    def test_run_id_cannot_select_another_endpoint(self) -> None:
        with self.assertRaises(PiSidecarError):
            self.client.snapshot("../health")


@unittest.skipUnless(
    shutil.which("node")
    and (
        Path(__file__).resolve().parent.parent
        / "pi-sidecar"
        / "node_modules"
        / "@earendil-works"
        / "pi-agent-core"
    ).exists(),
    "pi sidecar dependencies are not installed",
)
class PiSidecarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = int(sock.getsockname()[1])
        env = {
            **os.environ,
            "PI_SIDECAR_PORT": str(cls.port),
            "PI_SIDECAR_ROOT": str(cls.root),
        }
        cls.process = subprocess.Popen(
            ["node", "src/server.mjs"],
            cwd=cls.root / "pi-sidecar",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        cls.client = PiSidecar(
            f"http://127.0.0.1:{cls.port}", timeout=3, stream_timeout=10
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                output = cls.process.stdout.read() if cls.process.stdout else ""
                raise RuntimeError(f"sidecar failed to start: {output}")
            if cls.client.available():
                return
            time.sleep(0.05)
        raise RuntimeError("sidecar did not become healthy")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)

    def test_real_sse_and_confirmed_tool_execution(self) -> None:
        confirms: list[str] = []
        text: list[str] = []
        result = self.client.run(
            RunSpec(
                goal="quote ' and shell metacharacters $(false)",
                cwd=str(self.root),
                faux_scenario="tool",
                run_timeout_ms=5_000,
            ),
            on_text=text.append,
            on_confirm=lambda request: (confirms.append(request.tool), True)[1],
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(confirms, ["bash"])
        self.assertTrue(text)
        self.assertIn("shell metacharacters", result.result)

    def test_real_cancel_interrupts_stalled_tool(self) -> None:
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        result = self.client.run(
            RunSpec(
                goal="cancel me",
                cwd=str(self.root),
                faux_scenario="stall",
                run_timeout_ms=5_000,
            ),
            cancel=cancel,
            on_confirm=lambda _request: True,
        )
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(result.state, "cancelled")


class OrchestratorBudgetTests(unittest.TestCase):
    def test_step_budget_exhaustion_is_failed_not_done(self) -> None:
        class EndlessProvider:
            def chat(self, *_args, **_kwargs) -> ChatResult:
                return ChatResult(
                    content="",
                    tool_calls=[
                        ToolCall(id=str(uuid.uuid4()), name="memory_read", arguments={})
                    ],
                )

        job = orchestrator.Job(id=str(uuid.uuid4()), goal="never finish")
        state.create_job(job.id, job.goal)
        with (
            patch.object(
                orchestrator,
                "chat_for_slot",
                return_value=(EndlessProvider(), {"model": "test"}),
            ),
            patch.object(orchestrator, "load_soul", return_value="soul"),
            patch.object(orchestrator, "provider_summarizer", return_value=lambda _x: "summary"),
            patch.object(orchestrator, "maybe_compact", side_effect=lambda msgs, *_a, **_k: list(msgs)),
            patch.object(
                orchestrator, "run_tool", return_value={"ok": True, "context": ""}
            ),
            patch.object(orchestrator, "append_trace"),
            patch.object(orchestrator, "append_diary"),
        ):
            orchestrator._run_subagent(job)

        snapshot = state.get_job(job.id) or {}
        self.assertEqual(snapshot.get("state"), "failed")
        self.assertIn("step budget", snapshot.get("result") or "")

    def test_cancelled_worker_keeps_capacity_until_it_unwinds(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def hold(job: orchestrator.Job) -> None:
            entered.set()
            release.wait(timeout=3)
            if not job.cancel.is_set():
                state.update_job(job.id, state="done", progress="done", result="ok")

        with (
            patch.object(orchestrator, "_run_subagent", side_effect=hold),
            patch.object(orchestrator, "max_parallel_jobs", return_value=1),
        ):
            first = orchestrator.start_job("first")
            self.assertTrue(first["ok"])
            self.assertTrue(entered.wait(timeout=1))
            orchestrator.cancel_job(first["id"])
            second = orchestrator.start_job("second")
            self.assertFalse(second["ok"])
            self.assertEqual(second["reason"], "at_capacity")

            release.set()
            first_job = orchestrator._jobs[first["id"]]
            first_job.thread.join(timeout=2)
            third = orchestrator.start_job("third")
            self.assertTrue(third["ok"])
            orchestrator._jobs[third["id"]].thread.join(timeout=2)

        orchestrator.cancel_all()

    def test_unexpected_worker_return_is_marked_failed(self) -> None:
        with patch.object(orchestrator, "_run_subagent", return_value=None):
            started = orchestrator.start_job("return without result")
            self.assertTrue(started["ok"])
            orchestrator._jobs[started["id"]].thread.join(timeout=2)
        snapshot = state.get_job(started["id"]) or {}
        self.assertEqual(snapshot.get("state"), "failed")
        self.assertIn("without a terminal result", snapshot.get("result") or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Stability-fix regressions for rau/providers (P2–P8)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rau.providers.anthropic_compat as anthropic_compat  # noqa: E402
import rau.providers.openai_compat as openai_compat  # noqa: E402
from rau.providers.anthropic_compat import AnthropicCompatProvider  # noqa: E402
from rau.providers.base import Message, StreamDone, TextDelta  # noqa: E402
from rau.providers.openai_compat import (  # noqa: E402
    MAX_STREAM_LINE_BYTES,
    OpenAICompatProvider,
    _HTTPStatusError,
)


class _Reader:
    """readline() double honoring the size cap like a real buffered stream."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def readline(self, limit=-1):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        head, tail = chunk[:limit], chunk[limit:]
        if tail:
            self.chunks.insert(0, tail)
        return head


class StreamLineLimitTests(unittest.TestCase):
    """P4: a line of exactly MAX bytes + newline must be accepted."""

    def _check(self, module) -> None:
        exact = _Reader([b"x" * MAX_STREAM_LINE_BYTES + b"\n"])
        self.assertEqual(
            list(module._stream_lines(exact, "t")),
            [b"x" * MAX_STREAM_LINE_BYTES + b"\n"],
        )
        oversized = _Reader([b"x" * (MAX_STREAM_LINE_BYTES + 1) + b"\n"])
        with self.assertRaises(RuntimeError):
            list(module._stream_lines(oversized, "t"))

    def test_openai_stream_lines(self) -> None:
        self._check(openai_compat)

    def test_anthropic_stream_lines(self) -> None:
        self._check(anthropic_compat)


class FixedTemperatureTests(unittest.TestCase):
    """P2: catalog-flagged models must not send temperature with reasoning."""

    def test_strict_openai_models_drop_temperature(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        for provider, model in (
            ("openai", "gpt-5.6-sol"),
            ("codex", "gpt-5.5"),
            ("openrouter", "openai/gpt-5.6-terra"),
        ):
            payload = {"model": model, "temperature": 0.7}
            apply_reasoning_payload(payload, provider, model, "high")
            self.assertNotIn("temperature", payload, (provider, model))
            self.assertEqual(payload["reasoning_effort"], "high")

    def test_non_flagged_models_keep_temperature(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        for provider, model in (
            ("deepseek", "deepseek-v4-pro"),
            ("openrouter", "z-ai/glm-5.2"),
        ):
            payload = {"model": model, "temperature": 0.7}
            apply_reasoning_payload(payload, provider, model, "high")
            self.assertEqual(payload["temperature"], 0.7, (provider, model))

    def test_unsupported_model_keeps_temperature(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        payload = {"model": "gpt-5.6-luna", "temperature": 0.7}
        apply_reasoning_payload(payload, "openai", "gpt-5.6-luna", "high")
        self.assertEqual(payload["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", payload)


class KimiCodeReasoningTests(unittest.TestCase):
    """P3: kimi_code effort maps to the Anthropic thinking payload."""

    def test_kimi_code_builds_thinking_payload(self) -> None:
        from rau.providers.reasoning import build_reasoning_fields

        fields = build_reasoning_fields("kimi_code", "k3", "high")
        self.assertNotIn("reasoning_effort", fields)
        self.assertEqual(fields["thinking"]["type"], "enabled")
        self.assertIsInstance(fields["thinking"]["budget_tokens"], int)

    def test_kimi_code_apply_drops_temperature(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        payload = {"model": "k3", "temperature": 0.7}
        apply_reasoning_payload(payload, "kimi_code", "k3", "max")
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["thinking"]["budget_tokens"], 8192)

    def test_free_text_kimi_id_is_provider_aware(self) -> None:
        from rau.providers.catalog import reasoning_for

        self.assertEqual(
            reasoning_for("kimi_code", "kimi-for-coding-v9")["param"], "anthropic"
        )
        self.assertEqual(reasoning_for("kimi", "kimi-k9")["param"], "kimi")


class _SSEResponse:
    def __init__(self, lines):
        self.lines = list(lines)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def readline(self, _limit):
        if not self.lines:
            return b""
        return self.lines.pop(0)


def _openai_provider(lines) -> OpenAICompatProvider:
    provider = OpenAICompatProvider("openrouter", "https://example.test", "TEST_KEY")
    provider._key = lambda: "key"  # type: ignore[method-assign]
    provider._open = lambda *_args, **_kwargs: _SSEResponse(lines)  # type: ignore[method-assign]
    return provider


def _sse(chunk) -> bytes:
    return f"data: {json.dumps(chunk)}\n".encode()


class TruncatedToolCallTests(unittest.TestCase):
    """P5: a max_tokens-cut tool call must fail the turn, not execute."""

    def test_openai_length_finish_with_tool_call_raises(self) -> None:
        lines = [
            _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "c1",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"pa',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
            _sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
            b"data: [DONE]\n",
        ]
        with self.assertRaises(RuntimeError) as ctx:
            list(
                _openai_provider(lines).stream_turn(
                    [Message(role="user", content="x")], model="m"
                )
            )
        self.assertIn("truncated", str(ctx.exception))

    def test_openai_length_finish_without_tool_call_completes(self) -> None:
        lines = [
            _sse({"choices": [{"delta": {"content": "hi"}}]}),
            _sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
            b"data: [DONE]\n",
        ]
        events = list(
            _openai_provider(lines).stream_turn(
                [Message(role="user", content="x")], model="m"
            )
        )
        done = next(e for e in events if isinstance(e, StreamDone))
        self.assertEqual(done.result.content, "hi")

    def _anthropic_provider(self, lines) -> AnthropicCompatProvider:
        provider = AnthropicCompatProvider("kimi_code", "https://example.test", "TEST_KEY")
        provider._key = lambda: "key"  # type: ignore[method-assign]
        return provider

    def _run_anthropic(self, lines):
        provider = self._anthropic_provider(lines)
        with mock.patch(
            "urllib.request.urlopen", lambda *_a, **_k: _SSEResponse(lines)
        ):
            return list(
                provider.stream_turn([Message(role="user", content="x")], model="k3")
            )

    def test_anthropic_max_tokens_with_tool_call_raises(self) -> None:
        lines = [
            _sse(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "read_file",
                    },
                }
            ),
            _sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"pa'},
                }
            ),
            _sse({"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}),
            _sse({"type": "message_stop"}),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            self._run_anthropic(lines)
        self.assertIn("truncated", str(ctx.exception))

    def test_anthropic_tool_use_stop_completes(self) -> None:
        lines = [
            _sse(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "read_file",
                    },
                }
            ),
            _sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path": "README.md"}',
                    },
                }
            ),
            _sse({"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
            _sse({"type": "message_stop"}),
        ]
        events = self._run_anthropic(lines)
        done = next(e for e in events if isinstance(e, StreamDone))
        self.assertEqual(done.result.tool_calls[0].arguments, {"path": "README.md"})


class _JSONResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body


class StreamFallbackTests(unittest.TestCase):
    """P6: OpenAI-compat stream paths fall back to one blocking call."""

    def _provider(self, status: int) -> OpenAICompatProvider:
        provider = OpenAICompatProvider("openrouter", "https://example.test", "TEST_KEY")
        provider._key = lambda: "key"  # type: ignore[method-assign]

        def open_or_fail(req, timeout=0):
            payload = json.loads(req.data.decode())
            if payload.get("stream"):
                raise _HTTPStatusError(f"openrouter HTTP {status}: no stream", status)
            body = {"choices": [{"message": {"content": "blocking reply"}}]}
            return _JSONResponse(json.dumps(body).encode())

        provider._open = open_or_fail  # type: ignore[method-assign]
        return provider

    def test_chat_stream_falls_back(self) -> None:
        for status in (400, 404, 415, 501):
            out = self._provider(status).chat_stream(
                [Message(role="user", content="x")], model="m"
            )
            self.assertEqual("".join(out), "blocking reply", status)

    def test_stream_turn_falls_back(self) -> None:
        events = list(
            self._provider(400).stream_turn(
                [Message(role="user", content="x")], model="m"
            )
        )
        text = "".join(e.text for e in events if isinstance(e, TextDelta))
        done = next(e for e in events if isinstance(e, StreamDone))
        self.assertEqual(text, "blocking reply")
        self.assertEqual(done.result.content, "blocking reply")

    def test_non_fallback_status_reraises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            list(
                self._provider(401).stream_turn(
                    [Message(role="user", content="x")], model="m"
                )
            )
        self.assertIn("HTTP 401", str(ctx.exception))


class StatusAndSnapshotTests(unittest.TestCase):
    """P7/P8: provider_status and effort_snapshot cover all slots."""

    def test_provider_status_includes_media_and_browse(self) -> None:
        from rau.providers.registry import provider_status

        status = provider_status()
        self.assertEqual(status["deepgram"]["env"], "DEEPGRAM_API_KEY")
        self.assertEqual(status["firecrawl"]["env"], "FIRECRAWL_API_KEY")
        self.assertEqual(status["browserbase"]["env"], "BROWSERBASE_API_KEY")
        self.assertEqual(status["zai_code"]["env"], "ZAI_API_KEY")
        self.assertEqual(status["anthropic"]["env"], "ANTHROPIC_API_KEY")
        self.assertEqual(status["xai"]["env"], "XAI_API_KEY")
        self.assertEqual(status["gemini"]["env"], "GEMINI_API_KEY")
    def test_effort_snapshot_includes_player(self) -> None:
        from rau.providers.reasoning import effort_snapshot

        snap = effort_snapshot(
            {
                "face": {"provider": "kimi", "model": "kimi-k3", "effort": "high"},
                "player": {"provider": "kimi_code", "model": "k3", "effort": "low"},
            }
        )
        self.assertIn("player", snap["slots"])
        self.assertEqual(snap["player"], "low")
        self.assertEqual(snap["slots"]["player"]["param"], "anthropic")


if __name__ == "__main__":
    unittest.main()

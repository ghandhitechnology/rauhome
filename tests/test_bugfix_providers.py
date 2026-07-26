"""Bug-sweep regressions for rau/providers (see fix/bug-sweep)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.providers.anthropic_compat import _to_anthropic_messages  # noqa: E402
from rau.providers.base import Message, StreamDone, ToolCall, messages_to_openai  # noqa: E402
from rau.providers.openai_compat import OpenAICompatProvider  # noqa: E402


class _Response:
    """SSE response double; raises `exc` from readline once lines run out."""

    def __init__(self, lines, exc=None):
        self.lines = list(lines)
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def readline(self, _limit):
        if not self.lines:
            if self.exc is not None:
                raise self.exc
            return b""
        return self.lines.pop(0)


def _provider(lines, exc=None) -> OpenAICompatProvider:
    provider = OpenAICompatProvider("openrouter", "https://example.test", "TEST_KEY")
    provider._key = lambda: "key"  # type: ignore[method-assign]
    provider._open = lambda *_args, **_kwargs: _Response(lines, exc)  # type: ignore[method-assign]
    return provider


class KeepAliveStreamTests(unittest.TestCase):
    """Bare `data:` lines are SSE keep-alives and must not trip the malformed cap."""

    def test_chat_stream_survives_keepalives(self) -> None:
        lines = [b"data: \n"] * 20 + [
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
            b"data: [DONE]\n",
        ]
        out = _provider(lines).chat_stream(
            [Message(role="user", content="x")], model="m"
        )
        self.assertEqual("".join(out), "hi")

    def test_stream_turn_survives_keepalives(self) -> None:
        lines = [b"data:\n"] * 20 + [
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
            b"data: [DONE]\n",
        ]
        events = list(
            _provider(lines).stream_turn([Message(role="user", content="x")], model="m")
        )
        done = next(e for e in events if isinstance(e, StreamDone))
        self.assertEqual(done.result.content, "hi")


class MidStreamErrorTests(unittest.TestCase):
    """Mid-stream socket failures surface as RuntimeError, like connect-time ones."""

    def test_chat_stream_wraps_reset(self) -> None:
        lines = [b'data: {"choices":[{"delta":{"content":"he"}}]}\n']
        provider = _provider(lines, exc=ConnectionResetError(54, "reset by peer"))
        with self.assertRaises(RuntimeError) as ctx:
            list(provider.chat_stream([Message(role="user", content="x")], model="m"))
        self.assertIn("openrouter", str(ctx.exception))

    def test_stream_turn_wraps_reset(self) -> None:
        lines = [b'data: {"choices":[{"delta":{"content":"he"}}]}\n']
        provider = _provider(lines, exc=ConnectionResetError(54, "reset by peer"))
        with self.assertRaises(RuntimeError) as ctx:
            list(provider.stream_turn([Message(role="user", content="x")], model="m"))
        self.assertIn("openrouter", str(ctx.exception))

    def test_stream_turn_wraps_timeout(self) -> None:
        provider = _provider([], exc=TimeoutError("timed out"))
        with self.assertRaises(RuntimeError):
            list(provider.stream_turn([Message(role="user", content="x")], model="m"))


class ReasoningDetailsFormatTests(unittest.TestCase):
    """Foreign-format reasoning blocks are dropped after a provider switch."""

    def test_openai_drops_anthropic_blocks(self) -> None:
        encoded = messages_to_openai(
            [
                Message(
                    role="assistant",
                    content="hi",
                    reasoning_details=[
                        {"type": "thinking", "thinking": "x", "signature": "s"},
                        {"type": "reasoning.text", "text": "y"},
                        {"type": "reasoning.encrypted", "data": "z"},
                    ],
                )
            ]
        )
        self.assertEqual(
            encoded[0]["reasoning_details"],
            [
                {"type": "reasoning.text", "text": "y"},
                {"type": "reasoning.encrypted", "data": "z"},
            ],
        )

    def test_openai_tool_payload_drops_anthropic_blocks(self) -> None:
        encoded = messages_to_openai(
            [
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall("c1", "read_file", {})],
                    reasoning_details=[{"type": "redacted_thinking", "data": "q"}],
                ),
                Message(role="tool", content="ok", tool_call_id="c1"),
            ]
        )
        self.assertNotIn("reasoning_details", encoded[0])

    def test_anthropic_drops_openai_blocks(self) -> None:
        _system, encoded = _to_anthropic_messages(
            [
                Message(role="user", content="check"),
                Message(
                    role="assistant",
                    content="done",
                    reasoning_details=[
                        {"type": "reasoning.text", "text": "y"},
                        {"type": "reasoning.encrypted", "data": "z"},
                        {"type": "thinking", "thinking": "t", "signature": "s"},
                    ],
                ),
            ]
        )
        blocks = encoded[1]["content"]
        self.assertEqual(
            blocks,
            [
                {"type": "thinking", "thinking": "t", "signature": "s"},
                {"type": "text", "text": "done"},
            ],
        )

    def test_anthropic_tool_turn_drops_openai_blocks(self) -> None:
        _system, encoded = _to_anthropic_messages(
            [
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall("tool-1", "read_file", {})],
                    reasoning_details=[{"type": "reasoning.text", "text": "y"}],
                ),
                Message(role="tool", content="ok", tool_call_id="tool-1"),
            ]
        )
        assistant_blocks = encoded[1]["content"]
        self.assertTrue(all(b["type"] == "tool_use" for b in assistant_blocks))


if __name__ == "__main__":
    unittest.main()

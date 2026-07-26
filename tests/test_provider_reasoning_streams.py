from __future__ import annotations

import json

from rau.providers.anthropic_compat import (
    _parse_anthropic_result,
    _to_anthropic_messages,
)
from rau.providers.base import Message, ReasoningDelta, StreamDone, ToolCall
from rau.providers.openai_compat import OpenAICompatProvider


class _Response:
    def __init__(self, chunks):
        self.lines = [
            f"data: {json.dumps(chunk)}\n".encode()
            for chunk in chunks
        ] + [b"data: [DONE]\n"]
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def readline(self, _limit):
        if self.index >= len(self.lines):
            return b""
        line = self.lines[self.index]
        self.index += 1
        return line


def test_openrouter_readable_reasoning_and_fragmented_tool_calls():
    provider = OpenAICompatProvider("openrouter", "https://example.test", "TEST_KEY")
    provider._key = lambda: "key"  # type: ignore[method-assign]
    provider._open = lambda *_args, **_kwargs: _Response(  # type: ignore[method-assign]
        [
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "Inspecting "},
                                {
                                    "type": "reasoning.encrypted",
                                    "data": "never-public",
                                },
                            ],
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"pa',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "repository",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": 'th":"README.md"}'},
                                }
                            ],
                        }
                    }
                ]
            },
        ]
    )
    events = list(
        provider.stream_turn(
            [Message(role="user", content="read")],
            model="test",
            tools=[],
        )
    )
    readable = "".join(
        event.text for event in events if isinstance(event, ReasoningDelta)
    )
    assert readable == "Inspecting repository"
    assert "never-public" not in readable
    done = next(event for event in events if isinstance(event, StreamDone))
    assert done.result.tool_calls[0].arguments == {"path": "README.md"}
    assert done.result.reasoning_details is not None


def test_deepseek_reasoning_is_preserved_across_tool_round():
    message = Message(
        role="assistant",
        content="",
        reasoning="checked the repository",
        tool_calls=[ToolCall("call", "read_file", {"path": "README.md"})],
    )
    from rau.providers.base import messages_to_openai

    encoded = messages_to_openai(
        [
            message,
            Message(role="tool", content="ok", tool_call_id="call"),
        ]
    )
    assert encoded[0]["reasoning_content"] == "checked the repository"


def test_anthropic_thinking_signature_is_continuation_only():
    body = {
        "content": [
            {
                "type": "thinking",
                "thinking": "Checking the result",
                "signature": "opaque-signature",
            },
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "read_file",
                "input": {"path": "README.md"},
            },
        ]
    }
    result = _parse_anthropic_result(body)
    assert result.reasoning == "Checking the result"
    assert result.reasoning_details == [body["content"][0]]
    system, encoded = _to_anthropic_messages(
        [
            Message(role="user", content="check"),
            Message(
                role="assistant",
                content="",
                tool_calls=result.tool_calls,
                reasoning=result.reasoning,
                reasoning_details=result.reasoning_details,
            ),
            Message(role="tool", content="ok", tool_call_id="tool-1"),
        ]
    )
    assert system == ""
    assert encoded[1]["content"][0]["signature"] == "opaque-signature"

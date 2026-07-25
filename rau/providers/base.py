"""Unified chat provider interface."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, Iterable, List, Optional


@dataclass
class Message:
    role: str
    content: str
    #: Set on an assistant turn that asked for tools.
    tool_calls: Optional[List["ToolCall"]] = None
    #: Set on a role="tool" turn, binding the result back to the call it answers.
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResult:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None


# ── streaming events ──────────────────────────────────────────────────
# `stream_turn` yields these. The older `chat_stream` yields bare strings and
# cannot carry tool calls, which is why voice mode needs this richer channel:
# Rau has to be able to speak and fire off a job in the same turn.


@dataclass
class TextDelta:
    """A chunk of assistant prose, ready to speak."""

    text: str


@dataclass
class ToolCallDelta:
    """
    A fragment of a tool call. Providers stream `arguments` split across many
    chunks, so fragments must be concatenated per `index` before parsing.
    """

    index: int
    id: str = ""
    name: str = ""
    args_fragment: str = ""


@dataclass
class StreamDone:
    """Terminal event carrying the assembled result."""

    result: ChatResult


StreamEvent = Any  # TextDelta | ToolCallDelta | StreamDone


def assemble_tool_calls(parts: Dict[int, Dict[str, str]]) -> List[ToolCall]:
    """Turn accumulated ToolCallDelta fragments into finished ToolCalls."""
    out: List[ToolCall] = []
    for index in sorted(parts):
        part = parts[index]
        raw = part.get("args") or "{}"
        try:
            args = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            # A truncated stream can leave invalid JSON — surface it rather
            # than dropping the call silently.
            args = {"_raw": raw}
        out.append(
            ToolCall(
                id=part.get("id") or f"call_{index}",
                name=part.get("name") or "",
                arguments=args if isinstance(args, dict) else {"_raw": args},
            )
        )
    return [tc for tc in out if tc.name]


class ChatProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        effort: Optional[str] = None,
    ) -> ChatResult:
        raise NotImplementedError

    def chat_stream(
        self,
        messages: List[Message],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        effort: Optional[str] = None,
    ) -> Generator[str, None, str]:
        """Yield tokens; return full text."""
        result = self.chat(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            effort=effort,
        )
        if result.content:
            yield result.content
        return result.content

    def stream_turn(
        self,
        messages: List[Message],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        effort: Optional[str] = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        Stream one assistant turn as TextDelta / ToolCallDelta / StreamDone.

        This default falls back to a single blocking call, so a provider that
        cannot stream still works everywhere — it just arrives all at once.
        """
        result = self.chat(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            effort=effort,
        )
        if result.content:
            yield TextDelta(result.content)
        yield StreamDone(result)


#: One oversized tool payload can eat the whole context window, so the
#: serialized result is clamped before it ever reaches a wire encoder.
TOOL_RESULT_LIMIT = 12000


def tool_result_text(result: Any, limit: int = TOOL_RESULT_LIMIT) -> str:
    """Serialize a tool result for transport, clamped to `limit` characters."""
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(result)
    return text[:limit]


def orphan_tool_prose(m: Message) -> str:
    """
    Render a tool result whose call is missing.

    Both wire formats reject an unpaired result outright, so rather than drop
    what a tool actually returned it rides along as narration.
    """
    return f"[tool {m.name or 'result'}] {m.content}"


def pair_tool_calls(
    assistant: Message, results: List[Message]
) -> tuple[List[tuple[ToolCall, Message]], List[Message]]:
    """
    Match an assistant turn's tool calls against the results that answer them.

    A call left unanswered and a result with no call are both protocol errors,
    so anything that does not pair cleanly is handed back for demotion.
    """
    by_id = {m.tool_call_id: m for m in results if m.tool_call_id}
    paired = [(tc, by_id[tc.id]) for tc in assistant.tool_calls or [] if tc.id in by_id]
    matched = {tc.id for tc, _ in paired}
    return paired, [m for m in results if m.tool_call_id not in matched]


def messages_to_openai(messages: Iterable[Message]) -> List[Dict[str, Any]]:
    """
    Encode a conversation in OpenAI wire form.

    Tool plumbing has to survive exactly: a `tool` message is only accepted
    when its id appears in the `tool_calls` of the assistant turn directly
    above it, so pairs are resolved here and stragglers are turned into prose.
    """
    msgs = list(messages)
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(msgs):
        m = msgs[i]

        if m.role == "tool":
            # Reached outside a pair — the assistant turn that called it is gone.
            out.append({"role": "user", "content": orphan_tool_prose(m)})
            i += 1
            continue

        if m.role != "assistant" or not m.tool_calls:
            out.append({"role": m.role, "content": m.content})
            i += 1
            continue

        end = i + 1
        while end < len(msgs) and msgs[end].role == "tool":
            end += 1
        paired, orphans = pair_tool_calls(m, msgs[i + 1 : end])

        if paired:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc, _ in paired
                    ],
                }
            )
            # Every result has to land before any other role resumes.
            out.extend(
                {"role": "tool", "tool_call_id": tc.id, "content": res.content}
                for tc, res in paired
            )
        elif m.content:
            out.append({"role": "assistant", "content": m.content})

        out.extend({"role": "user", "content": orphan_tool_prose(o)} for o in orphans)
        i = end
    return out


def parse_tool_calls_openai(data: Dict[str, Any]) -> List[ToolCall]:
    out: List[ToolCall] = []
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        out.append(
            ToolCall(
                id=tc.get("id") or f"call_{len(out)}",
                name=fn.get("name") or "",
                arguments=args,
            )
        )
    return out

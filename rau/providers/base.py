"""Unified chat provider interface."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
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
    #: Optional images for multimodal tool results (e.g. CUA screenshots).
    #: Each entry: {"mime": "image/png", "b64": "..."}.
    images: Optional[List[Dict[str, str]]] = None


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


def normalize_tool_arguments(raw: Any) -> Dict[str, Any]:
    """Normalize provider tool input without ever guessing executable args."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    return {"_raw": raw}


def assemble_tool_calls(parts: Dict[int, Dict[str, str]]) -> List[ToolCall]:
    """Turn accumulated ToolCallDelta fragments into finished ToolCalls."""
    out: List[ToolCall] = []
    for index in sorted(parts):
        part = parts[index]
        raw = part.get("args") or "{}"
        args = normalize_tool_arguments(raw)
        out.append(
            ToolCall(
                id=part.get("id") or f"call_{index}",
                name=part.get("name") or "",
                arguments=args,
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

#: Keys that must never be JSON-dumped into a tool-result text blob.
_IMAGE_RESULT_KEYS = frozenset({"image_b64", "images"})


def tool_result_images(result: Any) -> List[Dict[str, str]]:
    """Extract image payloads from a CUA (or similar) tool result dict."""
    if not isinstance(result, dict):
        return []
    out: List[Dict[str, str]] = []
    b64 = result.get("image_b64")
    if isinstance(b64, str) and len(b64) > 200 and not b64.endswith("..."):
        mime = result.get("mime") if isinstance(result.get("mime"), str) else "image/png"
        out.append({"mime": mime or "image/png", "b64": b64})
    raw_images = result.get("images")
    if isinstance(raw_images, list):
        for img in raw_images:
            if not isinstance(img, dict):
                continue
            data = img.get("b64") or img.get("data")
            if isinstance(data, str) and len(data) > 200:
                mime = img.get("mime") if isinstance(img.get("mime"), str) else "image/png"
                out.append({"mime": mime or "image/png", "b64": data})
    return out


def tool_result_text(result: Any, limit: int = TOOL_RESULT_LIMIT) -> str:
    """Serialize a tool result for transport, clamped to `limit` characters.

    Image bytes are stripped — they travel on `Message.images` instead.
    """
    payload = result
    if isinstance(result, dict) and _IMAGE_RESULT_KEYS & set(result):
        payload = {
            key: value
            for key, value in result.items()
            if key not in _IMAGE_RESULT_KEYS
        }
        if "image_b64" in result and "image_b64_len" not in payload:
            b64 = result.get("image_b64")
            if isinstance(b64, str):
                payload["image_b64_len"] = len(b64)
        payload["has_image"] = bool(tool_result_images(result))
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]


def tool_message_content_openai(message: Message) -> Any:
    """OpenAI tool-message content: plain string, or text+image_url parts."""
    if not message.images:
        return message.content
    parts: List[Dict[str, Any]] = [{"type": "text", "text": message.content or ""}]
    for img in message.images:
        mime = img.get("mime") or "image/png"
        b64 = img.get("b64") or ""
        if not b64:
            continue
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )
    return parts if len(parts) > 1 else message.content


def tool_message_content_anthropic(message: Message) -> Any:
    """Anthropic tool_result content: string or text+image blocks."""
    if not message.images:
        return message.content
    parts: List[Dict[str, Any]] = [{"type": "text", "text": message.content or ""}]
    for img in message.images:
        mime = img.get("mime") or "image/png"
        b64 = img.get("b64") or ""
        if not b64:
            continue
        parts.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": b64,
                },
            }
        )
    return parts if len(parts) > 1 else message.content


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
    calls = list(assistant.tool_calls or [])
    call_counts = Counter(tc.id for tc in calls if tc.id)
    by_id: Dict[str, List[Message]] = defaultdict(list)
    for result in results:
        if result.tool_call_id:
            by_id[result.tool_call_id].append(result)

    paired: List[tuple[ToolCall, Message]] = []
    used: set[int] = set()
    for call in calls:
        matches = by_id.get(call.id) or []
        # Duplicate ids are ambiguous in either direction. Demote the result to
        # prose instead of silently pairing it to an arbitrary call.
        if call.id and call_counts[call.id] == 1 and len(matches) == 1:
            paired.append((call, matches[0]))
            used.add(id(matches[0]))
    return paired, [result for result in results if id(result) not in used]


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
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_message_content_openai(res),
                }
                for tc, res in paired
            )
        elif m.content:
            out.append({"role": "assistant", "content": m.content})

        out.extend({"role": "user", "content": orphan_tool_prose(o)} for o in orphans)
        i = end
    return out


def parse_tool_calls_openai(data: Dict[str, Any]) -> List[ToolCall]:
    out: List[ToolCall] = []
    if not isinstance(data, dict):
        return out
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, dict):
        return out
    msg = choice.get("message") or {}
    if not isinstance(msg, dict):
        return out
    calls = msg.get("tool_calls") or []
    if not isinstance(calls, list):
        return out
    for tc in calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        if not isinstance(fn, dict):
            continue
        args_raw = fn.get("arguments") or "{}"
        args = normalize_tool_arguments(args_raw)
        call_id = tc.get("id")
        name = fn.get("name")
        out.append(
            ToolCall(
                id=call_id if isinstance(call_id, str) and call_id else f"call_{len(out)}",
                name=name if isinstance(name, str) else "",
                arguments=args,
            )
        )
    return out

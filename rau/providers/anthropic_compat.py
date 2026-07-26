"""Anthropic-compatible HTTP chat (used for Kimi Coding Plan)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from rau.env import get_secret
from rau.providers.base import (
    ChatProvider,
    ChatResult,
    Message,
    ReasoningDelta,
    StreamDone,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    assemble_tool_calls,
    normalize_tool_arguments,
    orphan_tool_prose,
    pair_tool_calls,
    tool_message_content_anthropic,
)

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_STREAM_LINE_BYTES = 1024 * 1024
MAX_MALFORMED_STREAM_EVENTS = 16


def _stream_event(blob: str, malformed: int) -> tuple[Optional[Dict[str, Any]], int]:
    try:
        event = json.loads(blob)
    except json.JSONDecodeError:
        return None, malformed + 1
    if not isinstance(event, dict):
        return None, malformed + 1
    if event.get("type") == "error":
        error = event.get("error")
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"provider stream error: {message}")
    return event, malformed


def _event_index(value: Any) -> Optional[int]:
    try:
        index = int(value if value is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    return index if 0 <= index <= 1024 else None


def _malformed(name: str, count: int) -> int:
    count += 1
    if count > MAX_MALFORMED_STREAM_EVENTS:
        raise RuntimeError(f"{name} sent too many malformed stream events")
    return count


def _stream_lines(resp: Any, name: str):
    """Yield bounded SSE lines and cap the complete streaming response."""
    total = 0
    readline = getattr(resp, "readline", None)
    if callable(readline):
        while True:
            raw = readline(MAX_STREAM_LINE_BYTES + 1)
            if not raw:
                return
            if len(raw) > MAX_STREAM_LINE_BYTES or (
                len(raw) == MAX_STREAM_LINE_BYTES + 1
                and not raw.endswith((b"\n", b"\r"))
            ):
                raise RuntimeError(
                    f"{name} stream line exceeded {MAX_STREAM_LINE_BYTES} bytes"
                )
            total += len(raw)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    f"{name} stream exceeded {MAX_RESPONSE_BYTES} bytes"
                )
            yield raw
        return

    for raw in resp:
        if len(raw) > MAX_STREAM_LINE_BYTES:
            raise RuntimeError(
                f"{name} stream line exceeded {MAX_STREAM_LINE_BYTES} bytes"
            )
        total += len(raw)
        if total > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"{name} stream exceeded {MAX_RESPONSE_BYTES} bytes")
        yield raw


def _anthropic_reasoning_blocks(
    details: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Keep only Anthropic thinking blocks from a reasoning continuation.

    Blocks in a foreign format (e.g. OpenRouter `reasoning_details` after a
    mid-conversation provider switch) would be rejected as unknown content
    block types, so they are dropped before they can break the request.
    """
    return [
        item
        for item in details or []
        if isinstance(item, dict)
        and item.get("type") in {"thinking", "redacted_thinking"}
    ]


def _push(out: List[Dict[str, Any]], role: str, blocks: List[Dict[str, Any]]) -> None:
    """
    Add blocks as `role`, merging into the previous turn when roles repeat.

    Merging is done on block lists rather than joined strings: collapsing two
    turns into text would destroy the tool_use/tool_result pairing that has to
    reach the model intact.
    """
    if not blocks:
        return
    if out and out[-1]["role"] == role:
        out[-1]["content"].extend(blocks)
        return
    out.append({"role": role, "content": list(blocks)})


def _to_anthropic_messages(messages: List[Message]) -> tuple[str, List[Dict[str, Any]]]:
    """
    Split off the system prompt and encode the rest as Anthropic content blocks.

    Anthropic answers a tool_use only if the very next user turn opens with its
    tool_result, so pairs are resolved together and emitted adjacently; a
    result with no call is demoted to text before it can break that contract.
    """
    msgs = list(messages)
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    i = 0
    while i < len(msgs):
        m = msgs[i]

        if m.role == "system":
            system_parts.append(m.content)
            i += 1
            continue

        if m.role == "tool":
            _push(out, "user", [{"type": "text", "text": orphan_tool_prose(m)}])
            i += 1
            continue

        if m.role == "assistant" and m.tool_calls:
            end = i + 1
            while end < len(msgs) and msgs[end].role == "tool":
                end += 1
            paired, orphans = pair_tool_calls(m, msgs[i + 1 : end])

            blocks: List[Dict[str, Any]] = _anthropic_reasoning_blocks(m.reasoning_details)
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks += [
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                for tc, _ in paired
            ]
            _push(out, "assistant", blocks)

            answers: List[Dict[str, Any]] = [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": tool_message_content_anthropic(res),
                }
                for tc, res in paired
            ]
            answers += [
                {"type": "text", "text": orphan_tool_prose(o)} for o in orphans
            ]
            _push(out, "user", answers)
            i = end
            continue

        role = "assistant" if m.role == "assistant" else "user"
        blocks = _anthropic_reasoning_blocks(m.reasoning_details) if role == "assistant" else []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        if blocks:
            _push(out, role, blocks)
        i += 1

    # Anthropic requires alternating starting with user
    if out and out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continue)"}]})
    return "\n\n".join(system_parts).strip(), out


def _openai_tools_to_anthropic(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = (t.get("function") or t) if t.get("type") == "function" else t
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not name:
            continue
        out.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters")
                or fn.get("input_schema")
                or {"type": "object", "properties": {}},
            }
        )
    return out


def _parse_anthropic_result(body: Dict[str, Any]) -> ChatResult:
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    reasoning_blocks: List[Dict[str, Any]] = []
    tool_calls: List[ToolCall] = []
    if not isinstance(body, dict):
        raise RuntimeError("provider returned non-object JSON")
    error = body.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"provider error: {message}")
    blocks = body.get("content") or []
    if not isinstance(blocks, list):
        raise RuntimeError("provider content must be an array")
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if isinstance(text, str):
                text_parts.append(text)
        elif btype in {"thinking", "redacted_thinking"}:
            # Preserve the complete block for Anthropic's next tool round.
            reasoning_blocks.append(dict(block))
            if btype == "thinking":
                thought = block.get("thinking") or ""
                if isinstance(thought, str):
                    reasoning_parts.append(thought)
        elif btype == "tool_use":
            call_id = block.get("id")
            name = block.get("name")
            tool_calls.append(
                ToolCall(
                    id=(
                        call_id
                        if isinstance(call_id, str) and call_id
                        else f"tool_{len(tool_calls)}"
                    ),
                    name=name if isinstance(name, str) else "",
                    arguments=normalize_tool_arguments(block.get("input") or {}),
                )
            )
    return ChatResult(
        content="".join(text_parts).strip(),
        tool_calls=tool_calls,
        reasoning="".join(reasoning_parts).strip(),
        reasoning_details=reasoning_blocks or None,
        raw=body,
    )


class AnthropicCompatProvider(ChatProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key_env: str,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.default_headers = default_headers or {}

    def _key(self) -> str:
        return get_secret(self.api_key_env)

    def available(self) -> bool:
        return bool(self._key())

    def _headers(self, key: str, streaming: bool = False) -> Dict[str, str]:
        headers = {
            "x-api-key": key,
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            **self.default_headers,
        }
        if streaming:
            headers["Accept"] = "text/event-stream"
        return headers

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
        key = self._key()
        if not key:
            raise RuntimeError(f"{self.api_key_env} not set for provider {self.name}")

        system, anth_messages = _to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
        }
        if system:
            payload["system"] = system
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)
        anth_tools = _openai_tools_to_anthropic(tools)
        if anth_tools:
            payload["tools"] = anth_tools

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=data,
            headers=self._headers(key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    f"{self.name} response exceeded {MAX_RESPONSE_BYTES} bytes"
                )
            body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read(4000).decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {e.code}: {err}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"{self.name} is unreachable: {e.reason}") from e
        except OSError as e:
            raise RuntimeError(f"{self.name} connection failed: {e}") from e
        except (UnicodeError, json.JSONDecodeError) as e:
            raise RuntimeError(f"{self.name} returned invalid JSON") from e

        return _parse_anthropic_result(body)

    def chat_stream(
        self,
        messages: List[Message],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        effort: Optional[str] = None,
    ) -> Generator[str, None, str]:
        key = self._key()
        if not key:
            raise RuntimeError(f"{self.api_key_env} not set for provider {self.name}")

        system, anth_messages = _to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
            "stream": True,
        }
        if system:
            payload["system"] = system
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=data,
            headers=self._headers(key, streaming=True),
            method="POST",
        )
        accum: List[str] = []
        malformed = 0
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for raw in _stream_lines(resp, self.name):
                    line = raw.decode("utf-8", errors="ignore").rstrip("\n")
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:") :].strip()
                    if not payload_str or payload_str == "[DONE]":
                        continue
                    event, malformed = _stream_event(payload_str, malformed)
                    if malformed > MAX_MALFORMED_STREAM_EVENTS:
                        raise RuntimeError(
                            f"{self.name} sent too many malformed stream events"
                        )
                    if event is None:
                        continue
                    etype = event.get("type")
                    if etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        if not isinstance(delta, dict):
                            malformed = _malformed(self.name, malformed)
                            continue
                        token = delta.get("text") or ""
                        if isinstance(token, str) and token:
                            accum.append(token)
                            yield token
                    elif etype == "message_delta":
                        pass
        except urllib.error.HTTPError as e:
            # Fall back to non-stream if streaming unsupported
            err = e.read(4000).decode("utf-8", errors="replace")
            if e.code in (400, 404, 415, 501):
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
            raise RuntimeError(f"{self.name} HTTP {e.code}: {err}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"{self.name} is unreachable: {e.reason}") from e
        except OSError as e:
            raise RuntimeError(f"{self.name} connection failed: {e}") from e

        return "".join(accum)

    def stream_turn(
        self,
        messages: List[Message],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        effort: Optional[str] = None,
    ) -> Generator[Any, None, None]:
        """Stream prose and tool_use blocks together."""
        key = self._key()
        if not key:
            raise RuntimeError(f"{self.api_key_env} not set for provider {self.name}")

        system, anth_messages = _to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = _openai_tools_to_anthropic(tools)
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)

        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(key, streaming=True),
            method="POST",
        )

        text: List[str] = []
        parts: Dict[int, Dict[str, str]] = {}
        reasoning: List[str] = []
        reasoning_blocks: Dict[int, Dict[str, Any]] = {}
        malformed = 0

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for raw in _stream_lines(resp, self.name):
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    blob = line[len("data:") :].strip()
                    if not blob or blob == "[DONE]":
                        continue
                    event, malformed = _stream_event(blob, malformed)
                    if malformed > MAX_MALFORMED_STREAM_EVENTS:
                        raise RuntimeError(
                            f"{self.name} sent too many malformed stream events"
                        )
                    if event is None:
                        continue

                    etype = event.get("type")
                    idx = _event_index(event.get("index"))
                    if idx is None:
                        malformed = _malformed(self.name, malformed)
                        continue

                    if etype == "content_block_start":
                        block = event.get("content_block") or {}
                        if not isinstance(block, dict):
                            malformed = _malformed(self.name, malformed)
                            continue
                        if block.get("type") in {"thinking", "redacted_thinking"}:
                            reasoning_blocks[idx] = dict(block)
                        elif block.get("type") == "tool_use":
                            # Anthropic announces name/id up front, then streams
                            # the arguments as partial JSON fragments.
                            block_id = block.get("id")
                            block_name = block.get("name")
                            parts[idx] = {
                                "id": block_id if isinstance(block_id, str) else "",
                                "name": block_name if isinstance(block_name, str) else "",
                                "args": "",
                            }
                            yield ToolCallDelta(
                                index=idx,
                                id=block_id if isinstance(block_id, str) else "",
                                name=block_name if isinstance(block_name, str) else "",
                            )
                    elif etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        if not isinstance(delta, dict):
                            malformed = _malformed(self.name, malformed)
                            continue
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            token = delta.get("text") or ""
                            if isinstance(token, str) and token:
                                text.append(token)
                                yield TextDelta(token)
                        elif dtype == "thinking_delta":
                            thought = delta.get("thinking") or ""
                            if isinstance(thought, str) and thought:
                                reasoning.append(thought)
                                slot = reasoning_blocks.setdefault(
                                    idx, {"type": "thinking", "thinking": ""}
                                )
                                slot["thinking"] = (
                                    str(slot.get("thinking") or "") + thought
                                )
                                yield ReasoningDelta(thought, "anthropic")
                        elif dtype == "signature_delta":
                            # Required for a later tool continuation, but never
                            # emitted to the public activity plane.
                            signature = delta.get("signature") or ""
                            if isinstance(signature, str) and signature:
                                slot = reasoning_blocks.setdefault(
                                    idx, {"type": "thinking", "thinking": ""}
                                )
                                slot["signature"] = (
                                    str(slot.get("signature") or "") + signature
                                )
                        elif dtype == "input_json_delta":
                            frag = delta.get("partial_json") or ""
                            if isinstance(frag, str) and frag:
                                slot = parts.setdefault(
                                    idx, {"id": "", "name": "", "args": ""}
                                )
                                slot["args"] += frag
                                yield ToolCallDelta(index=idx, args_fragment=frag)
                            elif frag:
                                malformed = _malformed(self.name, malformed)
        except urllib.error.HTTPError as e:
            err = e.read(4000).decode("utf-8", errors="replace")
            if e.code in (400, 404, 415, 501):
                # Streaming unsupported — fall back to one blocking call.
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
                return
            raise RuntimeError(f"{self.name} HTTP {e.code}: {err}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"{self.name} is unreachable: {e.reason}") from e
        except OSError as e:
            raise RuntimeError(f"{self.name} connection failed: {e}") from e

        yield StreamDone(
            ChatResult(
                content="".join(text).strip(),
                tool_calls=assemble_tool_calls(parts),
                reasoning="".join(reasoning).strip(),
                reasoning_details=[
                    reasoning_blocks[index] for index in sorted(reasoning_blocks)
                ]
                or None,
            )
        )

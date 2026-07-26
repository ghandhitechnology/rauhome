"""OpenAI-compatible HTTP chat (OpenRouter, DeepSeek, Kimi, Codex-compatible)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional  # noqa: F401 — Optional used in signatures

from rau.env import get_secret
from rau.providers.base import (
    ChatProvider,
    ChatResult,
    Message,
    ReasoningDelta,
    StreamDone,
    TextDelta,
    ToolCallDelta,
    assemble_tool_calls,
    messages_to_openai,
    parse_tool_calls_openai,
)


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_STREAM_LINE_BYTES = 1024 * 1024
MAX_MALFORMED_STREAM_EVENTS = 16
_STANDARD_URL_OPEN = urllib.request.urlopen


def _readable_reasoning(delta: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    """Normalize OpenRouter/OpenAI/DeepSeek reasoning without exposing opaque data."""
    text_parts: List[str] = []
    direct = delta.get("reasoning_content")
    if not isinstance(direct, str):
        direct = delta.get("reasoning")
    if isinstance(direct, str) and direct:
        text_parts.append(direct)
    details = delta.get("reasoning_details")
    internal = details if isinstance(details, list) else []
    for item in internal:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if "encrypted" in kind:
            continue
        candidate = item.get("text")
        if not isinstance(candidate, str):
            candidate = item.get("summary")
        if isinstance(candidate, str) and candidate:
            text_parts.append(candidate)
    # Some OpenRouter providers mirror the same readable text in both the
    # convenience field and reasoning_details. Avoid a duplicated timeline.
    return "".join(dict.fromkeys(text_parts)), list(internal)


def _choice_delta(chunk: Any) -> Dict[str, Any]:
    if not isinstance(chunk, dict):
        return {}
    error = chunk.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"provider stream error: {message}")
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    if not isinstance(choice, dict):
        return {}
    delta = choice.get("delta") or {}
    return delta if isinstance(delta, dict) else {}


def _tool_index(value: Any) -> Optional[int]:
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
    """Iterate response lines without letting readline or the stream grow forever."""
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

    # Test doubles and unusual response adapters may only be iterable. The
    # aggregate remains bounded even though only urllib's readline path can
    # prevent allocation of an oversized individual line before it is yielded.
    for raw in resp:
        if len(raw) > MAX_STREAM_LINE_BYTES:
            raise RuntimeError(
                f"{name} stream line exceeded {MAX_STREAM_LINE_BYTES} bytes"
            )
        total += len(raw)
        if total > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"{name} stream exceeded {MAX_RESPONSE_BYTES} bytes")
        yield raw


class OpenAICompatProvider(ChatProvider):
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
        # Shared opener so warm + turns reuse the same handler stack.
        self._opener = urllib.request.build_opener()

    def _key(self) -> str:
        return get_secret(self.api_key_env)

    def available(self) -> bool:
        return bool(self._key())

    def warm(self) -> None:
        """Cheap TLS/handshake touch so the first stream_turn is not cold."""
        key = self._key()
        if not key:
            return
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={
                "Authorization": f"Bearer {key}",
                **self.default_headers,
            },
            method="GET",
        )
        try:
            with self._open(req, timeout=8) as resp:
                resp.read(512)
        except Exception:
            # Warmth is nicety; a failed probe must never block voice connect.
            pass

    def _open(self, req: urllib.request.Request, timeout: float):
        try:
            # Retain the warm shared opener in production while respecting
            # test/integration transports that replace urllib.request.urlopen.
            transport = (
                urllib.request.urlopen
                if urllib.request.urlopen is not _STANDARD_URL_OPEN
                else self._opener.open
            )
            return transport(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} is unreachable: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"{self.name} connection failed: {exc}") from exc

    def _read_json(self, resp) -> Dict[str, Any]:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"{self.name} response exceeded {MAX_RESPONSE_BYTES} bytes")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{self.name} returned an invalid JSON response") from exc
        if not isinstance(body, dict):
            raise RuntimeError(f"{self.name} returned an unexpected response shape")
        return body

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

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_openai(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            **self.default_headers,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        with self._open(req, timeout=120) as resp:
            body = self._read_json(resp)

        error = body.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"{self.name} provider error: {message}")
        choices = body.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else {}
        msg = choice.get("message") if isinstance(choice, dict) else {}
        msg = msg if isinstance(msg, dict) else {}
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        reasoning, reasoning_details = _readable_reasoning(msg)
        return ChatResult(
            content=content,
            tool_calls=parse_tool_calls_openai(body),
            reasoning=reasoning,
            reasoning_details=reasoning_details or None,
            raw=body,
        )

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

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_openai(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **self.default_headers,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        accum: List[str] = []
        malformed = 0
        try:
            with self._open(req, timeout=120) as resp:
                for raw in _stream_lines(resp, self.name):
                    line = raw.decode("utf-8", errors="ignore").rstrip("\n")
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:") :].strip()
                    # Bare "data:" lines are keep-alives, not malformed events.
                    if not payload_str:
                        continue
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        malformed = _malformed(self.name, malformed)
                        continue
                    delta = _choice_delta(chunk)
                    token = delta.get("content") or ""
                    if isinstance(token, str) and token:
                        accum.append(token)
                        yield token
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
        """Stream prose and tool calls together over SSE."""
        key = self._key()
        if not key:
            raise RuntimeError(f"{self.api_key_env} not set for provider {self.name}")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_openai(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        from rau.providers.reasoning import apply_reasoning_payload

        apply_reasoning_payload(payload, self.name, model, effort)

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                **self.default_headers,
            },
            method="POST",
        )

        text: List[str] = []
        # index -> {"id", "name", "args"}; `arguments` arrives in fragments and
        # is only valid JSON once the whole call has streamed in.
        parts: Dict[int, Dict[str, str]] = {}
        reasoning: List[str] = []
        reasoning_details: List[Dict[str, Any]] = []
        malformed = 0

        try:
            with self._open(req, timeout=120) as resp:
                for raw in _stream_lines(resp, self.name):
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    blob = line[len("data:") :].strip()
                    # Bare "data:" lines are keep-alives, not malformed events.
                    if not blob:
                        continue
                    if blob == "[DONE]":
                        break
                    try:
                        chunk = json.loads(blob)
                    except json.JSONDecodeError:
                        malformed = _malformed(self.name, malformed)
                        continue

                    delta = _choice_delta(chunk)

                    thought, continuation = _readable_reasoning(delta)
                    if continuation:
                        reasoning_details.extend(continuation)
                    if thought:
                        reasoning.append(thought)
                        yield ReasoningDelta(
                            thought,
                            "deepseek"
                            if self.name == "deepseek"
                            else "openrouter",
                        )

                    token = delta.get("content") or ""
                    if isinstance(token, str) and token:
                        text.append(token)
                        yield TextDelta(token)

                    calls = delta.get("tool_calls") or []
                    if not isinstance(calls, list):
                        malformed = _malformed(self.name, malformed)
                        continue
                    for tc in calls:
                        if not isinstance(tc, dict):
                            malformed = _malformed(self.name, malformed)
                            continue
                        # Some providers omit `index` when there is only one call.
                        idx = _tool_index(tc.get("index"))
                        if idx is None:
                            malformed = _malformed(self.name, malformed)
                            continue
                        fn = tc.get("function") or {}
                        if not isinstance(fn, dict):
                            malformed = _malformed(self.name, malformed)
                            continue
                        slot = parts.setdefault(idx, {"id": "", "name": "", "args": ""})
                        tc_id = tc.get("id")
                        tc_id = tc_id if isinstance(tc_id, str) else ""
                        fn_name = fn.get("name")
                        fn_name = fn_name if isinstance(fn_name, str) else ""
                        if tc_id:
                            slot["id"] = tc_id
                        if fn_name:
                            slot["name"] = fn_name
                        frag = fn.get("arguments") or ""
                        if isinstance(frag, str) and frag:
                            slot["args"] += frag
                        elif frag:
                            malformed = _malformed(self.name, malformed)
                            continue
                        yield ToolCallDelta(
                            index=idx,
                            id=tc_id,
                            name=fn_name,
                            args_fragment=frag if isinstance(frag, str) else "",
                        )
        except urllib.error.URLError as e:
            raise RuntimeError(f"{self.name} is unreachable: {e.reason}") from e
        except OSError as e:
            raise RuntimeError(f"{self.name} connection failed: {e}") from e

        yield StreamDone(
            ChatResult(
                content="".join(text).strip(),
                tool_calls=assemble_tool_calls(parts),
                reasoning="".join(reasoning).strip(),
                reasoning_details=reasoning_details or None,
            )
        )


PROVIDERS: Dict[str, ChatProvider] = {
    "openrouter": OpenAICompatProvider(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        default_headers={
            "HTTP-Referer": "http://127.0.0.1:8765",
            "X-Title": "Rau",
        },
    ),
    "deepseek": OpenAICompatProvider(
        "deepseek",
        "https://api.deepseek.com/v1",
        "DEEPSEEK_API_KEY",
    ),
    "kimi": OpenAICompatProvider(
        "kimi",
        "https://api.moonshot.ai/v1",
        "KIMI_API_KEY",
    ),
    # Alias for moonshot.ai platform
    "moonshot": OpenAICompatProvider(
        "moonshot",
        "https://api.moonshot.ai/v1",
        "KIMI_API_KEY",
    ),
    "codex": OpenAICompatProvider(
        "codex",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
    ),
    # Alias for clarity in UI
    "openai": OpenAICompatProvider(
        "openai",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
    ),
}

# Kimi Coding Plan (membership) — Anthropic-compatible, not Moonshot pay-as-you-go
from rau.providers.anthropic_compat import AnthropicCompatProvider  # noqa: E402

PROVIDERS["kimi_code"] = AnthropicCompatProvider(
    "kimi_code",
    "https://api.kimi.com/coding",
    "KIMI_CODING_API_KEY",
)
# Friendly aliases for the UI / config
PROVIDERS["kimi-code"] = PROVIDERS["kimi_code"]
PROVIDERS["kimi_coding"] = PROVIDERS["kimi_code"]

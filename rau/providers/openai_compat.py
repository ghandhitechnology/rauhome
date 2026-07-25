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
    StreamDone,
    TextDelta,
    ToolCallDelta,
    assemble_tool_calls,
    messages_to_openai,
    parse_tool_calls_openai,
)


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

    def _key(self) -> str:
        return get_secret(self.api_key_env)

    def available(self) -> bool:
        return bool(self._key())

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
        if effort:
            # OpenAI o-series / compatible gateways
            payload["reasoning_effort"] = effort if effort != "medium" else "medium"
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
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {e.code}: {err}") from e

        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        return ChatResult(
            content=content,
            tool_calls=parse_tool_calls_openai(body),
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
        if effort:
            payload["reasoning_effort"] = effort
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").rstrip("\n")
                if not line.startswith("data:"):
                    continue
                payload_str = line[len("data:") :].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                token = delta.get("content") or ""
                if token:
                    accum.append(token)
                    yield token
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
        if effort:
            payload["reasoning_effort"] = effort

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

        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                blob = line[len("data:") :].strip()
                if blob == "[DONE]":
                    break
                try:
                    chunk = json.loads(blob)
                except json.JSONDecodeError:
                    continue

                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}

                token = delta.get("content") or ""
                if token:
                    text.append(token)
                    yield TextDelta(token)

                for tc in delta.get("tool_calls") or []:
                    # Some providers omit `index` when there is only one call.
                    idx = int(tc.get("index") or 0)
                    fn = tc.get("function") or {}
                    slot = parts.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    frag = fn.get("arguments") or ""
                    if frag:
                        slot["args"] += frag
                    yield ToolCallDelta(
                        index=idx,
                        id=tc.get("id") or "",
                        name=fn.get("name") or "",
                        args_fragment=frag,
                    )

        yield StreamDone(
            ChatResult(
                content="".join(text).strip(),
                tool_calls=assemble_tool_calls(parts),
            )
        )


PROVIDERS = {
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


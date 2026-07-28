"""Provider failure classification and a small per-provider circuit breaker."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Generator, List, Optional

from rau.providers.base import ChatProvider, ChatResult, Message


def transient_provider_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "timeout",
            "timed out",
            "unreachable",
            "connection",
            "temporar",
            "overloaded",
            "rate limit",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
        )
    )


class CircuitBreakerProvider(ChatProvider):
    threshold = 3
    cooldown_sec = 60.0

    def __init__(self, inner: ChatProvider):
        self.inner = inner
        self.name = inner.name
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def _before(self) -> None:
        with self._lock:
            if self._open_until > time.monotonic():
                remaining = self._open_until - time.monotonic()
                raise RuntimeError(
                    f"{self.name} provider circuit is open for {remaining:.1f}s"
                )

    def _success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def _failure(self, error: BaseException) -> None:
        if not transient_provider_error(error):
            return
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._open_until = time.monotonic() + self.cooldown_sec

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
        self._before()
        try:
            result = self.inner.chat(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tools,
                effort=effort,
            )
        except Exception as exc:
            self._failure(exc)
            raise
        self._success()
        return result

    def chat_stream(self, messages: List[Message], **kwargs: Any) -> Generator[str, None, str]:
        self._before()
        generator = self.inner.chat_stream(messages, **kwargs)
        try:
            while True:
                try:
                    yield next(generator)
                except StopIteration as stop:
                    self._success()
                    return str(stop.value or "")
        except GeneratorExit:
            close = getattr(generator, "close", None)
            if close:
                close()
            raise
        except Exception as exc:
            self._failure(exc)
            raise

    def stream_turn(self, messages: List[Message], **kwargs: Any):
        self._before()
        generator = self.inner.stream_turn(messages, **kwargs)
        try:
            for event in generator:
                yield event
            self._success()
        except GeneratorExit:
            close = getattr(generator, "close", None)
            if close:
                close()
            raise
        except Exception as exc:
            self._failure(exc)
            raise

    def warm(self) -> None:
        warm = getattr(self.inner, "warm", None)
        if callable(warm):
            warm()

    def warm_hyper(self) -> None:
        warm = getattr(self.inner, "warm_hyper", None)
        if callable(warm):
            warm()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "failures": self._failures,
                "open": self._open_until > time.monotonic(),
                "open_until_monotonic": self._open_until,
            }

"""Small persistent streaming transport used by Hyper voice turns."""
from __future__ import annotations

from typing import Any, Dict, Iterator, Optional


class PooledStatusError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def make_client():
    import httpx

    limits = httpx.Limits(
        max_connections=8,
        max_keepalive_connections=4,
        keepalive_expiry=45.0,
    )
    try:
        return httpx.Client(http2=True, limits=limits)
    except ImportError:
        # The optional ``h2`` wheel may be absent in a minimal install.
        return httpx.Client(http2=False, limits=limits)


class PooledLineResponse:
    """Context-managed httpx stream exposing byte lines like urllib."""

    def __init__(
        self,
        client,
        *,
        method: str,
        url: str,
        headers: Dict[str, str],
        content: Optional[bytes],
        timeout: float,
    ) -> None:
        self.client = client
        self.method = method
        self.url = url
        self.headers = headers
        self.content = content
        self.timeout = timeout
        self._context: Any = None
        self._response: Any = None

    def __enter__(self):
        import httpx

        self._context = self.client.stream(
            self.method,
            self.url,
            headers=self.headers,
            content=self.content,
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
        )
        self._response = self._context.__enter__()
        if self._response.status_code >= 400:
            detail = self._response.read()[:4000].decode(
                "utf-8", errors="replace"
            )
            status = int(self._response.status_code)
            self._context.__exit__(None, None, None)
            self._context = None
            raise PooledStatusError(status, detail)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._context is not None:
            return self._context.__exit__(exc_type, exc, tb)
        return None

    def __iter__(self) -> Iterator[bytes]:
        if self._response is None:
            return
        for line in self._response.iter_lines():
            yield (line + "\n").encode("utf-8")


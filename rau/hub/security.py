"""Browser-origin and Host protections for the privileged local hub."""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
WILDCARD_BINDS = {"", "0.0.0.0", "::", "[::]"}


def _hostname(authority: str) -> str:
    value = str(authority or "").strip().lower()
    if not value:
        return ""
    try:
        # urlsplit handles bracketed IPv6 and ports correctly.
        return (urlsplit(f"//{value}").hostname or "").rstrip(".")
    except ValueError:
        return ""


def allowed_hostnames(configured_host: str, extra: Iterable[str] = ()) -> set[str]:
    allowed = set(LOOPBACK_NAMES)
    candidate = _hostname(configured_host)
    if candidate and candidate not in WILDCARD_BINDS:
        allowed.add(candidate)
    for value in extra:
        candidate = _hostname(value)
        if candidate and candidate not in WILDCARD_BINDS:
            allowed.add(candidate)
    return allowed


def host_allowed(authority: str, allowed: set[str]) -> bool:
    host = _hostname(authority)
    return bool(host) and host in allowed


def origin_allowed(origin: str, request_host: str, request_scheme: str = "http") -> bool:
    """Allow non-browser clients or an exact same-origin browser request."""
    value = str(origin or "").strip()
    if not value:
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.scheme != str(request_scheme or "http").lower():
        return False
    # Compare complete authorities, including ports. Vite's development proxy
    # preserves both at 5173; production serves both API and UI from 8765.
    return parsed.netloc.lower().rstrip(".") == str(request_host or "").lower().rstrip(".")


class LocalAccessMiddleware:
    """Reject DNS rebinding and cross-site requests before routes or WS accept."""

    def __init__(self, app, *, allowed_hosts: set[str]):
        self.app = app
        self.allowed_hosts = set(allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        host = headers.get("host", "")
        safe = host_allowed(host, self.allowed_hosts)
        safe = safe and origin_allowed(
            headers.get("origin", ""), host, str(scope.get("scheme") or "http")
        )
        safe = safe and headers.get("sec-fetch-site", "").lower() != "cross-site"
        if safe:
            await self.app(scope, receive, send)
            return

        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "untrusted origin"})
            return
        body = b'{"ok":false,"error":"untrusted host or origin"}'
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

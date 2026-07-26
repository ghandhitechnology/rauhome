"""
Browserbase: a real Chrome in someone else's data centre, driven over CDP.

Slower and dearer than scraping, and worth it exactly when the page will not
give up its content to anything that does not run its JavaScript — an app
behind a client-side router, a dashboard, anything that ships an empty <body>
and fills it in later.

Two things this file is careful about:

  * **Sessions are billed by the minute.** Every one is explicitly released in
    a `finally`, so a failure part way through costs one page load rather than
    a browser idling until its timeout.
  * **CDP is a stream of events with replies mixed in.** Replies are matched by
    id and everything else is skipped, so an unsolicited `Page.frameNavigated`
    cannot be mistaken for the answer to the question we asked.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from rau.browse.base import (
    BrowseError,
    BrowseProvider,
    Page,
    clamp_timeout,
    normalise_url,
    post_json,
)
from rau.env import get_secret

API_ROOT = "https://api.browserbase.com/v1"
ENV_KEY = "BROWSERBASE_API_KEY"
PROJECT_ENV = "BROWSERBASE_PROJECT_ID"

#: Pulled out of the page once it has settled. `innerText` rather than
#: `textContent` so it reflects what is actually visible, and the main content
#: is preferred over the chrome around it.
_EXTRACT = """
(() => {
  const pick = document.querySelector('main, article, [role=main]') || document.body
  const text = (pick && pick.innerText) || ''
  const links = Array.from(document.querySelectorAll('a[href]'))
    .map((a) => a.href)
    .filter((h) => h.startsWith('http'))
  return JSON.stringify({
    title: document.title || '',
    url: location.href,
    text,
    links: Array.from(new Set(links)).slice(0, 60),
  })
})()
"""


def _headers() -> Dict[str, str]:
    key = get_secret(ENV_KEY)
    if not key:
        raise BrowseError("no Browserbase API key is configured", code="no_key")
    return {"X-BB-API-Key": key}


def _connect(url: str, timeout: float):
    """Open the CDP websocket. Split out so tests can hand in a fake."""
    from websockets.sync.client import connect

    return connect(url, open_timeout=timeout, max_size=16 * 1024 * 1024)


class _Cdp:
    """The smallest correct CDP client: send a command, get *its* reply."""

    def __init__(self, socket: Any) -> None:
        self._socket = socket
        self._next_id = 0

    def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        session_id: str = "",
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        self._next_id += 1
        message: Dict[str, Any] = {
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            message["sessionId"] = session_id
        self._socket.send(json.dumps(message))

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowseError(f"{method} timed out", code="timeout")
            try:
                raw = self._socket.recv(timeout=remaining)
            except TimeoutError as exc:
                raise BrowseError(f"{method} timed out", code="timeout") from exc
            except Exception as exc:  # noqa: BLE001 — any transport fault reads the same
                raise BrowseError(f"browser connection failed: {exc}", code="unreachable") from exc
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            # Anything without our id is an event on the same wire; skip it.
            if data.get("id") != message["id"]:
                continue
            error = data.get("error")
            if error:
                detail = error.get("message") if isinstance(error, dict) else None
                raise BrowseError(
                    f"{method} failed: {detail or error}",
                    code="provider_error",
                )
            result = data.get("result")
            return result if isinstance(result, dict) else {}


class BrowserbaseBrowser(BrowseProvider):
    id = "browserbase"
    label = "Browserbase"
    # A real browser can load a search engine, but scraping one is a different
    # problem from reading a page and is not pretended at here.
    can_search = False

    def __init__(
        self,
        *,
        post: Callable[..., Dict[str, Any]] = post_json,
        connect: Callable[[str, float], Any] = _connect,
    ) -> None:
        self._post = post
        self._connect = connect

    def _create_session(self, timeout: float) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        project = get_secret(PROJECT_ENV)
        if project:
            # Optional: the key implies a project when this is not set.
            payload["projectId"] = project
        body = self._post(f"{API_ROOT}/sessions", payload, _headers(), timeout=timeout)
        connect_url = str(body.get("connectUrl") or "")
        session_id = str(body.get("id") or "")
        if not connect_url:
            raise BrowseError(
                "Browserbase did not return a connect URL", code="bad_response"
            )
        return {"id": session_id, "connectUrl": connect_url}

    def _release(self, session_id: str, timeout: float) -> None:
        """Give the session back. Best effort — never mask the real error."""
        if not session_id:
            return
        try:
            self._post(
                f"{API_ROOT}/sessions/{session_id}",
                {"status": "REQUEST_RELEASE"},
                _headers(),
                timeout=min(timeout, 10.0),
            )
        except Exception:
            pass

    def fetch(self, url: str, *, timeout: float = 45.0) -> Page:
        target_url = normalise_url(url)
        seconds = clamp_timeout(timeout)
        started = time.monotonic()

        session = self._create_session(min(seconds, 30.0))
        socket = None
        try:
            socket = self._connect(session["connectUrl"], min(seconds, 30.0))
            cdp = _Cdp(socket)

            def left() -> float:
                return max(1.0, seconds - (time.monotonic() - started))

            created = cdp.call(
                "Target.createTarget", {"url": "about:blank"}, timeout=left()
            )
            target_id = str(created.get("targetId") or "")
            if not target_id:
                raise BrowseError("browser gave no page to drive", code="bad_response")

            attached = cdp.call(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
                timeout=left(),
            )
            page_session = str(attached.get("sessionId") or "")
            if not page_session:
                raise BrowseError("could not attach to the page", code="bad_response")

            cdp.call("Page.enable", session_id=page_session, timeout=left())
            cdp.call(
                "Page.navigate",
                {"url": target_url},
                session_id=page_session,
                timeout=left(),
            )

            # Wait for the document to settle. Polling readyState is cruder than
            # listening for lifecycle events but cannot deadlock on a page that
            # never fires the one we happened to wait for.
            settled = False
            while left() > 2.0:
                state = cdp.call(
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                    session_id=page_session,
                    timeout=left(),
                )
                value = ((state.get("result") or {}).get("value")) or ""
                if value == "complete":
                    settled = True
                    break
                time.sleep(0.25)

            extracted = cdp.call(
                "Runtime.evaluate",
                {"expression": _EXTRACT, "returnByValue": True, "awaitPromise": False},
                session_id=page_session,
                timeout=left(),
            )
            payload = ((extracted.get("result") or {}).get("value")) or ""
            try:
                data = json.loads(payload) if isinstance(payload, str) else {}
            except json.JSONDecodeError:
                data = {}
            text = str(data.get("text") or "").strip()
            if not text:
                raise BrowseError(
                    "the page loaded but had no readable text"
                    + ("" if settled else " (it was still loading)"),
                    code="empty_page",
                )
            links = [str(link) for link in (data.get("links") or []) if isinstance(link, str)]
            return Page(
                url=str(data.get("url") or target_url),
                title=str(data.get("title") or "").strip(),
                text=text,
                links=links,
                provider=self.id,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            ).trimmed()
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass
            # Always, and before we return: an unreleased session keeps billing.
            self._release(session["id"], seconds)

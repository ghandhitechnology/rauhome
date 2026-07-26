"""
The face's window onto the web, and the body language that goes with it.

Reading a page takes seconds, not milliseconds, and during those seconds the
character should be doing the thing rather than standing in the middle of the
room. So the tool brackets the fetch with `browse_started` / `browse_finished`,
and the renderer holds him at the desk in `search` for exactly as long as the
work actually takes — not a guessed duration that ends early on a slow page and
late on a fast one.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from rau.browse import BrowseError, Page, SearchHit, get_browser, resolve_browse
from rau.events import BUS
from rau.face import choreography

MAX_QUERY_CHARS = 400
MAX_RESULTS = 10
#: A stuck fetch must not pin him at the desk forever; the renderer gives up
#: after this even if `browse_finished` never lands.
WATCHDOG_MS = 90_000


BROWSE_WEB_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "browse_web",
        "description": (
            "Read a page on the web, or search it. Give `url` to open "
            "something specific, or `query` to search for it first. You walk "
            "over to the computer to do this and it takes a few seconds, so "
            "say something before you start if it will be a moment. Never "
            "read the raw page back — say what it means."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Page to open. http/https only.",
                },
                "query": {
                    "type": "string",
                    "maxLength": MAX_QUERY_CHARS,
                    "description": (
                        "Search the web instead. Needs a backend that can "
                        "search; the result says so if it cannot."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_RESULTS,
                    "description": "How many search results to return.",
                },
            },
            "additionalProperties": False,
        },
    },
}


def _start(kind: str, detail: str) -> str:
    """Send him to the desk and tell the room what he is doing."""
    activity_id = f"browse_{uuid.uuid4().hex[:12]}"
    BUS.emit(
        "browse_started",
        activity_id=activity_id,
        turn_id=choreography.current_turn_id() or "",
        mode=kind,
        detail=detail[:200],
        watchdog_ms=WATCHDOG_MS,
    )
    return activity_id


def _finish(activity_id: str, *, ok: bool, detail: str = "") -> None:
    BUS.emit(
        "browse_finished",
        activity_id=activity_id,
        turn_id=choreography.current_turn_id() or "",
        ok=bool(ok),
        detail=detail[:200],
    )


def _page_result(page: Page, provider: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": provider,
        "url": page.url,
        "title": page.title,
        "text": page.text,
        "links": page.links,
        "elapsed_ms": round(page.elapsed_ms),
    }


def _hits_result(hits: List[SearchHit], provider: str, elapsed_ms: float) -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": provider,
        "results": [
            {"title": hit.title, "url": hit.url, "snippet": hit.snippet} for hit in hits
        ],
        "elapsed_ms": round(elapsed_ms),
    }


def browse_web(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run one browse. Always closes the activity it opened."""
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be an object", "code": "malformed"}

    unknown = set(args) - {"url", "query", "limit"}
    if unknown:
        return {
            "ok": False,
            "error": f"unknown field(s): {', '.join(sorted(unknown))}",
            "code": "unknown_field",
        }

    url = str(args.get("url") or "").strip()
    query = str(args.get("query") or "").strip()
    if not url and not query:
        return {
            "ok": False,
            "error": "give either a url to open or a query to search for",
            "code": "nothing_to_do",
        }
    if url and query:
        return {
            "ok": False,
            "error": "give a url or a query, not both",
            "code": "conflicting_input",
        }

    # Resolved before the walk, so a missing key is an instant answer rather
    # than a trip across the room that ends in nothing.
    try:
        provider_id, browser = get_browser()
    except BrowseError as exc:
        return {"ok": False, "error": str(exc), "code": exc.code}

    activity = _start("search" if query else "open", query or url)
    started = time.monotonic()
    try:
        if query:
            if not browser.can_search:
                _, view = resolve_browse()
                # An instant refusal is still the end of the activity: without
                # this he stands at the desk until the watchdog notices.
                _finish(activity, ok=False, detail="backend cannot search")
                return {
                    "ok": False,
                    "code": "unsupported",
                    "error": (
                        f"{browser.label} can open a page but cannot search. "
                        "Connect Firecrawl, or give a url instead."
                    ),
                    "provider": provider_id,
                    "can_search": bool(view.get("can_search")),
                }
            limit = args.get("limit")
            hits = browser.search(query, limit=int(limit) if limit else 5)
            result = _hits_result(hits, provider_id, (time.monotonic() - started) * 1000)
        else:
            result = _page_result(browser.fetch(url), provider_id)
        _finish(activity, ok=True)
        return result
    except BrowseError as exc:
        _finish(activity, ok=False, detail=str(exc))
        return {"ok": False, "error": str(exc), "code": exc.code, "provider": provider_id}
    except Exception as exc:  # noqa: BLE001 — a tool must not kill the turn
        _finish(activity, ok=False, detail=str(exc))
        return {
            "ok": False,
            "error": f"browsing failed: {exc}",
            "code": "browse_failed",
            "provider": provider_id,
        }
    finally:
        try:
            browser.close()
        except Exception:
            pass


def prompt_fragment() -> str:
    provider, view = resolve_browse()
    if not provider:
        return (
            "## The web\nYou have no web access right now — no Firecrawl or "
            "Browserbase key is configured. Say so plainly if asked to look "
            "something up."
        )
    lines = [
        "## The web",
        f"`browse_web` reads pages through {provider}. You walk to the computer "
        "to use it and it takes a few seconds.",
    ]
    if not view.get("can_search"):
        lines.append(
            "This backend opens a given url but cannot search, so ask for the "
            "address if you do not have one."
        )
    return "\n".join(lines)

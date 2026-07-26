"""
Panels: things Rau makes and puts on the wall.

The model writes a small self-contained HTML document — a report, a poster, a
little interactive dashboard — and it appears in the room as a framed panel he
can walk over and present. This is the difference between an assistant that
tells you a number and one that hands you something to look at.

## Why this is safe to render

The document is written by a language model, so it is treated as hostile input
that happens to be useful. Two independent barriers:

1. **The frame is an opaque origin.** The browser mounts it with
   `sandbox="allow-scripts"` and deliberately *without* `allow-same-origin`, so
   scripts run but the document belongs to no origin: it cannot read this app's
   cookies, storage or DOM, and it cannot call the hub with the user's
   credentials.

2. **The document cannot reach the network.** Everything the model writes is
   wrapped in a skeleton whose Content-Security-Policy forbids loading or
   connecting to anything at all — no scripts, styles, images, fonts or fetches
   from outside the document. Inline script and style are permitted, because
   that is the only way a self-contained panel can be interactive, but there is
   nowhere for data to go.

Together those mean the worst a bad panel can do is look wrong.
"""
from __future__ import annotations

import html
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from rau.events import BUS
from rau.face import choreography

KINDS: Tuple[str, ...] = ("report", "poster", "dashboard", "note")

MAX_TITLE_CHARS = 80
#: Big enough for a real dashboard with inline data, small enough that a
#: runaway generation cannot wedge the socket or the renderer.
MAX_HTML_BYTES = 96_000
#: Panels kept in memory. The wall only shows the newest few; the rest stay
#: addressable for a moment so a reload does not lose what was just made.
MAX_PANELS = 12

#: No origin may be contacted, and nothing may be loaded from one. Inline
#: script and style are allowed — a self-contained interactive panel cannot
#: exist without them — but `default-src 'none'` means there is no way out.
CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "font-src data:; "
    "form-action 'none'; "
    "base-uri 'none'"
)

_SKELETON = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  html, body {{ margin: 0; padding: 0; background: #14100E; color: #EDE6DC; }}
  body {{
    font: 15px/1.55 "DM Sans", ui-sans-serif, system-ui, -apple-system, sans-serif;
    padding: 22px 24px 30px;
    -webkit-font-smoothing: antialiased;
  }}
  h1, h2, h3 {{ font-family: ui-serif, Georgia, serif; font-weight: 600; line-height: 1.2; }}
  h1 {{ font-size: 1.7rem; margin: 0 0 0.2em; }}
  h2 {{ font-size: 1.25rem; margin: 1.4em 0 0.4em; }}
  a {{ color: #E8875A; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.8em 0; }}
  th, td {{ text-align: left; padding: 0.45em 0.6em; border-bottom: 1px solid #2E2622; }}
  th {{ color: #B9AFA4; font-weight: 600; font-size: 0.82rem; letter-spacing: 0.04em;
        text-transform: uppercase; }}
  code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.88em; }}
  pre {{ background: #1D1815; padding: 0.9em 1em; border-radius: 10px; overflow: auto; }}
  button {{ font: inherit; color: #14100E; background: #E8875A; border: 0;
            border-radius: 999px; padding: 0.45em 1.1em; cursor: pointer; }}
  .muted {{ color: #A79C90; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

_lock = threading.RLock()
_panels: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


def wrap_document(title: str, body: str) -> str:
    """Put the model's markup inside a skeleton it cannot escape."""
    return _SKELETON.format(csp=CSP, title=html.escape(title, quote=True), body=body)


def get_panel(panel_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        panel = _panels.get(panel_id)
        return dict(panel) if panel else None


def list_panels(limit: int = MAX_PANELS) -> List[Dict[str, Any]]:
    """Newest first, without the document bodies."""
    with _lock:
        items = list(_panels.values())[-max(0, int(limit)) :]
    return [
        {k: v for k, v in panel.items() if k != "document"}
        for panel in reversed(items)
    ]


def clear_panels() -> None:
    with _lock:
        _panels.clear()
    BUS.emit("panel_cleared", panel_id="")


SHOW_PANEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "show_panel",
        "description": (
            "Make something to look at and put it up on your wall: a short "
            "report, a poster, or a small interactive dashboard. Write a "
            "self-contained HTML fragment for the <body> — inline <style> and "
            "<script> are fine and charts should be drawn with inline SVG or "
            "canvas. Nothing external will load, so do not link stylesheets, "
            "scripts, images or fonts. Use this when a picture, a table or "
            "something clickable says it better than a sentence would; then "
            "say one line about it out loud. Never read the markup aloud."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "maxLength": MAX_TITLE_CHARS,
                    "description": "Short title, shown on the frame in the room.",
                },
                "kind": {
                    "type": "string",
                    "enum": list(KINDS),
                    "description": "What it is, which sets how the frame looks.",
                },
                "html": {
                    "type": "string",
                    "description": (
                        "HTML for the document body. Self-contained: inline "
                        "style and script only, no external references."
                    ),
                },
            },
            "required": ["title", "html"],
            "additionalProperties": False,
        },
    },
}


def show_panel(
    args: Dict[str, Any], *, turn_id: Optional[str] = None
) -> Dict[str, Any]:
    """Validate a panel, store it, and put it on the wall."""
    # The turn scope exists so callers do not have to thread the id through by
    # hand; reading it here means a caller that forgets still produces an event
    # a client can tie to the reply it belongs to.
    turn_id = turn_id or choreography.current_turn_id()
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be an object", "code": "malformed"}

    unknown = set(args) - {"title", "kind", "html"}
    if unknown:
        return {
            "ok": False,
            "error": f"unknown field(s): {', '.join(sorted(unknown))}",
            "code": "unknown_field",
        }

    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        return {"ok": False, "error": "title is required", "code": "missing_title"}
    title = title.strip()
    if len(title) > MAX_TITLE_CHARS:
        return {
            "ok": False,
            "error": f"title must be at most {MAX_TITLE_CHARS} characters",
            "code": "title_too_long",
        }

    markup = args.get("html")
    if not isinstance(markup, str) or not markup.strip():
        return {"ok": False, "error": "html is required", "code": "missing_html"}
    size = len(markup.encode("utf-8"))
    if size > MAX_HTML_BYTES:
        return {
            "ok": False,
            "error": f"html must be under {MAX_HTML_BYTES // 1000}kB (got {size // 1000}kB)",
            "code": "html_too_large",
        }

    kind = args.get("kind") or "report"
    if not isinstance(kind, str) or kind not in KINDS:
        return {
            "ok": False,
            "error": f"unknown kind — choose from {', '.join(KINDS)}",
            "code": "unknown_kind",
        }

    panel_id = f"panel_{uuid.uuid4().hex[:12]}"
    panel = {
        "panel_id": panel_id,
        "turn_id": turn_id or "",
        "title": title,
        "kind": kind,
        "bytes": size,
        "created": time.time(),
        "document": wrap_document(title, markup),
    }
    with _lock:
        _panels[panel_id] = panel
        while len(_panels) > MAX_PANELS:
            _panels.popitem(last=False)

    BUS.emit(
        "panel_shown",
        panel_id=panel_id,
        turn_id=panel["turn_id"],
        title=title,
        # Not `kind`: that names the *event* on the bus, and passing both is a
        # TypeError rather than anything subtler.
        panel_kind=kind,
        bytes=size,
        created=panel["created"],
    )
    return {
        "ok": True,
        "panel_id": panel_id,
        "title": title,
        "kind": kind,
        "note": "It is on the wall now. Say one line about it; do not read it out.",
    }


def prompt_fragment() -> str:
    recent = list_panels(3)
    lines = [
        "## Making things to look at",
        "`show_panel` puts a self-contained HTML panel on your wall — a report, "
        "a poster, or a small interactive dashboard. Reach for it when a table, "
        "a chart or something clickable beats a paragraph. Inline style and "
        "script only; nothing external loads.",
    ]
    if recent:
        lines.append("On the wall now: " + ", ".join(f"“{p['title']}”" for p in recent))
    return "\n".join(lines)

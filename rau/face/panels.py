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

## What is stored

The row keeps the model's **raw fragment**, not the wrapped document. The
document is rendered on read. That ordering is what makes editing possible: the
model wrote the fragment, so the fragment is what its edit anchors will match —
anchoring against the skeleton would mean matching markup it never saw.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from rau.agent.edit import _closest_excerpt, _match_indices
from rau.control.store import control_store
from rau.events import BUS
from rau.face import choreography

KINDS: Tuple[str, ...] = ("report", "poster", "dashboard", "note")

MAX_TITLE_CHARS = 80
#: Big enough for a real dashboard with inline data, small enough that a
#: runaway generation cannot wedge the socket or the renderer.
MAX_HTML_BYTES = 96_000
#: Panels kept on the wall. Older ones are dropped, not archived: taking a panel
#: down is permanent, so ageing one out has to mean the same thing.
MAX_PANELS = 12
#: Headings pulled out for the model's benefit — enough of an outline to aim an
#: edit at, without handing back 96kB it would only have to pay for.
MAX_HEADINGS = 12

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

#: Serialises read-modify-write on a panel body. The store is transactional per
#: statement, but a patch is read-then-write and two concurrent edits to one
#: panel would otherwise interleave and lose the first.
_lock = threading.RLock()

_HEADING_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def wrap_document(title: str, body: str) -> str:
    """Put the model's markup inside a skeleton it cannot escape."""
    return _SKELETON.format(csp=CSP, title=html.escape(title, quote=True), body=body)


def headings(body: str) -> List[str]:
    """The h1–h3 text of a panel, as a rough table of contents."""
    out: List[str] = []
    for match in _HEADING_RE.finditer(body or ""):
        text = html.unescape(_TAG_RE.sub("", match.group(1))).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            out.append(text[:80])
        if len(out) >= MAX_HEADINGS:
            break
    return out


def _public(row: Dict[str, Any], *, body: bool = False) -> Dict[str, Any]:
    """The shape the model, the hub and the browser all see."""
    out = {
        "panel_id": row.get("panel_id"),
        "title": row.get("title"),
        "kind": row.get("kind"),
        "bytes": int(row.get("bytes") or 0),
        "revision": int(row.get("revision") or 1),
        "turn_id": row.get("turn_id") or "",
        "job_id": row.get("job_id") or "",
        "source": row.get("source") or "face",
        "created": float(row.get("created") or 0.0),
        "updated": float(row.get("updated") or 0.0),
        "headings": headings(str(row.get("body") or "")),
    }
    if body:
        out["body"] = str(row.get("body") or "")
    return out


def get_panel(panel_id: str) -> Optional[Dict[str, Any]]:
    """One panel, with its document rendered from the stored fragment."""
    row = control_store.get_panel(str(panel_id or ""))
    if not row:
        return None
    panel = _public(row, body=True)
    panel["document"] = wrap_document(str(row["title"]), str(row["body"]))
    return panel


def list_panels(limit: int = MAX_PANELS) -> List[Dict[str, Any]]:
    """Newest first, without the document bodies."""
    # A negative limit means the caller asked for nothing, not for everything.
    limit = max(0, int(limit))
    if not limit:
        return []
    return [_public(row) for row in control_store.list_panels(limit=limit)]


def panels_for_job(job_id: str) -> List[Dict[str, Any]]:
    """Everything a given job put on the wall — used when weaving its result."""
    if not job_id:
        return []
    return [
        _public(row)
        for row in control_store.list_panels(limit=MAX_PANELS, job_id=str(job_id))
    ]


def clear_panels() -> None:
    with _lock:
        control_store.delete_all_panels()
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

LIST_PANELS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_panels",
        "description": (
            "See what is on your wall right now: id, title, kind, and the "
            "headings inside each one. Call this before editing or taking "
            "something down, so you are working from the real ids."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

UPDATE_PANEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_panel",
        "description": (
            "Change a panel already on the wall. Prefer a patch: give `old` — "
            "an exact run of markup from the panel, unique enough to match once "
            "— and `new` to put in its place. That way you change one number "
            "without rewriting the document. Use `html` only when you mean to "
            "replace the whole body. If a patch misses, the error shows you the "
            "nearest real text; aim again from that rather than guessing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "panel_id": {"type": "string", "description": "From list_panels."},
                "old": {
                    "type": "string",
                    "description": "Exact existing markup to replace. Must occur once.",
                },
                "new": {
                    "type": "string",
                    "description": "What to put there. Empty string deletes the old run.",
                },
                "html": {
                    "type": "string",
                    "description": "Whole new body. Do not combine with old/new.",
                },
                "title": {"type": "string", "maxLength": MAX_TITLE_CHARS},
                "kind": {"type": "string", "enum": list(KINDS)},
            },
            "required": ["panel_id"],
            "additionalProperties": False,
        },
    },
}

CLOSE_PANEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "close_panel",
        "description": (
            "Take a panel off the wall for good. There is no archive, so do "
            "this when it is genuinely finished with, not to tidy up."
        ),
        "parameters": {
            "type": "object",
            "properties": {"panel_id": {"type": "string"}},
            "required": ["panel_id"],
            "additionalProperties": False,
        },
    },
}

PRESENT_PANEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "present_panel",
        "description": (
            "Open a panel full-screen in the room — the equivalent of walking "
            "over and pointing at it. Use it when you want your friend looking "
            "at the thing while you talk about it. It only opens for someone "
            "who is in the room; otherwise it waits for them there."
        ),
        "parameters": {
            "type": "object",
            "properties": {"panel_id": {"type": "string"}},
            "required": ["panel_id"],
            "additionalProperties": False,
        },
    },
}

COMMISSION_PANEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "commission_panel",
        "description": (
            "Hand the whole job of making a panel to a silent worker: it does "
            "the research or the computer work first, then puts the finished "
            "panel on your wall itself. Use this when the thing you want to "
            "show does not exist yet and gathering it would take real work. "
            "For something you can already write out, just call show_panel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "What the panel should show and what has to be found "
                        "out to make it. Write it as a whole task."
                    ),
                },
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
    },
}

_PANEL_KEYS = frozenset({"title", "kind", "html"})


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _loads_panel_object(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of a show_panel arguments object from raw tool JSON."""
    text = _strip_fence(text)
    start = text.find("{")
    if start < 0:
        return None
    text = text[start:]

    candidates = [text]
    # Streaming tool args are often cut mid-string or mid-object.
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        if "Unterminated string" in (exc.msg or ""):
            candidates.append(text + '"')
        for base in list(candidates):
            for depth in range(1, 4):
                candidates.append(base + ("}" * depth))
                candidates.append(base + '"' + ("}" * depth))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        break

    try:
        parsed, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_panel_fields(raw: str) -> Optional[Dict[str, Any]]:
    """Last-resort field scrape when the JSON object will not close cleanly."""

    def _string_field(name: str) -> Optional[str]:
        match = re.search(
            rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"',
            raw,
            flags=re.DOTALL,
        )
        if not match:
            return None
        try:
            return json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            return match.group(1)

    title = _string_field("title")
    markup = _string_field("html")
    if title is None or markup is None:
        return None
    out: Dict[str, Any] = {"title": title, "html": markup}
    kind = _string_field("kind")
    if kind is not None:
        out["kind"] = kind
    return out


def coerce_panel_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recover title/kind/html when the provider handed us `{'_raw': ...}` because
    streamed tool JSON for a large dashboard failed to parse.
    """
    if "_raw" not in args:
        return args
    raw = args.get("_raw")
    if not isinstance(raw, str) or not raw.strip():
        return args

    parsed = _loads_panel_object(raw) or _extract_panel_fields(raw)
    if not isinstance(parsed, dict):
        return args

    recovered = {key: parsed[key] for key in _PANEL_KEYS if key in parsed}
    # Keep any already-decoded siblings the caller may have set, but never keep
    # `_raw` once we have real fields — otherwise unknown_field rejects us.
    merged = {key: value for key, value in args.items() if key != "_raw"}
    merged.update(recovered)
    return merged


def show_panel(
    args: Dict[str, Any],
    *,
    turn_id: Optional[str] = None,
    job_id: Optional[str] = None,
    source: str = "face",
) -> Dict[str, Any]:
    """Validate a panel, store it, and put it on the wall."""
    # The turn scope exists so callers do not have to thread the id through by
    # hand; reading it here means a caller that forgets still produces an event
    # a client can tie to the reply it belongs to.
    turn_id = turn_id or choreography.current_turn_id()
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be an object", "code": "malformed"}

    args = coerce_panel_args(args)
    if "_raw" in args and not (args.get("title") and args.get("html")):
        return {
            "ok": False,
            "error": "panel arguments were not valid JSON",
            "code": "malformed",
        }

    unknown = set(args) - _PANEL_KEYS
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
    now = time.time()
    with _lock:
        control_store.create_panel(
            {
                "panel_id": panel_id,
                "title": title,
                "kind": kind,
                "body": markup,
                "bytes": size,
                "turn_id": turn_id or "",
                "job_id": job_id or "",
                "source": source,
                "created": now,
                "updated": now,
            }
        )
        # Ageing a panel out is the same permanent removal as taking one down,
        # so the wall gets its own event per drop rather than a silent gap.
        dropped = control_store.trim_panels(MAX_PANELS)
    for gone in dropped:
        BUS.emit("panel_closed", panel_id=gone)

    BUS.emit(
        "panel_shown",
        panel_id=panel_id,
        turn_id=turn_id or "",
        title=title,
        # Not `kind`: that names the *event* on the bus, and passing both is a
        # TypeError rather than anything subtler.
        panel_kind=kind,
        bytes=size,
        created=now,
        revision=1,
        source=source,
    )
    return {
        "ok": True,
        "panel_id": panel_id,
        "title": title,
        "kind": kind,
        "note": "It is on the wall now. Say one line about it; do not read it out.",
    }


_UPDATE_KEYS = frozenset({"panel_id", "title", "kind", "html", "old", "new"})


def update_panel(
    args: Dict[str, Any], *, job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Edit a panel that is already on the wall, in one of two modes.

    *Patch* — `old` + `new` — swaps one exact run of text. This is the cheap
    path: the model never has to hold or resend the whole document to change a
    number. It must match exactly once, and when it does not, the error carries
    the nearest real text so the next attempt can be aimed properly. That
    feedback loop is deliberately the substitute for a read-the-panel-back tool.

    *Replace* — `html` — swaps the whole body. The panel keeps its id and its
    place on the wall, so a rewrite does not make the frame jump.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be an object", "code": "malformed"}

    args = coerce_panel_args(args)
    unknown = set(args) - _UPDATE_KEYS
    if unknown:
        return {
            "ok": False,
            "error": f"unknown field(s): {', '.join(sorted(unknown))}",
            "code": "unknown_field",
        }

    panel_id = str(args.get("panel_id") or "").strip()
    if not panel_id:
        return {"ok": False, "error": "panel_id is required", "code": "missing_panel_id"}

    markup = args.get("html")
    old = args.get("old")
    new = args.get("new")
    patching = old is not None or new is not None

    if patching and markup is not None:
        return {
            "ok": False,
            "error": "pass either html (replace) or old+new (patch), not both",
            "code": "conflicting_input",
        }
    if patching and not (isinstance(old, str) and old):
        return {"ok": False, "error": "old is required to patch", "code": "missing_old"}

    with _lock:
        row = control_store.get_panel(panel_id)
        if not row:
            return {
                "ok": False,
                "error": "no panel with that id — call list_panels to see the wall",
                "code": "unknown_panel",
            }

        body = str(row["body"])
        if patching:
            hits = _match_indices(body, str(old))
            if not hits:
                excerpt = _closest_excerpt(body, str(old))
                return {
                    "ok": False,
                    "error": "old text is not in this panel",
                    "code": "no_match",
                    "closest": excerpt or "(nothing similar found)",
                }
            if len(hits) > 1:
                return {
                    "ok": False,
                    "error": (
                        f"old text appears {len(hits)} times — include enough "
                        "surrounding markup to make it unique"
                    ),
                    "code": "ambiguous_match",
                }
            body = body.replace(str(old), str(new or ""), 1)
        elif markup is not None:
            if not isinstance(markup, str) or not markup.strip():
                return {"ok": False, "error": "html is required", "code": "missing_html"}
            body = markup

        size = len(body.encode("utf-8"))
        if size > MAX_HTML_BYTES:
            return {
                "ok": False,
                "error": f"html must be under {MAX_HTML_BYTES // 1000}kB (got {size // 1000}kB)",
                "code": "html_too_large",
            }

        changes: Dict[str, Any] = {"body": body, "bytes": size}

        title = args.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                return {"ok": False, "error": "title cannot be empty", "code": "missing_title"}
            title = title.strip()
            if len(title) > MAX_TITLE_CHARS:
                return {
                    "ok": False,
                    "error": f"title must be at most {MAX_TITLE_CHARS} characters",
                    "code": "title_too_long",
                }
            changes["title"] = title

        kind = args.get("kind")
        if kind is not None:
            if not isinstance(kind, str) or kind not in KINDS:
                return {
                    "ok": False,
                    "error": f"unknown kind — choose from {', '.join(KINDS)}",
                    "code": "unknown_kind",
                }
            changes["kind"] = kind

        if not patching and markup is None and len(changes) == 2:
            # Only body/bytes, and the body is unchanged: nothing was asked for.
            return {
                "ok": False,
                "error": "pass html to replace, old+new to patch, or a new title/kind",
                "code": "nothing_to_do",
            }

        updated = control_store.update_panel(panel_id, changes)

    if not updated:
        return {"ok": False, "error": "panel vanished mid-edit", "code": "unknown_panel"}

    BUS.emit(
        "panel_updated",
        panel_id=panel_id,
        title=updated["title"],
        panel_kind=updated["kind"],
        bytes=int(updated["bytes"]),
        revision=int(updated["revision"]),
        job_id=job_id or updated.get("job_id") or "",
    )
    return {
        "ok": True,
        "panel_id": panel_id,
        "title": updated["title"],
        "kind": updated["kind"],
        "revision": int(updated["revision"]),
        "mode": "patch" if patching else "replace",
        "note": "The wall is showing the new version.",
    }


def close_panel(panel_id: str) -> Dict[str, Any]:
    """Take a panel down. This is permanent — there is no archive to restore from."""
    panel_id = str(panel_id or "").strip()
    if not panel_id:
        return {"ok": False, "error": "panel_id is required", "code": "missing_panel_id"}
    with _lock:
        row = control_store.get_panel(panel_id)
        if not row:
            return {
                "ok": False,
                "error": "no panel with that id — call list_panels to see the wall",
                "code": "unknown_panel",
            }
        control_store.delete_panel(panel_id)
    BUS.emit("panel_closed", panel_id=panel_id)
    return {"ok": True, "panel_id": panel_id, "title": row["title"], "note": "Taken down."}


def present_panel(panel_id: str) -> Dict[str, Any]:
    """
    Ask the room to open a panel full-screen.

    Only the room obeys this. Elsewhere the request waits, and opens when the
    user next walks into the room — so "look at this" is never a page the model
    yanks out from under someone mid-sentence.
    """
    panel_id = str(panel_id or "").strip()
    if not panel_id:
        return {"ok": False, "error": "panel_id is required", "code": "missing_panel_id"}
    row = control_store.get_panel(panel_id)
    if not row:
        return {
            "ok": False,
            "error": "no panel with that id — call list_panels to see the wall",
            "code": "unknown_panel",
        }
    BUS.emit("panel_presented", panel_id=panel_id, title=row["title"])
    return {
        "ok": True,
        "panel_id": panel_id,
        "title": row["title"],
        "note": (
            "It opens in the room. If your friend is not in the room it waits "
            "for them there — say so rather than assuming they can see it."
        ),
    }


#: The goal a commissioned worker is actually given. The wording is load-bearing
#: twice over: "dashboard panel" is what `capabilities_for_goal` matches to hand
#: the worker its panel tools, and it is what steers it toward the dashboard
#: skill. Changing this phrase silently disarms both.
COMMISSION_TEMPLATE = (
    "Build a dashboard panel: {goal}\n\n"
    "Do the research or computer work first, then call show_panel with a "
    "self-contained HTML body to put the finished panel on the wall. Call "
    "use_skill('dashboard') before writing any markup. Do not finish without "
    "having shown a panel."
)


def commission(goal: str, *, origin_turn_id: Optional[str] = None) -> Dict[str, Any]:
    """Hand panel-making to a worker that can go and find the numbers first."""
    goal = str(goal or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required", "code": "missing_goal"}

    # Imported here, not at module scope: the orchestrator reads panels back
    # when it weaves a finished job, so a top-level import would be a cycle.
    from rau.agent import orchestrator

    result = orchestrator.start_hard_task(
        COMMISSION_TEMPLATE.format(goal=goal),
        origin_turn_id=origin_turn_id,
    )
    if result.get("ok"):
        result["note"] = (
            "A worker is on it. Say you are making it and carry on — it goes up "
            "by itself and you will hear when it lands."
        )
    return result


def prompt_fragment() -> str:
    recent = list_panels(5)
    lines = [
        "## Making things to look at",
        "`show_panel` puts a self-contained HTML panel on your wall — a report, "
        "a poster, or a small interactive dashboard. Reach for it when a table, "
        "a chart or something clickable beats a paragraph. Inline style and "
        "script only; nothing external loads.",
        "The wall is yours to keep tidy: `list_panels` to see it, `update_panel` "
        "to change one (patch with old/new rather than resending the whole "
        "thing), `close_panel` to take one down for good, `present_panel` to "
        "open one in the room. For anything that needs real digging first, "
        "`commission_panel` hands the whole job to a worker.",
    ]
    if recent:
        lines.append("")
        lines.append("On the wall now:")
        for panel in recent:
            lines.append(f"- {panel['panel_id']} · {panel['kind']} · “{panel['title']}”")
    return "\n".join(lines)

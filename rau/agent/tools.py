"""Local tools available to the subagent."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rau.agent.edit import edit_file, note_read
from rau.agent.sandbox import (
    NO_SANDBOX_WARNING,
    PathEscape,
    allow_unconfined_shell,
    resolve_in_root,
    shell_argv,
)
from rau.computer.cua import execute_action
from rau.mcp.client import MCP
from rau.memory.store import append_diary, append_trace, recent_context, write_daily_log
from rau.paths import ROOT

SHELL_TIMEOUT_SEC = 120.0
MAX_SHELL_TIMEOUT_SEC = 600.0
MAX_SHELL_COMMAND_CHARS = 20_000
#: Only the tail of a command's output is ever returned, so the spool it
#: collects in is capped as well: a runaway command (think `yes`) would
#: otherwise fill the disk behind the tail window.
MAX_SHELL_OUTPUT_BYTES = 64 * 1024 * 1024


def _shell_env() -> Dict[str, str]:
    """Do not hand provider/app credentials to model-authored subprocesses."""
    sensitive = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL")
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().endswith(sensitive)
        and key.upper() not in {"AUTHORIZATION", "AWS_SESSION_TOKEN"}
    }

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command on the local Mac, from the project root. "
                "Writes are confined to the project (plus temp and cache dirs) "
                "by the macOS sandbox; reads and network are not. If seatbelt "
                "is unavailable, execution fails closed unless the user has "
                "explicitly enabled allow_unconfined_shell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_sec": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": MAX_SHELL_TIMEOUT_SEC,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file under the project root (path string).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a whole UTF-8 text file under the project root. For an "
                "existing file prefer edit_file — this replaces everything."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact string in a file you have read this session. "
                "old_string must appear exactly once unless replace_all is set; "
                "include surrounding lines to make it unique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Append a note to today's diary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "Read recent diary context.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "composio_search",
            "description": "Search Composio tools for an integration need.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "composio_execute",
            "description": "Execute Composio tools (may require confirm / OAuth).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tools": {
                        "type": "array",
                        "items": {"type": "object"},
                        "maxItems": 32,
                    },
                },
                "required": ["tools"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cua_action",
            "description": (
                "Computer use on this Mac. Coordinates are logical points "
                "(matching screenshot width/height after Retina normalize). "
                "Actions: status, screenshot, click, double_click, move, "
                "drag, type, key (chords like cmd+c), scroll, wait. "
                "Call status if setup is unclear. After click/type/key/drag/"
                "move a verification screenshot is attached automatically. "
                "Optional display_id, app name, or frontmost=true for targeting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Continue the persisted session returned by an "
                            "earlier legacy screenshot/action."
                        ),
                    },
                    "action": {
                        "type": "string",
                        "description": (
                            "status|screenshot|click|double_click|move|drag|"
                            "type|key|scroll|wait"
                        ),
                    },
                    "x": {
                        "type": "integer",
                        "description": "Logical x in the target display (or window).",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Logical y in the target display (or window).",
                    },
                    "x2": {"type": "integer", "description": "Drag end x."},
                    "y2": {"type": "integer", "description": "Drag end y."},
                    "text": {"type": "string"},
                    "key": {
                        "type": "string",
                        "description": (
                            "Key or chord: return, tab, escape, backspace, "
                            "up/down/left/right, cmd+c, cmd+v, cmd+tab, …"
                        ),
                    },
                    "dy": {"type": "integer"},
                    "seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 30,
                    },
                    "display_id": {
                        "type": "integer",
                        "description": "Target display (from status/screenshot).",
                    },
                    "app": {
                        "type": "string",
                        "description": "Capture/target a window owned by this app name.",
                    },
                    "frontmost": {
                        "type": "boolean",
                        "description": "Capture the frontmost app's main window.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_status",
            "description": "Check stable computer-use capabilities or one persisted session.",
            "parameters": {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_observe",
            "description": (
                "Refresh a computer session, or take a one-shot observation "
                "when no session_id is given (the borrowed session is "
                "released immediately). Returns a screenshot, window/display "
                "identity, and bounded Accessibility tree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "app": {"type": "string"},
                    "frontmost": {"type": "boolean"},
                    "display_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_inspect_ui",
            "description": "Read the latest Accessibility observation for a session.",
            "parameters": {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_focus",
            "description": "Focus an application in an active computer session, then observe it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "app": {"type": "string"},
                },
                "required": ["session_id", "app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_act",
            "description": (
                "Perform one confirmed, verified computer mutation. target.kind "
                "is semantic (role/title/label/identifier/id) or visual "
                "(observation_id,x,y,display_id). Observe before acting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "activate",
                            "click",
                            "double_click",
                            "type",
                            "key",
                            "drag",
                            "move",
                        ],
                    },
                    "target": {"type": "object"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "postcondition": {"type": "object"},
                },
                "required": ["session_id", "action", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_wait_for",
            "description": "Observe until an Accessibility condition becomes true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "condition": {"type": "object"},
                    "timeout_sec": {"type": "number"},
                },
                "required": ["session_id", "condition"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_assert",
            "description": "Check an Accessibility postcondition without mutating the Mac.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "condition": {"type": "object"},
                },
                "required": ["session_id", "condition"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_finish",
            "description": "Release a persisted computer session with an outcome and summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "outcome": {
                        "type": "string",
                        "enum": ["completed", "failed", "cancelled"],
                    },
                    "summary": {"type": "string"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_schedules",
            "description": "List Rau's durable one-time, interval, and cron schedules.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_schedule",
            "description": (
                "Create durable scheduled work. trigger is {kind:'once',at:ISO}, "
                "{kind:'interval',seconds,anchor?}, or "
                "{kind:'cron',expression:'m h dom mon dow'}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "goal": {"type": "string"},
                    "trigger": {"type": "object"},
                    "timezone": {"type": "string"},
                    "resource_profile": {
                        "type": "string",
                        "enum": ["eco", "balanced", "performance"],
                    },
                    "permission_policy": {
                        "type": "string",
                        "enum": ["readonly", "approval"],
                    },
                },
                "required": ["name", "goal", "trigger"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_schedule",
            "description": "Update a durable schedule by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "changes": {"type": "object"},
                },
                "required": ["id", "changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schedule",
            "description": "Delete a durable schedule while retaining its run history.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_schedule",
            "description": "Pause a durable schedule.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_schedule",
            "description": "Resume a durable schedule from its next future occurrence.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_schedule_now",
            "description": "Queue a schedule immediately without changing its next occurrence.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_panel",
            "description": (
                "Put a finished thing on Rau's wall for the user to look at: a "
                "report, a poster, or a small interactive dashboard. Write a "
                "self-contained HTML fragment for the <body> — inline <style> "
                "and <script> only, charts as inline SVG or canvas. Nothing "
                "external loads, so never link stylesheets, scripts, images or "
                "fonts. This is how work that produced numbers becomes "
                "something the user can actually see. Call use_skill('dashboard') "
                "first for the house style."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["report", "poster", "dashboard", "note"],
                    },
                    "html": {"type": "string"},
                },
                "required": ["title", "html"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_panel",
            "description": (
                "Change a panel already on the wall. Prefer a patch: `old` is "
                "an exact run of markup from the panel that occurs exactly "
                "once, `new` replaces it. Use `html` only to replace the whole "
                "body. A failed patch tells you the nearest real text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "panel_id": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "html": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["report", "poster", "dashboard", "note"],
                    },
                },
                "required": ["panel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": (
                "Split this goal into independent sub-goals and run them as "
                "parallel child workers. Blocks until every child reports "
                "back, then returns their summaries. Children cannot spawn "
                "children of their own, so decompose in one pass."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One self-contained sub-goal per child.",
                    },
                },
                "required": ["goals"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Complete the hard task with a structured result. Include actual "
                "artifacts, mutations, verification, blockers, and remaining risks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "string",
                        "enum": ["completed", "failed", "blocked"],
                    },
                    "summary": {"type": "string"},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                    "mutations": {"type": "array", "items": {"type": "string"}},
                    "verification": {"type": "array", "items": {"type": "string"}},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "remaining_risks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": "Load an always-available skill body (plan, read, write, shell, search, …).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List always-available skills.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def run_tool(
    name: str,
    arguments: Dict[str, Any],
    job_id: Optional[str] = None,
    cancel: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    Execute one tool.

    `job_id` identifies the caller so a subagent can spawn work beneath itself;
    it is None for the face, which reaches nesting through its own tools.
    """
    if not isinstance(name, str) or not name:
        return {"ok": False, "error": "tool name must be a non-empty string"}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "tool arguments must be a JSON object"}
    args = arguments
    if "_raw" in args:
        return {
            "ok": False,
            "error": "tool arguments were malformed or incomplete JSON",
            "raw": str(args.get("_raw"))[:500],
        }
    if name == "run_shell":
        return _run_shell(args, cancel)

    if name == "read_file":
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            return {"ok": False, "error": "path must be a non-empty string"}
        try:
            path = resolve_in_root(args["path"])
        except PathEscape as exc:
            return {"ok": False, "error": str(exc)}
        if not path.is_file():
            return {"ok": False, "error": "not found", "path": str(path)}
        try:
            # The read itself is bounded, not just what is handed back:
            # read_text() would slurp a multi-GB file into memory before the
            # slice below ever applied.
            with path.open(encoding="utf-8", errors="replace") as fh:
                text = fh.read(50001)
                total_chars = len(text)
                hit_eof = total_chars <= 50000
                if not hit_eof:
                    # Count the rest chunk-wise, so the truncation marker can
                    # carry the true total with memory still bounded. The scan
                    # is bounded too: past the cap the exact count stops
                    # mattering and a multi-GB log would block the worker, so
                    # the marker degrades to a floor like ">5000000".
                    while total_chars < 5_000_000:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            hit_eof = True
                            break
                        total_chars += len(chunk)
        except OSError as exc:
            return {"ok": False, "error": f"could not read: {exc}", "path": str(path)}
        # Only a full read licenses a later edit; a truncated one would let the
        # model edit against a tail it never saw.
        if total_chars <= 50000:
            note_read(path)
            return {"ok": True, "path": str(path), "content": text}
        # A clipped read must say so: an unmarked truncation looks like the
        # whole file, and the model reasons over an ending that is not one.
        return {
            "ok": True,
            "path": str(path),
            "content": text[:50000],
            "truncated": True,
            # An int when the file was counted to its end; a floor string
            # once the counting scan hit its own cap.
            "total_chars": total_chars if hit_eof else ">5000000",
        }

    if name == "write_file":
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            return {"ok": False, "error": "path must be a non-empty string"}
        if not isinstance(args.get("content"), str):
            return {"ok": False, "error": "content must be a string"}
        try:
            path = resolve_in_root(args["path"])
        except PathEscape as exc:
            return {"ok": False, "error": str(exc)}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Re-resolve after mkdir so a symlinked parent created between the
            # first check and the write is caught before opening the file.
            path = resolve_in_root(str(path))
            path.write_text(args["content"], encoding="utf-8")
        except (OSError, PathEscape) as exc:
            return {"ok": False, "error": f"could not write: {exc}", "path": str(path)}
        note_read(path)
        append_trace("write_file", {"path": str(path)})
        return {"ok": True, "path": str(path)}

    if name == "edit_file":
        if not all(
            isinstance(args.get(field), str)
            for field in ("path", "old_string", "new_string")
        ):
            return {
                "ok": False,
                "error": "path, old_string, and new_string must be strings",
            }
        result = edit_file(
            args["path"],
            args["old_string"],
            args["new_string"],
            bool(args.get("replace_all")),
        )
        append_trace("edit_file", {"path": result.get("path"), "ok": result.get("ok")})
        return result

    if name == "memory_write":
        memory_text = args.get("text")
        role = args.get("role") or "note"
        if not isinstance(memory_text, str) or not isinstance(role, str):
            return {"ok": False, "error": "text and role must be strings"}
        p = append_diary(role, memory_text)
        return {"ok": True, "path": str(p)}

    if name == "memory_read":
        return {"ok": True, "context": recent_context()}

    if name == "composio_search":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "error": "query must be a non-empty string"}
        return MCP.composio_search(query)

    if name == "composio_execute":
        tools = args.get("tools") or []
        if not isinstance(tools, list) or not all(
            isinstance(tool, dict) for tool in tools
        ):
            return {"ok": False, "error": "tools must be an array of objects"}
        if not tools or len(tools) > 32:
            return {"ok": False, "error": "tools must contain between 1 and 32 items"}
        return MCP.composio_execute(tools)

    if name == "cua_action":
        action = args.get("action")
        if not isinstance(action, str):
            return {"ok": False, "error": "action must be a string"}
        from rau.computer.session import compatibility_cua_action

        try:
            return compatibility_cua_action(args, job_id=job_id, cancel=cancel)
        except (RuntimeError, TypeError, ValueError) as exc:
            # Same contract as the computer_* tools below: a session-layer
            # failure (e.g. another session holds the machine lease) is an
            # error result for the model, not a crash of the tool loop.
            return {"ok": False, "error": str(exc)}

    if name.startswith("computer_"):
        from rau.computer.session import COMPUTER

        session_id = str(args.get("session_id") or "")
        try:
            if name == "computer_status":
                return COMPUTER.status(session_id or None)
            if name == "computer_observe":
                created_here = not session_id
                if created_here:
                    started = COMPUTER.start(
                        job_id=job_id,
                        app=str(args.get("app") or "") or None,
                        frontmost=bool(args.get("frontmost", True)),
                    )
                    session_id = str(started["id"])
                observed: Dict[str, Any] = {"ok": False}
                try:
                    observed = COMPUTER.observe(
                        session_id,
                        app=str(args.get("app") or "") or None,
                        frontmost=args.get("frontmost")
                        if isinstance(args.get("frontmost"), bool)
                        else None,
                        display_id=args.get("display_id")
                        if isinstance(args.get("display_id"), int)
                        else None,
                    )
                finally:
                    if created_here:
                        # A bare observe borrowed the single machine lease.
                        # Release it like the legacy one-shot path does, or
                        # every later start() fails until the lease ages out.
                        COMPUTER.finish(
                            session_id,
                            outcome="completed" if observed.get("ok") else "failed",
                            summary="one-shot computer_observe",
                        )
                return observed
            if name == "computer_inspect_ui":
                return COMPUTER.inspect_ui(session_id)
            if name == "computer_focus":
                return COMPUTER.focus(session_id, str(args.get("app") or ""))
            if name == "computer_act":
                return COMPUTER.act(session_id, args, cancel=cancel)
            if name == "computer_wait_for":
                condition = args.get("condition")
                if not isinstance(condition, dict):
                    return {"ok": False, "error": "condition must be an object"}
                return COMPUTER.wait_for(
                    session_id,
                    condition,
                    timeout_sec=float(args.get("timeout_sec") or 15.0),
                    cancel=cancel,
                )
            if name == "computer_assert":
                condition = args.get("condition")
                if not isinstance(condition, dict):
                    return {"ok": False, "error": "condition must be an object"}
                return COMPUTER.assert_condition(session_id, condition)
            if name == "computer_finish":
                return COMPUTER.finish(
                    session_id,
                    outcome=str(args.get("outcome") or "completed"),
                    summary=str(args.get("summary") or ""),
                )
            return {"ok": False, "error": f"unknown computer tool {name}"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    if name in {
        "list_schedules",
        "create_schedule",
        "update_schedule",
        "delete_schedule",
        "pause_schedule",
        "resume_schedule",
        "run_schedule_now",
    }:
        from rau.scheduler import SCHEDULER

        if name == "list_schedules":
            return {"ok": True, "schedules": SCHEDULER.store.list_schedules()}
        schedule_id = str(args.get("id") or "")
        try:
            if name == "create_schedule":
                return {"ok": True, "schedule": SCHEDULER.create(args)}
            if name == "update_schedule":
                changes = args.get("changes")
                if not isinstance(changes, dict):
                    return {"ok": False, "error": "changes must be an object"}
                return {
                    "ok": True,
                    "schedule": SCHEDULER.update(schedule_id, changes),
                }
            if name == "delete_schedule":
                return {"ok": SCHEDULER.delete(schedule_id), "id": schedule_id}
            if name == "pause_schedule":
                return {"ok": True, "schedule": SCHEDULER.pause(schedule_id)}
            if name == "resume_schedule":
                return {"ok": True, "schedule": SCHEDULER.resume(schedule_id)}
            return {"ok": True, "run": SCHEDULER.run_now(schedule_id)}
        except KeyError:
            return {"ok": False, "error": "unknown schedule", "id": schedule_id}
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    if name == "spawn_subagent":
        # Imported here because the orchestrator owns the loop that calls this
        # module; at module scope the two would import each other.
        from rau.agent.orchestrator import spawn_children

        goals = args.get("goals") or []
        if not isinstance(goals, list) or not all(
            isinstance(goal, str) and goal.strip() for goal in goals
        ):
            return {
                "ok": False,
                "error": "goals must be an array of non-empty strings",
            }
        return spawn_children(job_id or "", goals)

    if name == "finish":
        fields = (
            "artifacts",
            "mutations",
            "verification",
            "blockers",
            "remaining_risks",
        )
        completion: Dict[str, Any] = {
            "outcome": str(args.get("outcome") or "completed"),
            "summary": str(args.get("summary") or ""),
        }
        for field_name in fields:
            values = args.get(field_name) or []
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                return {"ok": False, "error": f"{field_name} must be an array of strings"}
            completion[field_name] = [value[:1000] for value in values[:100]]
        return {
            "ok": True,
            "finished": True,
            "summary": completion["summary"],
            "completion": completion,
        }

    if name in ("show_panel", "update_panel"):
        # The wall is shared: a worker hangs a panel exactly the way the face
        # does, and the same sandbox/CSP barriers apply because it is the same
        # store. `job_id` is stamped so the orchestrator can mention what this
        # job put up when it weaves the result.
        from rau.face import panels

        if name == "show_panel":
            return panels.show_panel(args, job_id=job_id, source="subagent")
        return panels.update_panel(args, job_id=job_id)

    if name == "use_skill":
        from rau.skills.runtime import use_skill_tool

        return use_skill_tool(str(args.get("name") or ""))

    if name == "list_skills":
        from rau.skills.loader import skills_public

        return {"ok": True, "skills": skills_public()}

    return {"ok": False, "error": f"unknown tool {name}"}


def _number(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    if value is None:
        # Models routinely send an explicit null for optional parameters;
        # that is "use the default", not a validation failure.
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not minimum <= parsed <= maximum:
        return None
    return parsed


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            proc.terminate()
        except OSError:
            return
    try:
        proc.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _tail_bytes(stream: Any, limit: int) -> Tuple[str, bool]:
    """Return the tail of the spool, and whether anything was dropped."""
    stream.flush()
    size = stream.tell()
    stream.seek(max(0, size - limit))
    return stream.read().decode("utf-8", errors="replace"), size > limit


def _run_shell(
    args: Dict[str, Any],
    cancel: Optional[threading.Event],
) -> Dict[str, Any]:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return {"ok": False, "error": "command must be a non-empty string"}
    if len(command) > MAX_SHELL_COMMAND_CHARS:
        return {
            "ok": False,
            "error": f"command exceeds {MAX_SHELL_COMMAND_CHARS} characters",
        }
    if cancel is not None and cancel.is_set():
        return {"ok": False, "cancelled": True, "error": "command cancelled"}
    timeout = _number(
        args.get("timeout_sec", SHELL_TIMEOUT_SEC),
        default=SHELL_TIMEOUT_SEC,
        minimum=1.0,
        maximum=MAX_SHELL_TIMEOUT_SEC,
    )
    if timeout is None:
        return {
            "ok": False,
            "error": f"timeout_sec must be between 1 and {MAX_SHELL_TIMEOUT_SEC}",
        }

    argv, warning = shell_argv(command)
    if warning == NO_SANDBOX_WARNING and not allow_unconfined_shell():
        return {
            "ok": False,
            "error": (
                "sandbox-exec is unavailable; refusing an unconfined shell "
                "command (set allow_unconfined_shell to override)"
            ),
        }
    started = time.monotonic()
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as stdout, (
        tempfile.SpooledTemporaryFile(max_size=256 * 1024)
    ) as stderr:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(ROOT),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                env=_shell_env(),
            )
        except OSError as exc:
            return {"ok": False, "error": f"could not start command: {exc}"}

        cancelled = False
        timed_out = False
        output_overflow = False
        while proc.poll() is None:
            if cancel is not None and cancel.wait(timeout=0.05):
                cancelled = True
                _terminate_process_tree(proc)
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                _terminate_process_tree(proc)
                break
            if (
                stdout.tell() > MAX_SHELL_OUTPUT_BYTES
                or stderr.tell() > MAX_SHELL_OUTPUT_BYTES
            ):
                output_overflow = True
                _terminate_process_tree(proc)
                break
            if cancel is None:
                time.sleep(0.05)

        try:
            code = proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            try:
                code = proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                # SIGKILL is already delivered; a process that still will not
                # die is stuck in the kernel. Report it as killed rather than
                # raise out of the tool loop.
                code = -signal.SIGKILL

        out, out_clipped = _tail_bytes(stdout, 8000)
        err_text, err_clipped = _tail_bytes(stderr, 2000)

    append_trace(
        "shell",
        {
            "cmd": "<redacted>",
            "cmd_len": len(command),
            "code": code,
            "confined": not warning,
            "cancelled": cancelled,
            "timed_out": timed_out,
            "output_overflow": output_overflow,
        },
    )
    result: Dict[str, Any] = {
        "ok": code == 0 and not cancelled and not timed_out and not output_overflow,
        "stdout": out,
        "stderr": err_text,
        "code": code,
    }
    if out_clipped or err_clipped:
        # The tail windows hide how much was dropped; say so plainly.
        result["truncated"] = True
    if cancelled:
        result.update(cancelled=True, error="command cancelled")
    elif timed_out:
        result.update(timed_out=True, error=f"command timed out after {timeout:g} seconds")
    elif output_overflow:
        result.update(
            output_overflow=True,
            error=(
                "command produced more than "
                f"{MAX_SHELL_OUTPUT_BYTES // (1024 * 1024)} MB of output"
            ),
        )
    if warning:
        result["warning"] = warning
    return result

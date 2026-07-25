"""Local tools available to the subagent."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from rau.agent.edit import edit_file, note_read
from rau.agent.sandbox import (
    NO_SANDBOX_WARNING,
    PathEscape,
    allow_unconfined_shell,
    resolve_in_root,
    shell_argv,
)
from rau.computer.cua import capture_screenshot_b64, execute_action
from rau.mcp.client import MCP
from rau.memory.store import append_diary, append_trace, recent_context, write_daily_log
from rau.paths import ROOT

SHELL_TIMEOUT_SEC = 120.0
MAX_SHELL_TIMEOUT_SEC = 600.0
MAX_SHELL_COMMAND_CHARS = 20_000


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
            "description": "On-demand computer use action (screenshot/click/type/key/scroll/wait).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "x2": {"type": "integer"},
                    "y2": {"type": "integer"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "dy": {"type": "integer"},
                    "seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 30,
                    },
                },
                "required": ["action"],
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
            "description": "Complete the hard task with a final summary for Rau to speak.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
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
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"could not read: {exc}", "path": str(path)}
        # Only a full read licenses a later edit; a truncated one would let the
        # model edit against a tail it never saw.
        if len(text) <= 50000:
            note_read(path)
        return {"ok": True, "path": str(path), "content": text[:50000]}

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
        if action.lower() == "screenshot":
            b64 = capture_screenshot_b64()
            if not b64:
                return {"ok": False, "action": "screenshot", "error": "screenshot capture failed"}
            return {"ok": True, "action": "screenshot", "image_b64_len": len(b64), "image_b64": b64[:80] + "..."}
        return execute_action(args, cancel=cancel)

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
        return {"ok": True, "finished": True, "summary": str(args.get("summary") or "")}

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


def _tail_bytes(stream: Any, limit: int) -> str:
    stream.flush()
    size = stream.tell()
    stream.seek(max(0, size - limit))
    return stream.read().decode("utf-8", errors="replace")


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
        while proc.poll() is None:
            if cancel is not None and cancel.wait(timeout=0.05):
                cancelled = True
                _terminate_process_tree(proc)
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                _terminate_process_tree(proc)
                break
            if cancel is None:
                time.sleep(0.05)

        try:
            code = proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            code = proc.wait(timeout=2.0)

        out = _tail_bytes(stdout, 8000)
        err_text = _tail_bytes(stderr, 2000)

    append_trace(
        "shell",
        {
            "cmd": "<redacted>",
            "cmd_len": len(command),
            "code": code,
            "confined": not warning,
            "cancelled": cancelled,
            "timed_out": timed_out,
        },
    )
    result: Dict[str, Any] = {
        "ok": code == 0 and not cancelled and not timed_out,
        "stdout": out,
        "stderr": err_text,
        "code": code,
    }
    if cancelled:
        result.update(cancelled=True, error="command cancelled")
    elif timed_out:
        result.update(timed_out=True, error=f"command timed out after {timeout:g} seconds")
    if warning:
        result["warning"] = warning
    return result

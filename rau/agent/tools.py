"""Local tools available to the subagent."""
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from rau.agent.edit import edit_file, note_read
from rau.agent.sandbox import PathEscape, resolve_in_root, shell_argv
from rau.computer.cua import capture_screenshot_b64, execute_action
from rau.mcp.client import MCP
from rau.memory.store import append_diary, append_trace, recent_context, write_daily_log
from rau.paths import ROOT

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command on the local Mac, from the project root. "
                "Writes are confined to the project (plus temp and cache dirs) "
                "by the macOS sandbox; reads and network are not. If the "
                "sandbox is unavailable the result carries a warning and the "
                "command ran unconfined."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
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
                    "tools": {"type": "array"},
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
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "dy": {"type": "integer"},
                    "seconds": {"type": "number"},
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
) -> Dict[str, Any]:
    """
    Execute one tool.

    `job_id` identifies the caller so a subagent can spawn work beneath itself;
    it is None for the face, which reaches nesting through its own tools.
    """
    args = arguments or {}
    if name == "run_shell":
        cmd = str(args.get("command") or "")
        argv, warning = shell_argv(cmd)
        r = subprocess.run(
            argv,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout or "")[-8000:]
        err = (r.stderr or "")[-2000:]
        append_trace("shell", {"cmd": cmd, "code": r.returncode, "confined": not warning})
        result: Dict[str, Any] = {
            "ok": r.returncode == 0,
            "stdout": out,
            "stderr": err,
            "code": r.returncode,
        }
        if warning:
            result["warning"] = warning
        return result

    if name == "read_file":
        try:
            path = resolve_in_root(str(args.get("path") or ""))
        except PathEscape as exc:
            return {"ok": False, "error": str(exc)}
        if not path.is_file():
            return {"ok": False, "error": "not found", "path": str(path)}
        text = path.read_text(encoding="utf-8", errors="replace")
        # Only a full read licenses a later edit; a truncated one would let the
        # model edit against a tail it never saw.
        if len(text) <= 50000:
            note_read(path)
        return {"ok": True, "path": str(path), "content": text[:50000]}

    if name == "write_file":
        try:
            path = resolve_in_root(str(args.get("path") or ""))
        except PathEscape as exc:
            return {"ok": False, "error": str(exc)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(args.get("content") or ""), encoding="utf-8")
        note_read(path)
        append_trace("write_file", {"path": str(path)})
        return {"ok": True, "path": str(path)}

    if name == "edit_file":
        result = edit_file(
            str(args.get("path") or ""),
            str(args.get("old_string") or ""),
            str(args.get("new_string") or ""),
            bool(args.get("replace_all")),
        )
        append_trace("edit_file", {"path": result.get("path"), "ok": result.get("ok")})
        return result

    if name == "memory_write":
        p = append_diary(str(args.get("role") or "note"), str(args.get("text") or ""))
        return {"ok": True, "path": str(p)}

    if name == "memory_read":
        return {"ok": True, "context": recent_context()}

    if name == "composio_search":
        return MCP.composio_search(str(args.get("query") or ""))

    if name == "composio_execute":
        tools = args.get("tools") or []
        if not isinstance(tools, list):
            tools = [tools]
        return MCP.composio_execute(tools)

    if name == "cua_action":
        if (args.get("action") or "").lower() == "screenshot":
            b64 = capture_screenshot_b64()
            return {"ok": True, "action": "screenshot", "image_b64_len": len(b64), "image_b64": b64[:80] + "..."}
        return execute_action(args)

    if name == "spawn_subagent":
        # Imported here because the orchestrator owns the loop that calls this
        # module; at module scope the two would import each other.
        from rau.agent.orchestrator import spawn_children

        goals = args.get("goals") or []
        if isinstance(goals, str):
            goals = [goals]
        return spawn_children(job_id or "", [str(g) for g in goals])

    if name == "finish":
        return {"ok": True, "finished": True, "summary": str(args.get("summary") or "")}

    if name == "use_skill":
        from rau.skills.runtime import use_skill_tool

        return use_skill_tool(str(args.get("name") or ""))

    if name == "list_skills":
        from rau.skills.loader import skills_public

        return {"ok": True, "skills": skills_public()}

    return {"ok": False, "error": f"unknown tool {name}"}

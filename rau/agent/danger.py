"""Danger taxonomy for confirm-gated actions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rau.agent.sandbox import PathEscape, resolve_in_root
from rau.paths import SKILLS_DIR

DANGEROUS_SHELL = re.compile(
    r"\b(rm\s+-rf|sudo\s+|mkfs|dd\s+if=|shutdown|reboot|diskutil\s+erase|"
    r"git\s+push\s+--force|curl\s+[^\n]*\|\s*sh|chmod\s+-R\s+777)\b",
    re.I,
)

DANGEROUS_MCP = re.compile(
    r"(send_email|send.?mail|create.?draft.?and.?send|post.?tweet|publish|"
    r"delete.?repo|transfer.?money|place.?order|purchase|wire.?transfer|"
    r"COMPOSIO_MULTI_EXECUTE.*GMAIL.*SEND|slack.*chat.?post)",
    re.I,
)

DANGEROUS_CUA = {"type", "key", "click", "double_click", "drag", "move"}
def _target_path(given: str) -> Path:
    """
    The path the file tools will actually act on.

    Models write relative paths, and the tools root those at the project rather
    than at the process working directory. Resolving the same way keeps the gate
    from inspecting some unrelated file — or nothing at all — while a real one is
    about to be overwritten. A path that escapes the root is handed back as
    written, since the tool refuses it anyway.
    """
    try:
        return resolve_in_root(given)
    except PathEscape:
        return Path(given).expanduser()


def classify_tool(name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (needs_confirm, summary)."""
    n = (name or "").lower()
    args = arguments if isinstance(arguments, dict) else {}
    if "_raw" in args:
        return False, ""

    if n in ("run_shell", "shell"):
        cmd = str(args.get("command") or args.get("cmd") or "").strip()
        if not cmd:
            return False, ""
        # Shell is an escape hatch with host reads, subprocesses and network;
        # blocklists are trivially bypassed via an interpreter or generated
        # script. Every non-empty command therefore requires an explicit yes.
        preview = cmd if len(cmd) <= 500 else f"{cmd[:240]} … {cmd[-240:]}"
        label = "Dangerous shell" if DANGEROUS_SHELL.search(cmd) else "Run shell command"
        return True, f"{label}: {preview}"

    if n in ("write_file", "edit_file", "delete_file"):
        path = str(args.get("path") or "")
        target = _target_path(path)
        # Both forms are checked: the model writes the raw one, the tool acts on
        # the resolved one, and a pattern can hide in either.
        target_text = f"{path}\n{target}".lower()
        if any(x in target_text for x in ("/system", "/usr/", ".ssh", ".env")):
            return True, f"Sensitive file write/delete: {path}"
        skills_root = SKILLS_DIR.resolve()
        if target == skills_root or skills_root in target.parents:
            return True, f"Install or modify executable agent instructions: {path}"
        if n == "delete_file":
            return True, f"Delete file: {path}"
        # A whole-file rewrite of something that already exists is the one write
        # that can destroy work the model never read; a scoped edit cannot.
        if n == "write_file" and target.is_file():
            return True, f"Overwrite existing file: {target}"
        return False, ""

    if n == "read_file":
        path = str(args.get("path") or "")
        target = _target_path(path)
        # The read side of the .env check above: once secret contents reach
        # the model's context they can be sent anywhere, so the read itself
        # is what has to be gated. Both forms are checked, as on writes.
        target_text = f"{path}\n{target}".lower()
        if any(x in target_text for x in (".env", ".ssh", "secret", "credential")):
            return True, f"Sensitive file read: {path}"
        return False, ""

    if n.startswith("composio") or n.startswith("mcp_") or "execute" in n:
        if n.endswith("search") or n.endswith("list") or n.endswith("status"):
            return False, ""
        blob = f"{name} {args}"
        if DANGEROUS_MCP.search(blob):
            return True, f"External side-effect via MCP: {name}"
        # Unknown execute calls are side effects until proven otherwise.
        return True, f"Run external app action via {name}: {str(args)[:500]}"

    if n in ("cua_action", "computer_action"):
        action = str(args.get("action") or args.get("type") or "").lower()
        if action in DANGEROUS_CUA:
            return True, f"Computer use action: {action}"
        return False, ""

    if n == "computer_act":
        action = str(args.get("action") or "").lower()
        return True, f"Verified computer use action: {action or 'unknown'}"

    if n in {
        "create_schedule",
        "update_schedule",
        "delete_schedule",
        "run_schedule_now",
        "pause_schedule",
        "resume_schedule",
    }:
        return True, f"Change durable scheduled work via {name}: {str(args)[:500]}"

    if args.get("requires_confirm"):
        return True, str(args.get("summary") or name)

    return False, ""

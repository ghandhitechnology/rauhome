"""Danger taxonomy for confirm-gated actions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rau.agent.sandbox import PathEscape, resolve_in_root

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

DANGEROUS_CUA = {"type", "key", "click", "double_click", "drag"}


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
    args = arguments or {}

    if n in ("run_shell", "shell"):
        cmd = str(args.get("command") or args.get("cmd") or "")
        if DANGEROUS_SHELL.search(cmd):
            return True, f"Dangerous shell: {cmd[:180]}"
        if re.search(r"\b(rm|mv|chmod|chown|kill|launchctl)\b", cmd, re.I):
            return True, f"System-altering shell: {cmd[:180]}"
        return False, ""

    if n in ("write_file", "edit_file", "delete_file"):
        path = str(args.get("path") or "")
        target = _target_path(path)
        # Both forms are checked: the model writes the raw one, the tool acts on
        # the resolved one, and a pattern can hide in either.
        if any(x in f"{path}\n{target}" for x in ("/System", "/usr/", ".ssh", ".env")):
            return True, f"Sensitive file write/delete: {path}"
        if n == "delete_file":
            return True, f"Delete file: {path}"
        # A whole-file rewrite of something that already exists is the one write
        # that can destroy work the model never read; a scoped edit cannot.
        if n == "write_file" and target.is_file():
            return True, f"Overwrite existing file: {target}"
        return False, ""

    if n.startswith("composio") or n.startswith("mcp_") or "execute" in n:
        blob = f"{name} {args}"
        if DANGEROUS_MCP.search(blob):
            return True, f"External side-effect via MCP: {name}"
        # Default confirm for Composio multi-execute writes
        if "MULTI_EXECUTE" in name.upper() or args.get("danger"):
            return True, f"Composio/MCP action: {name}"
        return False, ""

    if n in ("cua_action", "computer_action"):
        action = str(args.get("action") or args.get("type") or "")
        if action in DANGEROUS_CUA:
            return True, f"Computer use action: {action}"
        return False, ""

    if args.get("requires_confirm"):
        return True, str(args.get("summary") or name)

    return False, ""

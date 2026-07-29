"""Per-scope permission modes: auto / bypass / readonly.

Scopes:
  - subagents: hard-task workers and job spawn
  - room: Face + Talk face tools
  - heartbeats: proactive presence nudges
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from rau.agent.danger import DANGEROUS_CUA, classify_tool
from rau.events import BUS
from rau.providers.registry import load_settings, save_settings

SCOPES = ("subagents", "room", "heartbeats")
MODES = ("auto", "bypass", "readonly")

DEFAULT_PERMISSIONS: Dict[str, str] = {
    "subagents": "auto",
    "room": "auto",
    "heartbeats": "auto",
}

#: Tools always allowed under read-only (no host mutation).
#: composio_search is deliberately absent: its query text is model-authored
#: and leaves the machine, which is an exfiltration channel, not a read.
_READONLY_ALLOW = frozenset(
    {
        "read_file",
        "memory_read",
        # Reading a page changes nothing on this machine.
        "browse_web",
        "list_skills",
        "use_skill",
        "body_choreography",
        "finish",
        "cancel_hard_task",
        "list_schedules",
        "computer_status",
        "computer_observe",
        "computer_inspect_ui",
        "computer_wait_for",
        "computer_assert",
        "computer_finish",
    }
)


def normalize_permissions(raw: Any) -> Dict[str, str]:
    out = dict(DEFAULT_PERMISSIONS)
    if not isinstance(raw, dict):
        return out
    for scope in SCOPES:
        mode = str(raw.get(scope) or out[scope]).lower().strip()
        if mode == "full_bypass":
            mode = "bypass"
        if mode == "read_only":
            mode = "readonly"
        if mode in MODES:
            out[scope] = mode
    return out


def _normalize_mode(raw: Any) -> Optional[str]:
    mode = str(raw or "").lower().strip()
    if mode == "full_bypass":
        mode = "bypass"
    if mode == "read_only":
        mode = "readonly"
    return mode if mode in MODES else None


def get_permissions() -> Dict[str, str]:
    settings = load_settings()
    return normalize_permissions(settings.get("permissions"))


def global_mode(perms: Optional[Dict[str, str]] = None) -> str:
    """
    The single mode the UI shows.

    The global labels are promises about every scope.  In particular, "Full
    bypass" must never be shown while even one scope can still ask.  Mixed
    per-scope settings therefore appear as Auto; choosing a global mode in the
    UI will lock all scopes together via ``set_permissions``.
    """
    p = perms if perms is not None else get_permissions()
    values = [p.get(s, "auto") for s in SCOPES]
    if len(set(values)) == 1:
        return values[0]
    return "auto"


def mode_for(scope: str) -> str:
    """
    Effective mode for one scope.

    This honours the scope it is given. It previously returned the global mode
    regardless, which made the whole per-scope model decorative: settings.json
    persists three keys and every call site passes a distinct scope, but
    `permissions.subagents = "readonly"` would run with the room's mode — and
    silently grant *more* than was asked for whenever the room was looser.
    """
    return get_permissions().get(scope, "auto")


def set_permissions(partial: Dict[str, Any]) -> Dict[str, str]:
    """Set permission mode. Prefer ``mode`` (global); else per-scope keys."""
    current = get_permissions()
    merged = dict(current)
    if isinstance(partial, dict):
        global_raw = partial.get("mode")
        if global_raw is not None:
            mode = _normalize_mode(global_raw)
            if mode is None:
                raise ValueError(f"invalid mode: {global_raw!r}")
            # `mode` is the global setter the UI uses: it moves every scope.
            merged = {scope: mode for scope in SCOPES}
        else:
            # Explicit per-scope keys are applied as given. They used to be
            # collapsed onto whichever scope happened to be listed first, so
            # asking for {"subagents": "bypass", "room": "readonly"} silently
            # granted bypass to nothing and read-only to everything.
            for scope in SCOPES:
                if scope not in partial:
                    continue
                mode = _normalize_mode(partial.get(scope))
                if mode is None:
                    raise ValueError(f"invalid mode for {scope}: {partial.get(scope)!r}")
                merged[scope] = mode
    settings = load_settings()
    settings["permissions"] = merged
    save_settings(settings)
    BUS.emit(
        "permissions_changed",
        permissions=merged,
        mode=global_mode(merged),
    )
    return merged


def is_readonly_allowed(name: str, arguments: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a tool may run when the scope is read-only."""
    n = (name or "").lower().strip()
    args = arguments if isinstance(arguments, dict) else {}
    if n == "computer_observe" and not str(args.get("session_id") or "").strip():
        # Without a session the call starts one, seizing the single machine
        # lease — a mutation read-only mode must not make, and one that
        # wedges every other session if the observe then fails.
        return False
    if n in _READONLY_ALLOW:
        return True
    if n.startswith("composio") or n.startswith("mcp_") or "execute" in n:
        # "search" is not a lookup: the query is model-authored text sent to
        # a remote API, so it rides out of the read-only jail. list/status
        # take no such payload and stay allowed.
        if n.endswith("list") or n.endswith("status"):
            return True
        return False
    if n in ("cua_action", "computer_action"):
        action = str(args.get("action") or args.get("type") or "").lower()
        if action in DANGEROUS_CUA:
            return False
        return action in ("", "screenshot", "scroll", "wait", "status", "cua_status")
    if n.startswith("computer_"):
        return n in {
            "computer_status",
            "computer_observe",
            "computer_inspect_ui",
            "computer_wait_for",
            "computer_assert",
            "computer_finish",
        }
    if n == "list_schedules":
        return True
    return False


def tool_decision(
    scope: str, name: str, arguments: Optional[Dict[str, Any]] = None
) -> str:
    """
    Return ``allow`` | ``deny`` | ``confirm`` for a tool under the scope's mode.

    Face (room) treats ``confirm`` as refuse-and-escalate (cannot block mid-turn).
    Subagents treat ``confirm`` as ``_await_confirm``.
    """
    args = arguments if isinstance(arguments, dict) else {}
    mode = mode_for(scope)
    if mode == "readonly":
        return "allow" if is_readonly_allowed(name, args) else "deny"
    needs, summary = classify_tool(name, args)
    if mode == "bypass":
        if needs:
            # YOLO mode is easy to leave on; make every dangerous call visible.
            import logging

            from rau.memory.store import append_trace

            logging.getLogger("rau.permissions").warning(
                "permissions bypass: running %s without confirm (%s) [scope=%s]",
                name,
                summary or name,
                scope,
            )
            append_trace(
                "permission_bypass",
                {"scope": scope, "tool": name, "summary": summary or name},
            )
        return "allow"
    # auto
    return "confirm" if needs else "allow"


def jobs_allowed() -> bool:
    return mode_for("subagents") != "readonly"


def heartbeat_nudge_allowed() -> bool:
    return mode_for("heartbeats") != "readonly"


def deny_result(name: str, *, reason: str = "blocked by read-only permissions") -> Dict[str, Any]:
    return {
        "ok": False,
        "error": reason,
        "tool": name,
        "permission": "readonly",
    }

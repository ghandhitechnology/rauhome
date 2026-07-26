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
_READONLY_ALLOW = frozenset(
    {
        "read_file",
        "memory_read",
        "list_skills",
        "use_skill",
        "body_choreography",
        "finish",
        "cancel_hard_task",
        "composio_search",
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
    """Single UI mode. If scopes diverge, prefer room then majority → auto."""
    p = perms if perms is not None else get_permissions()
    values = [p.get(s, "auto") for s in SCOPES]
    if len(set(values)) == 1:
        return values[0]
    return str(p.get("room") or "auto")


def mode_for(scope: str) -> str:
    """Effective mode for a scope — follows the global mode."""
    return global_mode()


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
            merged = {scope: mode for scope in SCOPES}
        else:
            for scope in SCOPES:
                if scope not in partial:
                    continue
                mode = _normalize_mode(partial.get(scope))
                if mode is None:
                    raise ValueError(f"invalid mode for {scope}: {partial.get(scope)!r}")
                merged[scope] = mode
            # Keep scopes in lockstep for the global UI.
            if any(scope in partial for scope in SCOPES):
                lock = _normalize_mode(
                    partial.get("room")
                    or partial.get("subagents")
                    or partial.get("heartbeats")
                )
                if lock:
                    merged = {scope: lock for scope in SCOPES}
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
    if n in _READONLY_ALLOW:
        return True
    if n.startswith("composio") or n.startswith("mcp_") or "execute" in n:
        if n.endswith("search") or n.endswith("list") or n.endswith("status"):
            return True
        return False
    if n in ("cua_action", "computer_action"):
        action = str(args.get("action") or args.get("type") or "").lower()
        if action in DANGEROUS_CUA:
            return False
        return action in ("", "screenshot", "scroll", "wait", "status", "cua_status")
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

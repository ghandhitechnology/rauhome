"""Map Rau effort levels onto provider-native reasoning fields."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rau.providers.catalog import reasoning_for

EFFORT_ORDER = ("low", "medium", "high", "max")


def clamp_effort(provider: str, model: str, effort: Optional[str]) -> Optional[str]:
    """
    Return a valid effort for this model, or None when reasoning is unsupported.

    When unsupported, callers should omit reasoning fields and may leave the
    stored effort alone (or set the catalog default for display).
    """
    cap = reasoning_for(provider, model)
    if not cap.get("supported"):
        return None
    allowed: List[str] = list(cap.get("levels") or [])
    if not allowed:
        return None
    raw = str(effort or cap.get("default") or "medium").lower().strip()
    if raw in allowed:
        return raw
    # Nearest higher, then lower, then default.
    if raw in EFFORT_ORDER:
        idx = EFFORT_ORDER.index(raw)
        for j in range(idx, len(EFFORT_ORDER)):
            if EFFORT_ORDER[j] in allowed:
                return EFFORT_ORDER[j]
        for j in range(idx, -1, -1):
            if EFFORT_ORDER[j] in allowed:
                return EFFORT_ORDER[j]
    default = str(cap.get("default") or allowed[0])
    return default if default in allowed else allowed[0]


def build_reasoning_fields(
    provider: str, model: str, effort: Optional[str]
) -> Dict[str, Any]:
    """Fields to merge into a chat/completions (or Anthropic messages) payload."""
    cap = reasoning_for(provider, model)
    if not cap.get("supported"):
        return {}
    mapped = clamp_effort(provider, model, effort)
    if not mapped:
        return {}
    param = str(cap.get("param") or "openai")

    if param == "deepseek":
        # DeepSeek V4: only high/max are meaningful; enable thinking explicitly.
        wire = "max" if mapped == "max" else "high"
        return {
            "reasoning_effort": wire,
            "thinking": {"type": "enabled"},
        }

    if param == "kimi":
        wire = {"low": "low", "medium": "high", "high": "high", "max": "max"}.get(
            mapped, "high"
        )
        return {"reasoning_effort": wire}

    if param == "openai":
        return {"reasoning_effort": mapped}

    if param in ("anthropic_effort", "none"):
        if param == "none":
            return {}
        wire = {"low": "low", "medium": "high", "high": "high", "max": "max"}.get(
            mapped, "high"
        )
        return {"reasoning_effort": wire}

    return {"reasoning_effort": mapped}


def apply_reasoning_payload(
    payload: Dict[str, Any], provider: str, model: str, effort: Optional[str]
) -> Dict[str, Any]:
    """Merge reasoning fields; nest ``extra_body`` when present."""
    fields = build_reasoning_fields(provider, model, effort)
    if not fields:
        return payload
    extra = fields.pop("extra_body", None)
    payload.update(fields)
    if isinstance(extra, dict):
        nested = payload.get("extra_body")
        if isinstance(nested, dict):
            nested.update(extra)
        else:
            payload["extra_body"] = extra
    return payload


def slot_effort_view(provider: str, model: str, effort: Optional[str]) -> Dict[str, Any]:
    """API shape for one chat slot."""
    cap = reasoning_for(provider, model)
    supported = bool(cap.get("supported"))
    allowed = list(cap.get("levels") or [])
    if not supported:
        return {
            "supported": False,
            "allowed": [],
            "effort": str(effort or cap.get("default") or "medium"),
            "param": "none",
        }
    clamped = clamp_effort(provider, model, effort) or allowed[0]
    return {
        "supported": True,
        "allowed": allowed,
        "effort": clamped,
        "param": str(cap.get("param") or "openai"),
    }


def effort_snapshot(models: Dict[str, Any]) -> Dict[str, Any]:
    """Build GET /api/effort (+ status.effort) payload from models.json."""
    slots_out: Dict[str, Any] = {}
    top: Dict[str, str] = {}
    for slot_name, default in (("face", "medium"), ("subagent", "high"), ("dream", "medium")):
        slot = models.get(slot_name) or {}
        if not isinstance(slot, dict):
            slot = {}
        view = slot_effort_view(
            str(slot.get("provider") or "openrouter"),
            str(slot.get("model") or ""),
            str(slot.get("effort") or default),
        )
        slots_out[slot_name] = view
        top[slot_name] = str(view.get("effort") or default)
    return {
        **top,
        "levels": list(EFFORT_ORDER),
        "slots": slots_out,
    }

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

    if param == "anthropic":
        # Anthropic /v1/messages has no reasoning_effort knob; effort maps to
        # an extended-thinking token budget instead. Assumption: kimi_code's
        # Anthropic-compatible endpoint accepts the same thinking payload —
        # it cannot be verified without live API access.
        budget = {"low": 1024, "medium": 2048, "high": 4096, "max": 8192}.get(
            mapped, 4096
        )
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}

    if param == "none":
        return {}

    return {"reasoning_effort": mapped}


#: Anthropic rejects a thinking budget below this minimum, and any budget
#: that is not strictly below max_tokens.
_MIN_THINKING_BUDGET = 1024


def _reconcile_thinking_budget(payload: Dict[str, Any]) -> None:
    """Keep an enabled thinking budget strictly below ``max_tokens``.

    Anthropic answers HTTP 400 unless max_tokens > thinking.budget_tokens,
    and slot budgets (face 512, player 400, dream 2048, subagent 4096) sit
    at or under the mapped budgets (1024-8192). Clamp the budget to
    max_tokens - 1, or drop the thinking block when max_tokens cannot fit
    the minimum — sending no thinking beats a guaranteed 400.
    """
    thinking = payload.get("thinking")
    if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
        return
    max_tokens = payload.get("max_tokens")
    budget = thinking.get("budget_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or isinstance(budget, bool)
        or not isinstance(budget, int)
    ):
        return
    if max_tokens - 1 < _MIN_THINKING_BUDGET:
        payload.pop("thinking", None)
    elif budget >= max_tokens:
        thinking["budget_tokens"] = max_tokens - 1


def apply_reasoning_payload(
    payload: Dict[str, Any], provider: str, model: str, effort: Optional[str]
) -> Dict[str, Any]:
    """Merge reasoning fields; nest ``extra_body`` when present."""
    fields = build_reasoning_fields(provider, model, effort)
    if not fields:
        return payload
    extra = fields.pop("extra_body", None)
    payload.update(fields)
    _reconcile_thinking_budget(payload)
    if isinstance(extra, dict):
        nested = payload.get("extra_body")
        if isinstance(nested, dict):
            nested.update(extra)
        else:
            payload["extra_body"] = extra
    # Catalog-flagged models (strict OpenAI reasoning endpoints, Anthropic
    # thinking) reject a non-default temperature with HTTP 400 — omit it.
    if reasoning_for(provider, model).get("fixed_temperature"):
        payload.pop("temperature", None)
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
    for slot_name, default in (
        ("face", "medium"),
        ("subagent", "high"),
        ("player", "high"),
        ("dream", "medium"),
    ):
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

"""Slash-command parsing and per-turn skill activation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from rau.providers.registry import EFFORT_LEVELS, load_models, save_models
from rau.skills import goals
from rau.skills.loader import load_skill, skills_public


@dataclass
class PreparedTurn:
    user_text: str
    system_extra: str = ""
    immediate_reply: str = ""
    activate: List[str] = field(default_factory=list)


def use_skill_tool(name: str):
    skill = load_skill(name)
    if not skill:
        return {"ok": False, "error": "unknown skill", "name": str(name or "")}
    return {
        "ok": True,
        "name": skill.name,
        "description": skill.description,
        "prompt": skill.prompt_block(),
    }


def _skills_reply() -> str:
    lines = [f"{s['slash']} — {s['description']}" for s in skills_public()]
    return "Available skills:\n" + "\n".join(lines)


def _effort(arg: str) -> str:
    from rau.providers.reasoning import clamp_effort, reasoning_for

    models = load_models()
    face = models.get("face") or {}
    provider = str(face.get("provider") or "openrouter")
    model = str(face.get("model") or "")
    cap = reasoning_for(provider, model)
    current = str(face.get("effort") or "medium")
    requested = arg.strip().lower()
    if not cap.get("supported"):
        return (
            f"Face model {model or '(unset)'} has no reasoning control "
            f"(effort is currently stored as {current})."
        )
    allowed = list(cap.get("levels") or [])
    choices = ", ".join(allowed) if allowed else ", ".join(EFFORT_LEVELS)
    if not requested:
        return f"Face effort is {current}. Choose: {choices}."
    if requested not in EFFORT_LEVELS:
        return f"Unknown effort '{requested}'. Choose: {choices}."
    if requested not in allowed:
        return f"'{requested}' is not valid for {model}. Choose: {choices}."
    clamped = clamp_effort(provider, model, requested)
    if clamped is None:
        return f"Face model {model} has no reasoning control."
    models.setdefault("face", {})["effort"] = clamped
    save_models(models)
    return f"Face effort set to {clamped}."


def _goal(arg: str) -> str:
    value = arg.strip()
    if not value:
        current = goals.get_goal()
        return f"Active goal: {current['text']}" if current else "There is no active goal."
    if value.lower() in {"clear", "off", "none", "delete"}:
        result = goals.clear_goal()
        return "Active goal cleared." if result.get("ok") else f"Could not clear the goal: {result.get('error')}"
    result = goals.set_goal(value)
    if result.get("ok") is False:
        return f"Could not set the goal: {result.get('error')}"
    return f"Active goal set: {result['text']}"


def prepare_turn(user_text: str) -> PreparedTurn:
    raw = str(user_text or "").strip()
    if not raw.startswith("/"):
        return PreparedTurn(user_text=raw)

    token, _, arg = raw.partition(" ")
    name = token[1:].strip().lower().replace("_", "-")
    arg = arg.strip()
    if name == "skills":
        return PreparedTurn(user_text=raw, immediate_reply=_skills_reply())
    if name == "effort":
        return PreparedTurn(user_text=raw, immediate_reply=_effort(arg))
    if name == "goal":
        return PreparedTurn(user_text=raw, immediate_reply=_goal(arg), activate=["goal"])

    skill = load_skill(name)
    if not skill:
        return PreparedTurn(
            user_text=raw,
            immediate_reply=f"Unknown command /{name}. Use /skills to see what is available.",
        )

    instruction = skill.prompt_block()
    if arg:
        turn_text = arg
    else:
        turn_text = f"Use the /{skill.name} skill now. Ask for the minimum input needed to begin."
    return PreparedTurn(
        user_text=turn_text,
        system_extra=instruction,
        activate=[skill.name],
    )

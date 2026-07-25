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
    models = load_models()
    current = str((models.get("face") or {}).get("effort") or "medium")
    requested = arg.strip().lower()
    if not requested:
        return f"Face effort is {current}. Choose: {', '.join(EFFORT_LEVELS)}."
    if requested not in EFFORT_LEVELS:
        return f"Unknown effort '{requested}'. Choose: {', '.join(EFFORT_LEVELS)}."
    models.setdefault("face", {})["effort"] = requested
    save_models(models)
    return f"Face effort set to {requested}."


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

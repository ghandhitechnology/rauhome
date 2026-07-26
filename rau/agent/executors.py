"""Executor selection without starting optional backends during import."""
from __future__ import annotations

import re
from typing import Any, Dict

from rau.agent.protocol import AgentStep, JobResult
from rau.pi.supervisor import PI_SUPERVISOR
from rau.providers.registry import load_settings

_CODING = re.compile(
    r"\b(code|coding|repository|repo|bug|test|refactor|implement|"
    r"python|javascript|typescript|rust|file|build|lint|compile)\b",
    re.I,
)
_COMPUTER = re.compile(
    r"\b(click|type|keyboard|screen|window|desktop|computer|application|app)\b",
    re.I,
)
_SCHEDULE = re.compile(
    r"\b(schedule|scheduled|cron|recurring|every day|every week|interval)\b",
    re.I,
)
_EXTERNAL = re.compile(
    r"\b(email|calendar|slack|drive|notion|github|web service|account)\b",
    re.I,
)


def capabilities_for_goal(goal: str, executor: str) -> list[str]:
    if executor == "pi":
        return ["coding", "filesystem", "shell"]
    found = ["memory"]
    if _CODING.search(goal or ""):
        found.extend(("filesystem", "shell"))
    if _COMPUTER.search(goal or ""):
        found.append("computer_use")
    if _SCHEDULE.search(goal or ""):
        found.append("scheduling")
    if _EXTERNAL.search(goal or ""):
        found.append("external_apps")
    return list(dict.fromkeys(found))


def tools_for_goal(goal: str) -> list[Dict[str, Any]]:
    """Expose only tool schemas plausibly relevant to this plan step."""
    from rau.agent.tools import TOOL_SCHEMAS
    from rau.agent.tool_registry import descriptor

    capabilities = set(capabilities_for_goal(goal, "python"))
    names = {
        "memory_write",
        "memory_read",
        "finish",
        "use_skill",
        "list_skills",
        "spawn_subagent",
    }
    for schema in TOOL_SCHEMAS:
        name = str(schema.get("function", {}).get("name") or "")
        item = descriptor(name)
        if item is None:
            continue
        if item.capability in capabilities:
            names.add(name)
        if item.capability == "filesystem" and capabilities & {"filesystem", "shell"}:
            names.add(name)
    return [
        schema
        for schema in TOOL_SCHEMAS
        if schema.get("function", {}).get("name") in names
    ]


def routed_effort(
    goal: str, *, configured: str, attempt: int = 1, profile: str = "balanced"
) -> str:
    levels = ("low", "medium", "high", "max")
    score = 0
    text = goal or ""
    score += min(2, len(text) // 800)
    score += len(capabilities_for_goal(text, "python")) // 2
    if re.search(r"\b(migrate|architecture|security|race|debug|investigate)\b", text, re.I):
        score += 2
    if attempt > 1:
        score += min(2, attempt - 1)
    desired = "high" if score >= 3 else "medium"
    if score >= 6 and profile == "performance":
        desired = "max"
    ceiling = {"eco": "medium", "balanced": "high", "performance": "max"}.get(
        profile, "high"
    )
    configured = configured if configured in levels else "medium"
    target = max((desired, configured), key=levels.index)
    return min((target, ceiling), key=levels.index)


def select_executor(goal: str, requested: str = "auto") -> str:
    if requested in {"python", "pi"}:
        return requested
    settings = load_settings()
    mode = str(settings.get("subagent_executor") or "auto").lower()
    if mode in {"python", "pi"}:
        return mode if mode != "pi" or PI_SUPERVISOR.enabled() else "python"
    if PI_SUPERVISOR.enabled() and _CODING.search(goal or ""):
        return "pi"
    return "python"


def executor_health() -> Dict[str, Any]:
    return {
        "python": PYTHON_EXECUTOR.health(),
        "pi": PI_EXECUTOR.health(),
    }


class PythonExecutor:
    """Native execution backend; lifecycle authority remains with the scheduler."""

    name = "python"

    def start(
        self,
        step: AgentStep,
        **kwargs: Any,
    ) -> JobResult:
        runner = kwargs.get("runner")
        if not callable(runner):
            raise ValueError("PythonExecutor.start requires a runner")
        value = runner()
        if isinstance(value, JobResult):
            return value
        if isinstance(value, dict):
            return JobResult(
                outcome=str(value.get("outcome") or "completed"),
                summary=str(value.get("summary") or step.title),
                artifacts=list(value.get("artifacts") or []),
                mutations=list(value.get("mutations") or []),
                verification=list(value.get("verification") or []),
                blockers=list(value.get("blockers") or []),
                remaining_risks=list(value.get("remaining_risks") or []),
            )
        if isinstance(value, str):
            return JobResult(outcome="completed", summary=value)
        if value is None:
            raise RuntimeError("worker exited without a terminal result")
        return JobResult(outcome="completed", summary=step.title)

    def cancel(self, step: AgentStep) -> bool:
        # The scheduler/orchestrator owns the cancellation event and durable
        # transition. Backends deliberately have no independent state machine.
        return bool(step.id)

    def resume(self, step: AgentStep, **kwargs: Any) -> JobResult:
        return self.start(step, **kwargs)

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "backend": self.name}


class PiExecutor(PythonExecutor):
    """Lazy Pi backend using the same structured execution contract."""

    name = "pi"

    def health(self) -> Dict[str, Any]:
        return PI_SUPERVISOR.health()


PYTHON_EXECUTOR = PythonExecutor()
PI_EXECUTOR = PiExecutor()


def get_executor(name: str) -> PythonExecutor:
    return PI_EXECUTOR if name == "pi" else PYTHON_EXECUTOR

"""Shared durable plan/step/result shapes for execution backends."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class AgentStep:
    id: str
    job_id: str
    ordinal: int
    title: str
    goal: str = ""
    executor: str = "python"
    state: str = "queued"
    effect_class: str = "read"
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    expected_output: Dict[str, Any] = field(default_factory=dict)
    expected_evidence: List[str] = field(default_factory=list)
    preconditions: List[Dict[str, Any]] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    attempt: int = 0
    retry_budget: int = 1
    strategy: str = "execute the requested goal and verify the result"
    timeout_sec: float = 300.0
    concurrency_key: str = ""
    plan_revision: int = 1
    idempotency_key: Optional[str] = None
    effect_state: str = "none"
    terminal_reason: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentPlan:
    goal: str
    steps: List[AgentStep]
    capabilities: List[str] = field(default_factory=list)
    expected_evidence: List[str] = field(default_factory=list)
    budget: Dict[str, Any] = field(default_factory=dict)
    revision: int = 1

    @classmethod
    def single(
        cls,
        job_id: str,
        goal: str,
        *,
        executor: str,
        budget: Optional[Dict[str, Any]] = None,
    ) -> "AgentPlan":
        from rau.agent.executors import capabilities_for_goal

        capabilities = capabilities_for_goal(goal, executor)
        step = AgentStep(
            id=str(uuid.uuid4()),
            job_id=job_id,
            ordinal=0,
            title=goal[:300],
            goal=goal,
            executor=executor,
            capabilities=capabilities,
            expected_evidence=["structured completion summary", "verification performed"],
            expected_output={"type": "job_result"},
        )
        return cls(
            goal=goal,
            steps=[step],
            capabilities=capabilities,
            expected_evidence=list(step.expected_evidence),
            budget=dict(budget or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["steps"] = [step.to_dict() for step in self.steps]
        return value

    def validate(self, *, max_steps: int = 24) -> None:
        if not self.steps or len(self.steps) > max_steps:
            raise ValueError(f"plan must contain 1..{max_steps} steps")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step ids must be unique")
        known = set(ids)
        for step in self.steps:
            if not step.goal.strip():
                raise ValueError(f"step {step.id} has no goal")
            if step.executor not in {"python", "pi"}:
                raise ValueError(f"step {step.id} has invalid executor")
            if step.effect_class not in {
                "read",
                "local_mutation",
                "external_mutation",
                "unknown",
            }:
                raise ValueError(f"step {step.id} has invalid effect class")
            if any(dep not in known or dep == step.id for dep in step.dependencies):
                raise ValueError(f"step {step.id} has an invalid dependency")
            if step.retry_budget < 0 or step.timeout_sec <= 0:
                raise ValueError(f"step {step.id} has invalid budget")
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {step.id: step for step in self.steps}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependencies contain a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in by_id[step_id].dependencies:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)

    def ready_steps(self) -> List[AgentStep]:
        completed = {step.id for step in self.steps if step.state == "completed"}
        return [
            step
            for step in self.steps
            if step.state == "queued" and set(step.dependencies) <= completed
        ]


@dataclass
class JobResult:
    outcome: str
    summary: str
    artifacts: List[str] = field(default_factory=list)
    mutations: List[str] = field(default_factory=list)
    verification: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    remaining_risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobExecutor(Protocol):
    name: str

    def start(self, step: AgentStep, **kwargs: Any) -> JobResult: ...

    def cancel(self, step: AgentStep) -> bool: ...

    def resume(self, step: AgentStep, **kwargs: Any) -> JobResult: ...

    def health(self) -> Dict[str, Any]: ...

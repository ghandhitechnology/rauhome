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
    executor: str = "python"
    state: str = "queued"
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    expected_evidence: List[str] = field(default_factory=list)
    preconditions: List[Dict[str, Any]] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    attempt: int = 0
    strategy: str = "execute the requested goal and verify the result"
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
            executor=executor,
            capabilities=capabilities,
            expected_evidence=["structured completion summary", "verification performed"],
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

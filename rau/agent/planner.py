"""Hybrid, deterministic planning and DAG validation.

The planner is intentionally local: opening the activity inspector and
deciding whether work needs a plan never adds a provider round or changes the
configured reasoning effort. Execution steps still use the selected provider.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from rau.agent.executors import capabilities_for_goal
from rau.agent.protocol import AgentPlan, AgentStep

INITIAL_STEP_LIMIT = 16
TOTAL_STEP_LIMIT = 24
_MUTATION_MARKERS = re.compile(
    r"\b(?:add|apply|build|change|click|create|delete|deploy|edit|fix|implement|"
    r"install|move|post|push|refactor|remove|rename|send|submit|type|update|write)\b",
    re.IGNORECASE,
)
_DEEP_MARKERS = re.compile(
    r"\b(?:agentic|complete|deep|multi[- ]?step|plan|research|thorough|verify)\b",
    re.IGNORECASE,
)
_SINGLE_READ_MARKERS = re.compile(
    r"^\s*(?:check|describe|explain|find|inspect|list|read|show|summarize|what|where|who)\b",
    re.IGNORECASE,
)


def effect_for_goal(goal: str) -> str:
    lower = goal.lower()
    if any(word in lower for word in ("send ", "post ", "deploy ", "submit ")):
        return "external_mutation"
    if _MUTATION_MARKERS.search(goal):
        return "local_mutation"
    return "read"


def needs_structured_plan(
    goal: str,
    *,
    scheduled: bool = False,
    previously_failed: bool = False,
) -> bool:
    text = goal.strip()
    clauses = [part for part in re.split(r"(?:\n+|;\s+)", text) if part.strip()]
    if scheduled or previously_failed or len(clauses) > 1:
        return True
    if _MUTATION_MARKERS.search(text) or _DEEP_MARKERS.search(text):
        return True
    # A short goal with no mutation/deep-work signal is the cheap read-only
    # path even when it is phrased as a noun rather than "read/list/show".
    return len(text) > 240


def _step(
    job_id: str,
    ordinal: int,
    title: str,
    goal: str,
    *,
    executor: str,
    effect: str = "read",
    dependencies: Optional[List[str]] = None,
    revision: int = 1,
    retry_budget: int = 1,
) -> AgentStep:
    capabilities = capabilities_for_goal(goal, executor)
    return AgentStep(
        id=str(uuid.uuid4()),
        job_id=job_id,
        ordinal=ordinal,
        title=title[:300],
        goal=goal,
        executor=executor,
        effect_class=effect,
        capabilities=capabilities,
        dependencies=list(dependencies or []),
        expected_output={"type": "job_result", "non_empty": True},
        expected_evidence=[
            "structured completion summary",
            "verification evidence" if effect != "read" else "source evidence",
        ],
        retry_budget=retry_budget,
        timeout_sec=600.0 if effect != "read" else 300.0,
        concurrency_key=(
            "computer"
            if "computer" in capabilities
            else ("mutation" if effect != "read" else "")
        ),
        plan_revision=revision,
    )


def build_plan(
    job_id: str,
    goal: str,
    *,
    executor: str,
    budget: Optional[Dict[str, Any]] = None,
    scheduled: bool = False,
    previously_failed: bool = False,
) -> AgentPlan:
    if not needs_structured_plan(
        goal, scheduled=scheduled, previously_failed=previously_failed
    ):
        plan = AgentPlan.single(job_id, goal, executor=executor, budget=budget)
        plan.validate(max_steps=INITIAL_STEP_LIMIT)
        return plan

    effect = effect_for_goal(goal)
    inspect = _step(
        job_id,
        0,
        "Inspect relevant context",
        (
            "Inspect only the context needed for this goal. Do not mutate anything. "
            f"Return concise findings and evidence.\n\nOverall goal: {goal}"
        ),
        executor=executor,
        effect="read",
        retry_budget=2,
    )
    execute = _step(
        job_id,
        1,
        "Execute the requested work" if effect != "read" else "Synthesize findings",
        (
            "Use the dependency findings to accomplish this bounded step. "
            f"Overall goal: {goal}"
        ),
        executor=executor,
        effect=effect,
        dependencies=[inspect.id],
        retry_budget=2,
    )
    steps = [inspect, execute]
    if effect != "read" or _DEEP_MARKERS.search(goal):
        verify = _step(
            job_id,
            2,
            "Verify the result",
            (
                "Verify the completed work against the original goal. Prefer "
                "read-only checks. Report concrete evidence and remaining risks.\n\n"
                f"Overall goal: {goal}"
            ),
            executor=executor,
            effect="read",
            dependencies=[execute.id],
            retry_budget=1,
        )
        steps.append(verify)
    plan = AgentPlan(
        goal=goal,
        steps=steps,
        capabilities=sorted({cap for step in steps for cap in step.capabilities}),
        expected_evidence=["step evidence", "terminal structured result"],
        budget=dict(budget or {}),
    )
    plan.validate(max_steps=INITIAL_STEP_LIMIT)
    return plan


def add_steering_revision(
    plan: AgentPlan,
    instruction: str,
    *,
    executor: str,
) -> AgentStep:
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("steering instruction is empty")
    if len(instruction) > 4000:
        raise ValueError("steering instruction exceeds 4000 characters")
    if len(plan.steps) >= TOTAL_STEP_LIMIT:
        raise ValueError("plan step budget exhausted")
    plan.revision += 1
    active_dependencies = [
        step.id
        for step in plan.steps
        if step.state in {"running", "completed"}
    ]
    step = _step(
        plan.steps[0].job_id,
        len(plan.steps),
        "Apply user steering",
        (
            f"Apply this user steering within the original goal and budget: "
            f"{instruction}\n\nOriginal goal: {plan.goal}"
        ),
        executor=executor,
        effect=effect_for_goal(instruction),
        dependencies=active_dependencies,
        revision=plan.revision,
        retry_budget=1,
    )
    plan.steps.append(step)
    plan.validate(max_steps=TOTAL_STEP_LIMIT)
    return step


def add_repair_revision(
    plan: AgentPlan,
    rejected_step: AgentStep,
    reason: str,
    *,
    executor: str,
) -> tuple[AgentStep, AgentStep]:
    """Replace rejected final evidence with a repair and fresh verification."""
    if len(plan.steps) + 2 > TOTAL_STEP_LIMIT:
        raise ValueError("plan step budget exhausted")
    plan.revision += 1
    repair = _step(
        rejected_step.job_id,
        len(plan.steps),
        "Repair the rejected result",
        (
            "Repair the work within the original goal and existing authority. "
            f"Verifier rejection: {reason}\n\nOriginal goal: {plan.goal}"
        ),
        executor=executor,
        effect="local_mutation",
        dependencies=list(rejected_step.dependencies),
        revision=plan.revision,
        retry_budget=1,
    )
    verify = _step(
        rejected_step.job_id,
        len(plan.steps) + 1,
        "Verify the repaired result",
        (
            "Perform read-only verification of the repair and return concrete "
            f"evidence.\n\nOriginal goal: {plan.goal}"
        ),
        executor=executor,
        effect="read",
        dependencies=[repair.id],
        revision=plan.revision,
        retry_budget=1,
    )
    plan.steps.extend((repair, verify))
    plan.validate(max_steps=TOTAL_STEP_LIMIT)
    return repair, verify

from __future__ import annotations

import pytest

from rau.agent.planner import (
    TOTAL_STEP_LIMIT,
    add_repair_revision,
    add_steering_revision,
    build_plan,
    needs_structured_plan,
)
from rau.agent.protocol import AgentPlan, AgentStep
from rau.agent.tool_registry import adapt_result, descriptor, validate_arguments


def test_trivial_read_bypasses_structured_plan():
    plan = build_plan("job", "List the Python files", executor="python")
    assert len(plan.steps) == 1
    assert plan.steps[0].effect_class == "read"


def test_mutation_gets_dependency_ordered_inspect_execute_verify_dag():
    plan = build_plan(
        "job",
        "Implement the scheduler change and verify it thoroughly",
        executor="python",
    )
    assert [step.title for step in plan.steps] == [
        "Inspect relevant context",
        "Execute the requested work",
        "Verify the result",
    ]
    assert plan.steps[1].dependencies == [plan.steps[0].id]
    assert plan.steps[2].dependencies == [plan.steps[1].id]
    plan.validate()


def test_cycle_and_invalid_executor_are_rejected():
    a = AgentStep(id="a", job_id="j", ordinal=0, title="a", goal="a")
    b = AgentStep(
        id="b", job_id="j", ordinal=1, title="b", goal="b", dependencies=["a"]
    )
    a.dependencies = ["b"]
    with pytest.raises(ValueError, match="cycle"):
        AgentPlan(goal="g", steps=[a, b]).validate()
    a.dependencies = []
    a.executor = "unknown"
    with pytest.raises(ValueError, match="executor"):
        AgentPlan(goal="g", steps=[a]).validate()


def test_steering_creates_bounded_revision_with_original_goal():
    plan = build_plan("job", "Implement a stable change", executor="python")
    step = add_steering_revision(
        plan, "Also preserve the compatibility adapter", executor="python"
    )
    assert plan.revision == 2
    assert step.plan_revision == 2
    assert "Original goal" in step.goal
    while len(plan.steps) < TOTAL_STEP_LIMIT:
        add_steering_revision(plan, "inspect one more edge case", executor="python")
    with pytest.raises(ValueError, match="budget"):
        add_steering_revision(plan, "one too many", executor="python")


def test_verifier_rejection_adds_repair_and_fresh_verification_nodes():
    plan = build_plan(
        "job", "Implement and verify a stable change", executor="python"
    )
    rejected = plan.steps[-1]
    repair, verify = add_repair_revision(
        plan,
        rejected,
        "missing regression evidence",
        executor="python",
    )
    assert repair.dependencies == rejected.dependencies
    assert verify.dependencies == [repair.id]
    assert repair.effect_class == "local_mutation"
    assert verify.effect_class == "read"
    assert plan.revision == 2


def test_tool_registry_strictly_validates_assembled_arguments():
    item = descriptor("read_file")
    assert item and item.capability == "filesystem" and item.idempotent
    assert validate_arguments("read_file", {"path": "README.md"})["path"] == "README.md"
    with pytest.raises(ValueError, match="missing required"):
        validate_arguments("read_file", {})
    with pytest.raises(ValueError, match="unknown arguments"):
        validate_arguments("read_file", {"path": "README.md", "surprise": True})
    result = adapt_result(
        "write_file",
        {
            "ok": True,
            "summary": "Updated file",
            "mutations": ["README.md"],
            "verification": ["read back"],
        },
    )
    assert result.ok and result.mutations == ["README.md"]

"""Hybrid planner: structured plans, revisions and tool-argument validation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.agent.planner import (
    TOTAL_STEP_LIMIT,
    add_repair_revision,
    add_steering_revision,
    build_plan,
    needs_structured_plan,
)
from rau.agent.protocol import AgentPlan, AgentStep
from rau.agent.tool_registry import adapt_result, descriptor, validate_arguments


class HybridPlannerTests(unittest.TestCase):
    def test_trivial_read_bypasses_structured_plan(self) -> None:
        plan = build_plan("job", "List the Python files", executor="python")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].effect_class, "read")

    def test_mutation_gets_dependency_ordered_inspect_execute_verify_dag(self) -> None:
        plan = build_plan(
            "job",
            "Implement the scheduler change and verify it thoroughly",
            executor="python",
        )
        self.assertEqual(
            [step.title for step in plan.steps],
            [
                "Inspect relevant context",
                "Execute the requested work",
                "Verify the result",
            ],
        )
        self.assertEqual(plan.steps[1].dependencies, [plan.steps[0].id])
        self.assertEqual(plan.steps[2].dependencies, [plan.steps[1].id])
        plan.validate()

    def test_cycle_and_invalid_executor_are_rejected(self) -> None:
        a = AgentStep(id="a", job_id="j", ordinal=0, title="a", goal="a")
        b = AgentStep(
            id="b", job_id="j", ordinal=1, title="b", goal="b", dependencies=["a"]
        )
        a.dependencies = ["b"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            AgentPlan(goal="g", steps=[a, b]).validate()
        a.dependencies = []
        a.executor = "unknown"
        with self.assertRaisesRegex(ValueError, "executor"):
            AgentPlan(goal="g", steps=[a]).validate()

    def test_steering_creates_bounded_revision_with_original_goal(self) -> None:
        plan = build_plan("job", "Implement a stable change", executor="python")
        step = add_steering_revision(
            plan, "Also preserve the compatibility adapter", executor="python"
        )
        self.assertEqual(plan.revision, 2)
        self.assertEqual(step.plan_revision, 2)
        self.assertIn("Original goal", step.goal)
        while len(plan.steps) < TOTAL_STEP_LIMIT:
            add_steering_revision(plan, "inspect one more edge case", executor="python")
        with self.assertRaisesRegex(ValueError, "budget"):
            add_steering_revision(plan, "one too many", executor="python")

    def test_verifier_rejection_adds_repair_and_fresh_verification_nodes(self) -> None:
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
        self.assertEqual(repair.dependencies, rejected.dependencies)
        self.assertEqual(verify.dependencies, [repair.id])
        self.assertEqual(repair.effect_class, "local_mutation")
        self.assertEqual(verify.effect_class, "read")
        self.assertEqual(plan.revision, 2)

    def test_tool_registry_strictly_validates_assembled_arguments(self) -> None:
        item = descriptor("read_file")
        self.assertTrue(item and item.capability == "filesystem" and item.idempotent)
        self.assertEqual(
            validate_arguments("read_file", {"path": "README.md"})["path"],
            "README.md",
        )
        with self.assertRaisesRegex(ValueError, "missing required"):
            validate_arguments("read_file", {})
        with self.assertRaisesRegex(ValueError, "unknown arguments"):
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
        self.assertTrue(result.ok and result.mutations == ["README.md"])


if __name__ == "__main__":
    unittest.main()

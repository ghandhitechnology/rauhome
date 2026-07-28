from __future__ import annotations

import uuid
from unittest.mock import patch

from rau import state
from rau.agent import orchestrator
from rau.agent.planner import build_plan
from rau.agent.tool_registry import adapt_result
from rau.providers.base import ChatResult, ToolCall


class _AvailableProvider:
    def __init__(self, name: str, available: bool = True) -> None:
        self.name = name
        self._available = available

    def available(self) -> bool:
        return self._available


class _PrematureThenFinish:
    name = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    def chat(self, messages, **_kwargs):
        self.calls += 1
        self.messages.append(list(messages))
        if self.calls == 1:
            return ChatResult(content="I would inspect the repository first.")
        return ChatResult(
            content="",
            tool_calls=[
                ToolCall(
                    id="finish-1",
                    name="finish",
                    arguments={
                        "outcome": "completed",
                        "summary": "Inspected and verified.",
                        "verification": ["repository evidence checked"],
                    },
                )
            ],
        )


def _job(goal: str = "inspect the repository") -> orchestrator.Job:
    job = orchestrator.Job(
        id=str(uuid.uuid4()),
        goal=goal,
        budget={"max_turns": 6},
    )
    state.create_job(job.id, goal)
    return job


def test_native_harness_resumes_after_premature_answer() -> None:
    provider = _PrematureThenFinish()
    job = _job()
    with (
        patch.object(
            orchestrator,
            "_subagent_routes",
            return_value=[(provider, {"model": "test", "max_tokens": 1024})],
        ),
        patch.object(orchestrator, "load_soul", return_value="soul"),
        patch.object(
            orchestrator, "provider_summarizer", return_value=lambda _text: "summary"
        ),
        patch.object(
            orchestrator,
            "maybe_compact",
            side_effect=lambda messages, *_args, **_kwargs: list(messages),
        ),
        patch.object(orchestrator, "_job_tool_decision", return_value="allow"),
        patch.object(orchestrator, "append_trace"),
    ):
        summary = orchestrator._run_subagent(job, finalize=False)

    assert summary == "Inspected and verified."
    assert provider.calls == 2
    assert job.harness_recoveries == 1
    assert any(
        "not completion" in (message.content or "")
        for message in provider.messages[-1]
        if message.role == "user"
    )


def test_native_harness_keeps_one_session_across_plan_phases() -> None:
    provider = _PrematureThenFinish()
    # Start with the finish response and provide one more finish for phase two.
    provider.calls = 1
    job = _job("complete a multi-phase inspection")
    common = (
        patch.object(
            orchestrator,
            "_subagent_routes",
            return_value=[(provider, {"model": "test", "max_tokens": 1024})],
        ),
        patch.object(orchestrator, "load_soul", return_value="soul"),
        patch.object(
            orchestrator, "provider_summarizer", return_value=lambda _text: "summary"
        ),
        patch.object(
            orchestrator,
            "maybe_compact",
            side_effect=lambda messages, *_args, **_kwargs: list(messages),
        ),
        patch.object(orchestrator, "_job_tool_decision", return_value="allow"),
        patch.object(orchestrator, "append_trace"),
    )
    # The mock returns finish for all calls after its first scripted response.
    with common[0], common[1], common[2], common[3], common[4], common[5]:
        first = orchestrator._run_subagent(
            job, step_goal="Inspect phase", finalize=False
        )
        second = orchestrator._run_subagent(
            job,
            step_goal="Verify phase",
            dependency_results={"inspect": first},
            finalize=False,
        )

    assert second == "Inspected and verified."
    assert sum(message.role == "system" for message in job.harness_messages) == 1
    transcript = "\n".join(message.content or "" for message in job.harness_messages)
    assert "Inspect phase" in transcript
    assert "Verify phase" in transcript


def test_missing_direct_key_routes_same_model_through_openrouter() -> None:
    direct = _AvailableProvider("deepseek", available=False)
    router = _AvailableProvider("openrouter", available=True)
    with (
        patch.object(
            orchestrator,
            "chat_for_slot",
            return_value=(
                direct,
                {"provider": "deepseek", "model": "deepseek-v4-pro"},
            ),
        ),
        patch.object(orchestrator, "get_provider", return_value=router),
        patch.object(orchestrator, "get_slot", return_value={}),
    ):
        routes = orchestrator._subagent_routes()

    assert len(routes) == 1
    assert routes[0][0] is router
    assert routes[0][1]["provider"] == "openrouter"
    assert routes[0][1]["model"] == "deepseek/deepseek-v4-pro"


def test_tool_results_feed_the_completion_ledger() -> None:
    changed = adapt_result("edit_file", {"ok": True, "path": "/repo/app.py"})
    checked = adapt_result("run_shell", {"ok": True, "code": 0})
    assert changed.artifacts == ["/repo/app.py"]
    assert changed.mutations == ["edit_file: /repo/app.py"]
    assert checked.evidence[0]["kind"] == "command"


def test_model_claim_cannot_replace_post_mutation_tool_evidence() -> None:
    plan = build_plan(
        "job-verify",
        "Fix a repository file",
        executor="python",
    )
    mutation_step = next(
        step for step in plan.steps if step.effect_class != "read"
    )
    error = orchestrator._step_verification_error(
        mutation_step,
        "completed",
        {
            "mutations": ["edited app.py"],
            "verification": ["model says tests passed"],
            "tool_backed_verification": False,
        },
    )
    assert "tool-backed post-mutation" in error


def test_pi_planner_uses_one_long_lived_agent_step() -> None:
    plan = build_plan(
        "job-1",
        "Fix the repository bug and verify the tests",
        executor="pi",
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].executor == "pi"
    assert plan.steps[0].title == "Execute and verify autonomously"

"""Offline WorkflowPlanner golden-set gate.

This gate starts after routing: cases provide reviewed Goal sequences and assert
the expected task/step dependency shape. It is deterministic and does not call a
live LLM or database.
"""

from __future__ import annotations

import json
from pathlib import Path

from personal_agent.kernel.config import Settings
from personal_agent.infra.structured_model import StructuredModelResponse
from personal_agent.planning.router import Goal, RouterDecision
from personal_agent.planning.workflow_planner import (
    GoalDependencyDecision,
    WorkflowPlanner,
)

from .dataset import WorkflowPlannerRunOutput, default_cases_path, load_cases
from .scorer import score_all


class FakeDependencyModelClient:
    def __init__(self, cases) -> None:
        self._cases = list(cases)

    def generate(self, request):
        content = "\n".join(message["content"] for message in request.messages)
        matched = next(
            (
                case
                for case in self._cases
                if case.entry_text in content
            ),
            None,
        )
        dependencies = matched.model_task_dependencies if matched else {}
        return StructuredModelResponse(
            value=request.output_type(
                decisions=[
                    GoalDependencyDecision(
                        task_id=task_id,
                        depends_on=depends_on,
                        reason="fixture",
                        confidence=1.0,
                    )
                    for task_id, depends_on in dependencies.items()
                ]
            ),
            model="fake-dependency-model",
            latency_ms=0.0,
        )


def test_workflow_planner_meets_dependency_quality_baseline():
    cases = load_cases(default_cases_path())
    planner = WorkflowPlanner(
        Settings(),
        dependency_model_client=FakeDependencyModelClient(cases),
    )
    runs: dict[str, WorkflowPlannerRunOutput] = {}

    for case in cases:
        decision = RouterDecision(
            goals=[
                Goal(
                    goal_id=goal.goal_id,
                    intent=goal.intent,
                    input=goal.input,
                )
                for goal in case.goals
            ]
        )

        plan, steps = planner.plan(decision, entry_text=case.entry_text)
        runs[case.id] = WorkflowPlannerRunOutput(
            task_dependencies={
                task.task_id: task.depends_on
                for task in plan.tasks
            },
            step_dependencies={
                step.step_id: step.depends_on
                for step in steps
            },
            tool_sequence=[
                str(step.tool_name)
                for step in steps
                if step.action_type == "tool_call" and step.tool_name
            ],
        )

    report = score_all(cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "baseline.json").read_text(encoding="utf-8")
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"

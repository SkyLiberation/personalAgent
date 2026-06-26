"""Dataset model + loader for the WorkflowPlanner golden set.

The router golden set answers "which goals did the user express?". This planner
golden set starts after routing: it receives reviewed Goal sequences and asserts
how WorkflowPlanner should organize them into task-level and step-level
dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PlannerGoalCase:
    goal_id: str
    intent: str
    input: str = ""


@dataclass(frozen=True)
class WorkflowPlannerEvalCase:
    id: str
    description: str
    entry_text: str
    goals: list[PlannerGoalCase] = field(default_factory=list)
    expected_task_dependencies: dict[str, list[str]] = field(default_factory=dict)
    expected_step_dependencies: dict[str, list[str]] = field(default_factory=dict)
    model_task_dependencies: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class WorkflowPlannerRunOutput:
    """Scoreable projection of one WorkflowPlanner run."""

    task_dependencies: dict[str, list[str]] = field(default_factory=dict)
    step_dependencies: dict[str, list[str]] = field(default_factory=dict)


def load_cases(path: str | Path) -> list[WorkflowPlannerEvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[WorkflowPlannerEvalCase] = []
    for item in raw:
        goals = [
            PlannerGoalCase(
                goal_id=str(goal["goal_id"]),
                intent=str(goal["intent"]),
                input=str(goal.get("input", "")),
            )
            for goal in item.get("goals", [])
        ]
        cases.append(
            WorkflowPlannerEvalCase(
                id=str(item["id"]),
                description=str(item.get("description", "")),
                entry_text=str(item.get("entry_text", "")),
                goals=goals,
                expected_task_dependencies={
                    str(k): [str(v) for v in values]
                    for k, values in (item.get("expected_task_dependencies") or {}).items()
                },
                expected_step_dependencies={
                    str(k): [str(v) for v in values]
                    for k, values in (item.get("expected_step_dependencies") or {}).items()
                },
                model_task_dependencies={
                    str(k): [str(v) for v in values]
                    for k, values in (item.get("model_task_dependencies") or {}).items()
                },
            )
        )
    return cases


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"

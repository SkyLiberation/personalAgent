"""Scoring for the WorkflowPlanner golden set."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import WorkflowPlannerEvalCase, WorkflowPlannerRunOutput
from .metrics import (
    dependency_edge_f1,
    dependency_map_exact,
    dependency_node_accuracy,
)


@dataclass(frozen=True)
class WorkflowPlannerCaseScore:
    case_id: str
    task_dependency_exact: float
    task_dependency_node_accuracy: float
    task_dependency_edge_f1: float
    step_dependency_exact: float
    step_dependency_node_accuracy: float
    step_dependency_edge_f1: float
    overall_exact: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_case(
    case: WorkflowPlannerEvalCase,
    run: WorkflowPlannerRunOutput,
) -> WorkflowPlannerCaseScore:
    scored_step_dependencies = {
        key: value
        for key, value in run.step_dependencies.items()
        if key in case.expected_step_dependencies
    }
    task_exact = dependency_map_exact(
        run.task_dependencies,
        case.expected_task_dependencies,
    )
    step_exact = dependency_map_exact(
        scored_step_dependencies,
        case.expected_step_dependencies,
    )
    return WorkflowPlannerCaseScore(
        case_id=case.id,
        task_dependency_exact=task_exact,
        task_dependency_node_accuracy=dependency_node_accuracy(
            run.task_dependencies,
            case.expected_task_dependencies,
        ),
        task_dependency_edge_f1=dependency_edge_f1(
            run.task_dependencies,
            case.expected_task_dependencies,
        ),
        step_dependency_exact=step_exact,
        step_dependency_node_accuracy=dependency_node_accuracy(
            scored_step_dependencies,
            case.expected_step_dependencies,
        ),
        step_dependency_edge_f1=dependency_edge_f1(
            scored_step_dependencies,
            case.expected_step_dependencies,
        ),
        overall_exact=1.0 if task_exact and step_exact else 0.0,
    )


_METRIC_NAMES = (
    "task_dependency_exact",
    "task_dependency_node_accuracy",
    "task_dependency_edge_f1",
    "step_dependency_exact",
    "step_dependency_node_accuracy",
    "step_dependency_edge_f1",
    "overall_exact",
)


@dataclass(frozen=True)
class WorkflowPlannerQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[WorkflowPlannerCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [score.as_dict() for score in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"WorkflowPlanner Quality Report ({self.num_cases} cases)"]
        for name in _METRIC_NAMES:
            lines.append(f"  {name:<34} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate(scores: list[WorkflowPlannerCaseScore]) -> WorkflowPlannerQualityReport:
    if not scores:
        return WorkflowPlannerQualityReport(
            num_cases=0,
            means=dict.fromkeys(_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _METRIC_NAMES
    }
    return WorkflowPlannerQualityReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def score_all(
    cases: list[WorkflowPlannerEvalCase],
    runs: dict[str, WorkflowPlannerRunOutput],
) -> WorkflowPlannerQualityReport:
    scores = [
        score_case(case, runs[case.id])
        for case in cases
        if case.id in runs
    ]
    return aggregate(scores)

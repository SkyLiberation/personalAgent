"""Quality scoring for TaskAnalyzer semantic outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import TaskAnalysisEvalCase, TaskAnalysisRunOutput
from .metrics import (
    clarify_field_precision,
    result_contract_sequence_exact,
    result_contract_set_f1,
    outcome_correct,
)


@dataclass(frozen=True)
class TaskAnalysisCaseScore:
    case_id: str
    outcome_accuracy: float
    result_contract_f1: float
    result_contract_sequence_exact: float
    clarify_field_precision: float

    def as_dict(self):
        return asdict(self)


def score_case(case: TaskAnalysisEvalCase, run: TaskAnalysisRunOutput) -> TaskAnalysisCaseScore:
    return TaskAnalysisCaseScore(
        case_id=case.id,
        outcome_accuracy=outcome_correct(run.outcome, case.expected_outcome),
        result_contract_f1=result_contract_set_f1(run.result_contracts, case.expected_result_contracts),
        result_contract_sequence_exact=result_contract_sequence_exact(
            run.result_contracts,
            case.expected_result_contracts,
        ),
        clarify_field_precision=clarify_field_precision(
            run.missing_information, case.expected_missing_info,
        ),
    )


_METRIC_NAMES = (
    "outcome_accuracy", "result_contract_f1", "result_contract_sequence_exact", "clarify_field_precision",
)


@dataclass(frozen=True)
class TaskAnalysisQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[TaskAnalysisCaseScore] = field(default_factory=list)

    def as_dict(self):
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [item.as_dict() for item in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Task Analysis Quality Report ({self.num_cases} cases)"]
        lines.extend(
            f"  {name:<24} {self.means.get(name, 0.0):.4f}"
            for name in _METRIC_NAMES
        )
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        return [
            f"{name}={self.means.get(name, 0.0):.4f} < threshold {floor:.4f}"
            for name, floor in thresholds.items()
            if self.means.get(name, 0.0) < floor
        ]


def aggregate(scores: list[TaskAnalysisCaseScore]) -> TaskAnalysisQualityReport:
    if not scores:
        return TaskAnalysisQualityReport(0, dict.fromkeys(_METRIC_NAMES, 0.0))
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _METRIC_NAMES
    }
    return TaskAnalysisQualityReport(len(scores), means, scores)


def score_all(cases, runs) -> TaskAnalysisQualityReport:
    return aggregate([score_case(case, runs[case.id]) for case in cases if case.id in runs])

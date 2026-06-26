"""Scoring for tool governance quality cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import (
    ToolEvalCase,
    ToolExecutionEvalCase,
    ToolExecutionRunOutput,
    ToolRunOutput,
)
from .metrics import nullable_scalar_exact, scalar_exact, side_effects_exact


@dataclass(frozen=True)
class ToolCaseScore:
    case_id: str
    exposure_exact: float
    risk_exact: float
    confirmation_exact: float
    side_effect_exact: float
    permission_scope_exact: float
    idempotency_exact: float
    audit_exact: float
    resource_policy_exact: float
    overall_exact: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_case(case: ToolEvalCase, run: ToolRunOutput) -> ToolCaseScore:
    exposure_exact = scalar_exact(run.exposure, case.expected_exposure)
    risk_exact = scalar_exact(run.risk_level, case.expected_risk_level)
    confirmation_exact = scalar_exact(
        run.requires_confirmation,
        case.expected_requires_confirmation,
    )
    side_effect_exact = side_effects_exact(
        run.side_effects,
        case.expected_side_effects or [],
    )
    permission_scope_exact = scalar_exact(
        run.permission_scope,
        case.expected_permission_scope,
    )
    idempotency_exact = scalar_exact(
        run.idempotency_key_required,
        case.expected_idempotency_key_required,
    )
    audit_exact = scalar_exact(run.audit_required, case.expected_audit_required)
    resource_checks = [
        nullable_scalar_exact(run.timeout_seconds, case.expected_timeout_seconds),
        nullable_scalar_exact(run.max_retries, case.expected_max_retries),
        nullable_scalar_exact(
            run.rate_limit_per_minute,
            case.expected_rate_limit_per_minute,
        ),
    ]
    resource_policy_exact = 1.0 if all(resource_checks) else 0.0
    field_scores = [
        exposure_exact,
        risk_exact,
        confirmation_exact,
        side_effect_exact,
        permission_scope_exact,
        idempotency_exact,
        audit_exact,
        resource_policy_exact,
    ]
    return ToolCaseScore(
        case_id=case.id,
        exposure_exact=exposure_exact,
        risk_exact=risk_exact,
        confirmation_exact=confirmation_exact,
        side_effect_exact=side_effect_exact,
        permission_scope_exact=permission_scope_exact,
        idempotency_exact=idempotency_exact,
        audit_exact=audit_exact,
        resource_policy_exact=resource_policy_exact,
        overall_exact=1.0 if all(field_scores) else 0.0,
    )


_METRIC_NAMES = (
    "exposure_exact",
    "risk_exact",
    "confirmation_exact",
    "side_effect_exact",
    "permission_scope_exact",
    "idempotency_exact",
    "audit_exact",
    "resource_policy_exact",
    "overall_exact",
)


@dataclass(frozen=True)
class ToolQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ToolCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [score.as_dict() for score in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Tool Quality Report ({self.num_cases} cases)"]
        for name in _METRIC_NAMES:
            lines.append(f"  {name:<30} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate(scores: list[ToolCaseScore]) -> ToolQualityReport:
    if not scores:
        return ToolQualityReport(
            num_cases=0,
            means=dict.fromkeys(_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _METRIC_NAMES
    }
    return ToolQualityReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def score_all(
    cases: list[ToolEvalCase],
    runs: dict[str, ToolRunOutput],
) -> ToolQualityReport:
    scores = [
        score_case(case, runs[case.tool_name])
        for case in cases
        if case.tool_name in runs
    ]
    return aggregate(scores)


@dataclass(frozen=True)
class ToolExecutionCaseScore:
    case_id: str
    outcome_exact: float
    error_kind_exact: float
    data_shape_match: float
    evidence_count_match: float
    repeat_exact: float
    call_count_exact: float
    overall_exact: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_execution_case(
    case: ToolExecutionEvalCase,
    run: ToolExecutionRunOutput,
) -> ToolExecutionCaseScore:
    outcome_exact = scalar_exact(run.ok, case.expected_ok)
    error_kind_exact = scalar_exact(run.error_kind, case.expected_error_kind)
    data_shape_match = (
        1.0
        if all(key in set(run.data_keys) for key in case.expected_data_keys)
        else 0.0
    )
    evidence_count_match = (
        1.0 if run.evidence_count >= case.expected_evidence_min_count else 0.0
    )
    if case.expected_repeat_ok is None:
        repeat_exact = 1.0
    else:
        repeat_exact = 1.0 if (
            run.repeat_ok == case.expected_repeat_ok
            and run.repeat_error_kind == case.expected_repeat_error_kind
        ) else 0.0
    call_count_exact = (
        1.0
        if all(
            run.call_counts.get(name, 0) == expected
            for name, expected in case.expected_call_counts.items()
        )
        else 0.0
    )
    field_scores = [
        outcome_exact,
        error_kind_exact,
        data_shape_match,
        evidence_count_match,
        repeat_exact,
        call_count_exact,
    ]
    return ToolExecutionCaseScore(
        case_id=case.id,
        outcome_exact=outcome_exact,
        error_kind_exact=error_kind_exact,
        data_shape_match=data_shape_match,
        evidence_count_match=evidence_count_match,
        repeat_exact=repeat_exact,
        call_count_exact=call_count_exact,
        overall_exact=1.0 if all(field_scores) else 0.0,
    )


_EXECUTION_METRIC_NAMES = (
    "outcome_exact",
    "error_kind_exact",
    "data_shape_match",
    "evidence_count_match",
    "repeat_exact",
    "call_count_exact",
    "overall_exact",
)


@dataclass(frozen=True)
class ToolExecutionQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ToolExecutionCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [score.as_dict() for score in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Tool Execution Quality Report ({self.num_cases} cases)"]
        for name in _EXECUTION_METRIC_NAMES:
            lines.append(f"  {name:<30} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate_execution(
    scores: list[ToolExecutionCaseScore],
) -> ToolExecutionQualityReport:
    if not scores:
        return ToolExecutionQualityReport(
            num_cases=0,
            means=dict.fromkeys(_EXECUTION_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _EXECUTION_METRIC_NAMES
    }
    return ToolExecutionQualityReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def score_execution_all(
    cases: list[ToolExecutionEvalCase],
    runs: dict[str, ToolExecutionRunOutput],
) -> ToolExecutionQualityReport:
    scores = [
        score_execution_case(case, runs[case.id])
        for case in cases
        if case.id in runs
    ]
    return aggregate_execution(scores)

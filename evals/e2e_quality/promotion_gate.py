"""Deterministic early rejection over checksum-sealed product evidence cohorts."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from math import ceil, isfinite
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.e2e_quality.trace_archive import TraceArchive
from evals.product_baselines.evidence import (
    EvidencePairError,
    FinalizedProductEvidence,
    canonical_evidence_digest,
    load_finalized_product_evidence,
)

PromotionStatus = Literal["continue", "rejected", "passed"]


class PromotionGateError(ValueError):
    """The gate input or cohort violates its deterministic contract."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricRef(_FrozenModel):
    source: Literal[
        "report",
        "duration_seconds",
        "result_report_missing",
        "test_failed",
    ]
    path: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_path(self) -> "MetricRef":
        if self.source == "report" and not self.path:
            raise ValueError("report metric requires a non-empty path")
        if self.source != "report" and self.path:
            raise ValueError(f"{self.source} metric cannot declare a report path")
        return self

    def key(self) -> str:
        if self.source != "report":
            return self.source
        return "report:" + ".".join(self.path)


class _Constraint(_FrozenModel):
    constraint_id: str = Field(min_length=1)


class MinimumCountConstraint(_Constraint):
    kind: Literal["minimum_count"] = "minimum_count"
    metric: MetricRef
    minimum: int = Field(ge=0)


class MaximumCountConstraint(_Constraint):
    kind: Literal["maximum_count"] = "maximum_count"
    metric: MetricRef
    maximum: int = Field(ge=0)


class MaximumSumConstraint(_Constraint):
    kind: Literal["maximum_sum"] = "maximum_sum"
    metric: MetricRef
    maximum: float = Field(ge=0)


class MaximumNearestRankPercentileConstraint(_Constraint):
    kind: Literal["maximum_nearest_rank_percentile"] = (
        "maximum_nearest_rank_percentile"
    )
    metric: MetricRef
    percentile: int = Field(gt=0, le=100)
    maximum: float = Field(ge=0)


class MinimumConditionalRateConstraint(_Constraint):
    kind: Literal["minimum_conditional_rate"] = "minimum_conditional_rate"
    numerator_metric: MetricRef
    denominator_metric: MetricRef
    minimum_rate: float = Field(ge=0, le=1)
    minimum_denominator: int = Field(ge=1)


PromotionConstraint = Annotated[
    MinimumCountConstraint
    | MaximumCountConstraint
    | MaximumSumConstraint
    | MaximumNearestRankPercentileConstraint
    | MinimumConditionalRateConstraint,
    Field(discriminator="kind"),
]


class PromotionGateSpec(_FrozenModel):
    schema_version: Literal[1] = 1
    gate_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    role: Literal["target"] = "target"
    stage: Literal[
        "runtime_conformance",
        "provider_conformance",
        "focused_product_target",
        "formal_product_target",
        "ablation",
    ]
    expected_samples: int = Field(ge=1)
    constraints: tuple[PromotionConstraint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_constraints(self) -> "PromotionGateSpec":
        identifiers = [item.constraint_id for item in self.constraints]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("promotion constraint IDs must be unique")
        for constraint in self.constraints:
            if (
                isinstance(constraint, MinimumCountConstraint)
                and constraint.minimum > self.expected_samples
            ):
                raise ValueError("minimum count cannot exceed expected samples")
            if (
                isinstance(constraint, MinimumConditionalRateConstraint)
                and constraint.minimum_denominator > self.expected_samples
            ):
                raise ValueError(
                    "minimum conditional denominator cannot exceed expected samples"
                )
        return self


class PromotionSampleFact(_FrozenModel):
    archive_ref: str = Field(min_length=1)
    archive_run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    role: Literal["target"]
    evidence_class: str = Field(min_length=1)
    formal_entrypoint: str = Field(min_length=1)
    interaction_mode: str = Field(min_length=1)
    config_cohort: str = Field(min_length=1)
    grader_version: str = Field(min_length=1)
    subject_digest: str = Field(pattern="^[0-9a-f]{64}$")
    sample_key: str = Field(pattern="^[0-9a-f]{64}$")
    duration_seconds: float = Field(ge=0)
    metrics: dict[str, bool | int | float]

    def cohort_key(self) -> tuple[str, ...]:
        return (
            self.case_id,
            self.role,
            self.evidence_class,
            self.formal_entrypoint,
            self.interaction_mode,
            self.config_cohort,
            self.grader_version,
            self.subject_digest,
        )


class ConstraintEvaluation(_FrozenModel):
    constraint_id: str
    kind: str
    irreversibly_failed: bool
    complete_satisfied: bool
    details: dict[str, bool | int | float | str | None]


class PromotionDecisionReport(_FrozenModel):
    schema_version: Literal[1] = 1
    evidence_class: Literal[
        "evaluation_promotion_decision_not_product_e2e"
    ] = "evaluation_promotion_decision_not_product_e2e"
    spec: PromotionGateSpec
    status: PromotionStatus
    observed_samples: int
    remaining_samples: int
    first_failed_constraint: str | None
    first_failed_at_sample: int | None
    cohort_digest: str | None
    constraint_evaluations: tuple[ConstraintEvaluation, ...]
    samples: tuple[PromotionSampleFact, ...]


def _metric_refs(spec: PromotionGateSpec) -> tuple[MetricRef, ...]:
    refs: list[MetricRef] = []
    for constraint in spec.constraints:
        if isinstance(constraint, MinimumConditionalRateConstraint):
            refs.extend(
                (constraint.numerator_metric, constraint.denominator_metric)
            )
        else:
            refs.append(constraint.metric)
    return tuple({ref.key(): ref for ref in refs}.values())


def _report_value(report: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = report
    for segment in path:
        if not isinstance(value, dict) or segment not in value:
            raise PromotionGateError(
                "promotion metric is missing from product report: " + ".".join(path)
            )
        value = value[segment]
    return value


def _metric_value(ref: MetricRef, evidence: FinalizedProductEvidence) -> bool | int | float:
    value = (
        evidence.duration_seconds
        if ref.source == "duration_seconds"
        else not evidence.result_report_captured
        if ref.source == "result_report_missing"
        else evidence.outcome == "failed"
        if ref.source == "test_failed"
        else _report_value(evidence.report, ref.path)
    )
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and isfinite(value):
        return value
    raise PromotionGateError(
        f"promotion metric {ref.key()!r} must be bool, int, or float"
    )


def sample_fact_from_archive(
    spec: PromotionGateSpec,
    run_dir: Path,
) -> PromotionSampleFact:
    try:
        evidence = load_finalized_product_evidence(run_dir)
    except EvidencePairError as exc:
        raise PromotionGateError(str(exc)) from exc
    identity = evidence.identity
    metrics = {
        ref.key(): _metric_value(ref, evidence)
        for ref in _metric_refs(spec)
    }
    return PromotionSampleFact(
        archive_ref=run_dir.as_posix(),
        archive_run_id=evidence.archive_run_id,
        case_id=identity.case_id,
        role=identity.role,
        evidence_class=identity.evidence_class,
        formal_entrypoint=identity.formal_entrypoint,
        interaction_mode=identity.interaction_mode,
        config_cohort=identity.config_cohort,
        grader_version=identity.grader_version,
        subject_digest=evidence.subject_digest,
        sample_key=canonical_evidence_digest(
            {"archive_run_id": evidence.archive_run_id}
        ),
        duration_seconds=evidence.duration_seconds,
        metrics=metrics,
    )


def _bool_values(samples: tuple[PromotionSampleFact, ...], ref: MetricRef) -> list[bool]:
    values = [sample.metrics[ref.key()] for sample in samples]
    if any(not isinstance(value, bool) for value in values):
        raise PromotionGateError(f"constraint metric {ref.key()!r} must be boolean")
    return values


def _numeric_values(
    samples: tuple[PromotionSampleFact, ...],
    ref: MetricRef,
) -> list[float]:
    values = [sample.metrics[ref.key()] for sample in samples]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise PromotionGateError(f"constraint metric {ref.key()!r} must be numeric")
    return [float(value) for value in values]


def _evaluate_constraint(
    constraint: PromotionConstraint,
    *,
    samples: tuple[PromotionSampleFact, ...],
    expected_samples: int,
) -> ConstraintEvaluation:
    observed = len(samples)
    remaining = expected_samples - observed
    complete = observed == expected_samples
    if isinstance(constraint, MinimumCountConstraint):
        count = sum(_bool_values(samples, constraint.metric))
        failed = count + remaining < constraint.minimum
        satisfied = complete and count >= constraint.minimum
        details = {
            "current_count": count,
            "maximum_achievable_count": count + remaining,
            "required_minimum": constraint.minimum,
        }
    elif isinstance(constraint, MaximumCountConstraint):
        count = sum(_bool_values(samples, constraint.metric))
        failed = count > constraint.maximum
        satisfied = complete and count <= constraint.maximum
        details = {
            "current_count": count,
            "allowed_maximum": constraint.maximum,
        }
    elif isinstance(constraint, MaximumSumConstraint):
        values = _numeric_values(samples, constraint.metric)
        if any(value < 0 for value in values):
            raise PromotionGateError(
                f"maximum-sum metric {constraint.metric.key()!r} must be non-negative"
            )
        total = sum(values)
        failed = total > constraint.maximum
        satisfied = complete and total <= constraint.maximum
        details = {
            "current_sum": round(total, 6),
            "allowed_maximum": constraint.maximum,
        }
    elif isinstance(constraint, MaximumNearestRankPercentileConstraint):
        values = sorted(_numeric_values(samples, constraint.metric))
        final_rank = ceil(constraint.percentile / 100 * expected_samples)
        allowed_exceedances = expected_samples - final_rank
        exceedances = sum(value > constraint.maximum for value in values)
        failed = exceedances > allowed_exceedances
        percentile_value = (
            values[ceil(constraint.percentile / 100 * observed) - 1]
            if values
            else None
        )
        final_value = values[final_rank - 1] if complete else None
        satisfied = complete and final_value is not None and final_value <= constraint.maximum
        details = {
            "observed_percentile": round(percentile_value, 6)
            if percentile_value is not None
            else None,
            "final_nearest_rank": final_rank,
            "exceedance_count": exceedances,
            "allowed_exceedances": allowed_exceedances,
            "allowed_maximum": constraint.maximum,
        }
    else:
        numerators = _bool_values(samples, constraint.numerator_metric)
        denominators = _bool_values(samples, constraint.denominator_metric)
        if any(numerator and not denominator for numerator, denominator in zip(
            numerators,
            denominators,
            strict=True,
        )):
            raise PromotionGateError(
                "conditional-rate numerator must imply its denominator"
            )
        numerator_count = sum(numerators)
        denominator_count = sum(denominators)
        maximum_denominator = denominator_count + remaining
        maximum_rate = (
            (numerator_count + remaining) / maximum_denominator
            if maximum_denominator
            else 0.0
        )
        current_rate = (
            numerator_count / denominator_count if denominator_count else None
        )
        failed = (
            maximum_denominator < constraint.minimum_denominator
            or maximum_rate < constraint.minimum_rate
        )
        satisfied = bool(
            complete
            and denominator_count >= constraint.minimum_denominator
            and current_rate is not None
            and current_rate >= constraint.minimum_rate
        )
        details = {
            "numerator_count": numerator_count,
            "denominator_count": denominator_count,
            "current_rate": round(current_rate, 6)
            if current_rate is not None
            else None,
            "maximum_achievable_rate": round(maximum_rate, 6),
            "required_minimum_rate": constraint.minimum_rate,
            "required_minimum_denominator": constraint.minimum_denominator,
        }
    return ConstraintEvaluation(
        constraint_id=constraint.constraint_id,
        kind=constraint.kind,
        irreversibly_failed=failed,
        complete_satisfied=satisfied,
        details=details,
    )


class PromotionGateController:
    """Own one in-process cohort decision; never mutates product evidence."""

    def __init__(self, spec: PromotionGateSpec) -> None:
        self.spec = spec
        self._samples: list[PromotionSampleFact] = []
        self._cohort_key: tuple[str, ...] | None = None
        self._first_failed_constraint: str | None = None
        self._first_failed_at_sample: int | None = None

    @property
    def samples(self) -> tuple[PromotionSampleFact, ...]:
        return tuple(self._samples)

    def observe_archive(self, run_dir: Path) -> PromotionDecisionReport:
        return self.observe(sample_fact_from_archive(self.spec, run_dir))

    def observe(self, sample: PromotionSampleFact) -> PromotionDecisionReport:
        current = self.decision()
        if current.status != "continue":
            raise PromotionGateError(
                f"promotion gate is already terminal: {current.status}"
            )
        if sample.case_id != self.spec.case_id or sample.role != self.spec.role:
            raise PromotionGateError(
                "sample case/role does not match promotion gate specification"
            )
        if len(self._samples) >= self.spec.expected_samples:
            raise PromotionGateError("promotion gate received too many samples")
        cohort_key = sample.cohort_key()
        if self._cohort_key is None:
            self._cohort_key = cohort_key
        elif cohort_key != self._cohort_key:
            raise PromotionGateError(
                "promotion samples differ in code, config, grader, or entrypoint cohort"
            )
        if any(existing.sample_key == sample.sample_key for existing in self._samples):
            raise PromotionGateError("promotion cohort contains a duplicate sample identity")
        expected_metric_keys = {ref.key() for ref in _metric_refs(self.spec)}
        if set(sample.metrics) != expected_metric_keys:
            raise PromotionGateError(
                "promotion sample metrics do not match the gate specification"
            )
        self._samples.append(sample)
        decision = self.decision()
        if decision.status == "rejected" and self._first_failed_constraint is None:
            failed = next(
                item
                for item in decision.constraint_evaluations
                if item.irreversibly_failed
            )
            self._first_failed_constraint = failed.constraint_id
            self._first_failed_at_sample = len(self._samples)
            decision = self.decision()
        return decision

    def decision(self) -> PromotionDecisionReport:
        samples = tuple(self._samples)
        evaluations = tuple(
            _evaluate_constraint(
                constraint,
                samples=samples,
                expected_samples=self.spec.expected_samples,
            )
            for constraint in self.spec.constraints
        )
        if any(item.irreversibly_failed for item in evaluations):
            status: PromotionStatus = "rejected"
        elif len(samples) == self.spec.expected_samples and all(
            item.complete_satisfied for item in evaluations
        ):
            status = "passed"
        else:
            status = "continue"
        return PromotionDecisionReport(
            spec=self.spec,
            status=status,
            observed_samples=len(samples),
            remaining_samples=self.spec.expected_samples - len(samples),
            first_failed_constraint=self._first_failed_constraint,
            first_failed_at_sample=self._first_failed_at_sample,
            cohort_digest=canonical_evidence_digest(self._cohort_key)
            if self._cohort_key is not None
            else None,
            constraint_evaluations=evaluations,
            samples=samples,
        )


def replay_product_evidence_archives(
    spec: PromotionGateSpec,
    run_dirs: Iterable[Path],
) -> PromotionGateController:
    controller = PromotionGateController(spec)
    finalized = sorted(
        (load_finalized_product_evidence(path) for path in run_dirs),
        key=lambda evidence: evidence.archive_run_id,
    )
    for evidence in finalized:
        decision = controller.observe_archive(evidence.archive_dir)
        if decision.status != "continue":
            break
    return controller


def write_promotion_report(
    controller: PromotionGateController,
    output_root: Path,
) -> Path:
    decision = controller.decision()
    archive = TraceArchive(output_root / controller.spec.gate_id.lower())
    nodeid = f"promotion_gate::{controller.spec.gate_id}"
    archive.write_trace(
        nodeid=nodeid,
        case_id=controller.spec.gate_id,
        trace=decision.model_dump(mode="json"),
    )
    outcome = (
        "passed"
        if decision.status == "passed"
        else "failed"
        if decision.status == "rejected"
        else "skipped"
    )
    archive.record_test_result(
        nodeid=nodeid,
        phase="call",
        outcome=outcome,
        duration_seconds=sum(sample.duration_seconds for sample in controller.samples),
        detail=(
            f"irreversible promotion failure: {decision.first_failed_constraint}"
            if decision.status == "rejected"
            else None
        ),
    )
    archive.finalize(exit_status=0 if decision.status == "passed" else 1)
    return archive.run_dir


def load_promotion_spec(path: Path) -> PromotionGateSpec:
    try:
        return PromotionGateSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PromotionGateError(f"invalid promotion gate specification: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="replay sealed product evidence through a deterministic promotion gate"
    )
    parser.add_argument("spec", type=Path)
    parser.add_argument("archive_root", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/e2e_traces/promotion_gates"),
    )
    args = parser.parse_args()
    spec = load_promotion_spec(args.spec)
    run_dirs = tuple(
        path
        for path in args.archive_root.iterdir()
        if path.is_dir() and (path / "checksums.sha256").is_file()
    )
    controller = replay_product_evidence_archives(spec, run_dirs)
    output = write_promotion_report(controller, args.output_root)
    decision = controller.decision()
    print(decision.model_dump_json(indent=2))
    print(f"PROMOTION_REPORT_ARCHIVE={output.resolve()}")
    return 0 if decision.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ConstraintEvaluation",
    "MetricRef",
    "MinimumConditionalRateConstraint",
    "MinimumCountConstraint",
    "MaximumCountConstraint",
    "MaximumNearestRankPercentileConstraint",
    "MaximumSumConstraint",
    "PromotionDecisionReport",
    "PromotionGateController",
    "PromotionGateError",
    "PromotionGateSpec",
    "PromotionSampleFact",
    "load_promotion_spec",
    "replay_product_evidence_archives",
    "sample_fact_from_archive",
    "write_promotion_report",
]

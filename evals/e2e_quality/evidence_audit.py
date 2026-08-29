"""Fail-closed audit of the canonical E2E evidence catalog and archives."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES, EvidenceCase
from evals.e2e_quality.metrics_report import MeasurementArchiveError, available_cohorts
from evals.e2e_quality.validation_catalog import VALIDATION_SUITES, ValidationSuite


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    evidence_ids: tuple[str, ...]
    detail: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class EvidenceOverlap:
    left_evidence_id: str
    right_evidence_id: str
    shared_invariants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationSuiteOverlap:
    evidence_id: str
    suite_ids: tuple[str, ...]


def build_overlap_graph(cases: Iterable[EvidenceCase]) -> tuple[EvidenceOverlap, ...]:
    """Expose shared assertions while preserving each case's unique invariants."""

    materialized = tuple(cases)
    edges: list[EvidenceOverlap] = []
    for index, left in enumerate(materialized):
        for right in materialized[index + 1:]:
            shared = tuple(sorted(left.covered_invariants & right.covered_invariants))
            if shared:
                edges.append(EvidenceOverlap(
                    left_evidence_id=left.evidence_id,
                    right_evidence_id=right.evidence_id,
                    shared_invariants=shared,
                ))
    return tuple(edges)


def build_validation_suite_overlaps(
    suites: Iterable[ValidationSuite],
) -> tuple[ValidationSuiteOverlap, ...]:
    memberships: dict[str, list[str]] = {}
    for suite in suites:
        for case in suite.cases:
            memberships.setdefault(case.evidence_id, []).append(suite.suite_id.value)
    return tuple(
        ValidationSuiteOverlap(
            evidence_id=evidence_id,
            suite_ids=tuple(sorted(suite_ids)),
        )
        for evidence_id, suite_ids in sorted(memberships.items())
        if len(suite_ids) > 1
    )


def audit_catalog(cases: Iterable[EvidenceCase]) -> tuple[AuditFinding, ...]:
    """Audit metadata without inferring evidence semantics from names or paths."""

    findings: list[AuditFinding] = []
    product_outcomes: dict[str, list[str]] = {}
    for case in cases:
        evidence_class = getattr(case, "evidence_class", None)
        outcome = getattr(case, "user_outcome_contract", None)
        if case.release_eligible and outcome is None:
            findings.append(AuditFinding(
                code="release_claim_missing_user_outcome_contract",
                evidence_ids=(case.evidence_id,),
                detail="release evidence has no typed persona/source/baseline/result contract",
            ))
        if evidence_class is None:
            findings.append(AuditFinding(
                code="missing_evidence_class",
                evidence_ids=(case.evidence_id,),
                detail="catalog entry does not declare its evidence responsibility",
            ))
        if outcome is not None:
            product_outcomes.setdefault(outcome.outcome_id, []).append(case.evidence_id)
    for outcome_id, evidence_ids in sorted(product_outcomes.items()):
        if len(evidence_ids) > 1:
            findings.append(AuditFinding(
                code="duplicate_product_outcome",
                evidence_ids=tuple(sorted(evidence_ids)),
                detail=f"multiple release claims own canonical outcome {outcome_id!r}",
            ))
    return tuple(findings)


def audit_measurement_cohorts(trace_root: Path) -> tuple[AuditFinding, ...]:
    try:
        cohorts = available_cohorts(trace_root)
    except MeasurementArchiveError as exc:
        return (AuditFinding("invalid_measurement_archive", (), str(exc)),)
    collisions = [
        profile_id
        for profile_id, cohort_ids in cohorts.items()
        if len(cohort_ids) > 1
    ]
    return tuple(
        AuditFinding(
            code="measurement_profile_collision",
            evidence_ids=(),
            detail=f"profile id {profile_id!r} maps to multiple cohort digests",
            severity="warning",
        )
        for profile_id in sorted(collisions)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="audit E2E evidence qualification")
    parser.add_argument("--trace-root", type=Path, default=Path("data/e2e_traces"))
    args = parser.parse_args()
    findings = (*audit_catalog(EVIDENCE_CASES), *audit_measurement_cohorts(args.trace_root))
    for finding in findings:
        ids = ",".join(finding.evidence_ids) or "-"
        print(f"{finding.severity}\t{finding.code}\t{ids}\t{finding.detail}")
    for overlap in build_overlap_graph(EVIDENCE_CASES):
        print(
            "overlap\t"
            f"{overlap.left_evidence_id},{overlap.right_evidence_id}\t"
            + ",".join(overlap.shared_invariants)
        )
    for overlap in build_validation_suite_overlaps(VALIDATION_SUITES):
        print(
            "suite_overlap\t"
            f"{overlap.evidence_id}\t"
            + ",".join(overlap.suite_ids)
        )
    return 1 if any(item.severity == "error" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "EvidenceOverlap",
    "ValidationSuiteOverlap",
    "audit_catalog",
    "audit_measurement_cohorts",
    "build_overlap_graph",
    "build_validation_suite_overlaps",
]

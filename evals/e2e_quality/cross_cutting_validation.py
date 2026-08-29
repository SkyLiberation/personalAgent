"""Evaluate cross-cutting mechanism checkpoints from sealed E2E traces."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES
from evals.e2e_quality.trace_archive import archive_checksums_valid
from evals.e2e_quality.validation_catalog import (
    VALIDATION_SUITE_BY_ID,
    ValidationCaseContract,
    ValidationCheck,
    ValidationCheckKind,
    ValidationSuite,
    ValidationSuiteId,
)


class ValidationArchiveError(ValueError):
    """The supplied archive set cannot support a trustworthy evaluation."""


@dataclass(frozen=True, slots=True)
class CheckEvaluation:
    check_id: str
    passed: bool
    observed_count: int
    detail: str


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    evidence_id: str
    nodeid: str
    pytest_outcome: str
    capability_passed: bool
    trace_file: str
    checks: tuple[CheckEvaluation, ...]


@dataclass(frozen=True, slots=True)
class SuiteEvaluation:
    suite_id: str
    purpose: str
    capability_passed: bool
    passed_cases: int
    total_cases: int
    cases: tuple[CaseEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_nodeid(evidence_id: str) -> str:
    evidence = next(
        (case for case in EVIDENCE_CASES if case.evidence_id == evidence_id),
        None,
    )
    if evidence is None:
        raise ValidationArchiveError(f"unknown evidence id {evidence_id!r}")
    return f"evals/e2e_quality/{evidence.module}::{evidence.test_name}"


def suite_nodeids(suite: ValidationSuite) -> tuple[str, ...]:
    return tuple(_canonical_nodeid(case.evidence_id) for case in suite.cases)


def _walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _matching_count(
    items: Iterable[dict[str, Any]],
    check: ValidationCheck,
) -> int:
    kinds = (
        {"tool_result"}
        if check.kind is ValidationCheckKind.TOOL_RESULT_COUNT
        else (
            {"agent_artifact"}
            if check.kind is ValidationCheckKind.AGENT_ARTIFACT_COUNT
            else {"agent_artifact", "agent_status"}
        )
    )
    return sum(
        item.get("kind") in kinds
        and str(item.get("capability_id", "")) in check.capability_ids
        and (
            not check.accepted_statuses
            or str(item.get("status", "")) in check.accepted_statuses
        )
        for item in items
    )


def _evaluate_check(
    items: tuple[dict[str, Any], ...],
    check: ValidationCheck,
) -> CheckEvaluation:
    if check.kind in {
        ValidationCheckKind.TOOL_RESULT_COUNT,
        ValidationCheckKind.AGENT_ARTIFACT_COUNT,
        ValidationCheckKind.AGENT_OBSERVATION_COUNT,
    }:
        observed = _matching_count(items, check)
        maximum_ok = (
            check.maximum_count is None or observed <= check.maximum_count
        )
        bounds = f"required>={check.minimum_count}"
        if check.maximum_count is not None:
            bounds += f" and <={check.maximum_count}"
        return CheckEvaluation(
            check_id=check.check_id,
            passed=observed >= check.minimum_count and maximum_ok,
            observed_count=observed,
            detail=f"{bounds}; observed={observed}",
        )
    observed_reasons = sorted({
        str(item.get("reason_code"))
        for item in items
        if item.get("kind") == "decision_feedback"
        and str(item.get("reason_code")) in check.reason_codes
    })
    return CheckEvaluation(
        check_id=check.check_id,
        passed=not observed_reasons,
        observed_count=len(observed_reasons),
        detail=(
            "no forbidden feedback reasons observed"
            if not observed_reasons
            else "forbidden feedback: " + ", ".join(observed_reasons)
        ),
    )


def _trace_envelopes(run_dirs: Iterable[Path]) -> dict[str, tuple[Path, dict[str, Any]]]:
    by_nodeid: dict[str, tuple[Path, dict[str, Any]]] = {}
    expected_subject: str | None = None
    for run_dir in run_dirs:
        if not archive_checksums_valid(run_dir):
            raise ValidationArchiveError(f"invalid sealed archive: {run_dir}")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        subject = json.dumps(
            {
                "repository": manifest.get("repository"),
                "measurement_profile": manifest.get("measurement_profile"),
                "environment": manifest.get("environment"),
            },
            sort_keys=True,
        )
        if expected_subject is None:
            expected_subject = subject
        elif subject != expected_subject:
            raise ValidationArchiveError(
                "archives have different repository or evaluation identities"
            )
        for path in sorted(run_dir.glob("*.trace.json")):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            nodeid = str(envelope.get("nodeid", ""))
            if not nodeid:
                raise ValidationArchiveError(f"trace has no nodeid: {path}")
            if nodeid in by_nodeid:
                raise ValidationArchiveError(
                    f"duplicate trace for {nodeid!r}; select one atomic sample"
                )
            by_nodeid[nodeid] = (path, envelope)
    return by_nodeid


def _evaluate_case(
    contract: ValidationCaseContract,
    traces: dict[str, tuple[Path, dict[str, Any]]],
) -> CaseEvaluation:
    nodeid = _canonical_nodeid(contract.evidence_id)
    selected = traces.get(nodeid)
    if selected is None:
        checks = tuple(
            CheckEvaluation(
                check_id=check.check_id,
                passed=False,
                observed_count=0,
                detail="required trace is missing",
            )
            for check in contract.checks
        )
        return CaseEvaluation(
            evidence_id=contract.evidence_id,
            nodeid=nodeid,
            pytest_outcome="missing",
            capability_passed=False,
            trace_file="",
            checks=checks,
        )
    path, envelope = selected
    items = tuple(_walk_json(envelope.get("trace")))
    checks = tuple(_evaluate_check(items, check) for check in contract.checks)
    return CaseEvaluation(
        evidence_id=contract.evidence_id,
        nodeid=nodeid,
        pytest_outcome=str(envelope.get("test_outcome", "pending")),
        capability_passed=all(check.passed for check in checks),
        trace_file=str(path),
        checks=checks,
    )


def evaluate_suite(
    suite_id: ValidationSuiteId,
    run_dirs: Iterable[Path],
) -> SuiteEvaluation:
    suite = VALIDATION_SUITE_BY_ID[suite_id]
    traces = _trace_envelopes(run_dirs)
    cases = tuple(_evaluate_case(case, traces) for case in suite.cases)
    passed_cases = sum(case.capability_passed for case in cases)
    return SuiteEvaluation(
        suite_id=suite.suite_id.value,
        purpose=suite.purpose,
        capability_passed=passed_cases == len(cases),
        passed_cases=passed_cases,
        total_cases=len(cases),
        cases=cases,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="evaluate cross-cutting checkpoints from sealed E2E traces"
    )
    parser.add_argument(
        "--suite",
        required=True,
        choices=tuple(suite.value for suite in ValidationSuiteId),
    )
    parser.add_argument("--archive", action="append", type=Path, default=[])
    parser.add_argument("--list-nodeids", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    suite_id = ValidationSuiteId(args.suite)
    suite = VALIDATION_SUITE_BY_ID[suite_id]
    if args.list_nodeids:
        print("\n".join(suite_nodeids(suite)))
        return 0
    if not args.archive:
        parser.error("at least one --archive is required unless --list-nodeids is used")
    try:
        report = evaluate_suite(suite_id, args.archive)
    except ValidationArchiveError as exc:
        parser.error(str(exc))
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.capability_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CaseEvaluation",
    "CheckEvaluation",
    "SuiteEvaluation",
    "ValidationArchiveError",
    "evaluate_suite",
    "suite_nodeids",
]

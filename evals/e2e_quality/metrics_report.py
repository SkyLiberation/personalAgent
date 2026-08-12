"""Deterministic metrics projection over checksum-sealed E2E archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES, EvidenceCase
from evals.e2e_quality.measurements import CaseMeasurement, MeasurementProfile
from evals.e2e_quality.trace_archive import archive_checksums_valid


class MeasurementArchiveError(ValueError):
    pass


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RateMetric(_ReportModel):
    numerator: int
    denominator: int
    rate: float | None


class IntegerMetric(_ReportModel):
    value: int | None
    available_cases: int
    expected_cases: int


class DurationMetric(_ReportModel):
    raw_seconds: tuple[float, ...]
    min_seconds: float | None
    median_seconds: float | None
    p95_seconds: float | None
    available_cases: int
    expected_cases: int


class MetricsReport(_ReportModel):
    measurement_profile: MeasurementProfile
    archive_run_ids: tuple[str, ...]
    repetitions: tuple[int, ...]
    case_ids: tuple[str, ...]
    goal_completion_rate: RateMetric
    input_tokens: IntegerMetric
    output_tokens: IntegerMetric
    total_tokens: IntegerMetric
    model_calls: IntegerMetric
    model_turns: IntegerMetric
    tool_calls: IntegerMetric
    agent_calls: IntegerMetric
    case_latency_seconds: DurationMetric
    recovery_success_rate: RateMetric
    recovery_duration_seconds: DurationMetric
    replay_new_side_effects: IntegerMetric


class _ExecutedCase(_ReportModel):
    case_id: str
    outcome: Literal["passed", "failed"]
    call_duration_seconds: float | None
    measurement: CaseMeasurement | None


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeasurementArchiveError(f"invalid archive JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MeasurementArchiveError(f"archive JSON is not an object: {path}")
    return value


def _measurement_for_result(
    run_dir: Path,
    trace_files: object,
) -> CaseMeasurement | None:
    if not isinstance(trace_files, list):
        return None
    measurements: list[CaseMeasurement] = []
    for filename in trace_files:
        if not isinstance(filename, str):
            raise MeasurementArchiveError("trace filename is not a string")
        path = run_dir / filename
        if path.parent != run_dir:
            raise MeasurementArchiveError("trace path escapes its archive")
        envelope = _read_object(path)
        raw = envelope.get("measurement")
        if raw is not None:
            measurements.append(CaseMeasurement.model_validate(raw))
    if len(measurements) > 1:
        raise MeasurementArchiveError(
            "one E2E case has multiple authoritative CaseMeasurement facts"
        )
    return measurements[0] if measurements else None


def _call_duration(result: dict[str, object]) -> float | None:
    phases = result.get("phases")
    if not isinstance(phases, dict):
        return None
    call = phases.get("call")
    if not isinstance(call, dict):
        return None
    value = call.get("duration_seconds")
    return float(value) if isinstance(value, (int, float)) else None


def _load_cohort(
    *,
    trace_root: Path,
    profile_id: str,
    evidence_cases: tuple[EvidenceCase, ...],
) -> tuple[
    MeasurementProfile,
    tuple[str, ...],
    tuple[_ExecutedCase, ...],
    tuple[int, ...],
]:
    by_nodeid = {
        f"evals/e2e_quality/{case.module}::{case.test_name}": case
        for case in evidence_cases
        if case.release_eligible
    }
    selected_profiles: list[MeasurementProfile] = []
    selected_run_ids: list[str] = []
    executed: list[_ExecutedCase] = []
    if not trace_root.exists():
        raise MeasurementArchiveError(f"trace root does not exist: {trace_root}")
    for run_dir in sorted(path for path in trace_root.iterdir() if path.is_dir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = _read_object(manifest_path)
        raw_profile = manifest.get("measurement_profile")
        if not isinstance(raw_profile, dict) or raw_profile.get("profile_id") != profile_id:
            continue
        if not archive_checksums_valid(run_dir):
            raise MeasurementArchiveError(
                f"checksum validation failed for measurement archive: {run_dir.name}"
            )
        profile = MeasurementProfile.model_validate(raw_profile)
        summary = _read_object(run_dir / "summary.json")
        selected_profiles.append(profile)
        selected_run_ids.append(str(manifest.get("archive_run_id") or run_dir.name))
        tests = summary.get("tests")
        if not isinstance(tests, list):
            raise MeasurementArchiveError(f"summary tests are invalid: {run_dir.name}")
        for result in tests:
            if not isinstance(result, dict):
                continue
            nodeid = result.get("nodeid")
            case = by_nodeid.get(nodeid) if isinstance(nodeid, str) else None
            outcome = result.get("outcome")
            if case is None or outcome not in {"passed", "failed"}:
                continue
            executed.append(_ExecutedCase(
                case_id=case.case_id,
                outcome=outcome,
                call_duration_seconds=_call_duration(result),
                measurement=_measurement_for_result(run_dir, result.get("trace_files")),
            ))
    if not selected_profiles:
        raise MeasurementArchiveError(
            f"no checksum-sealed archives found for profile {profile_id!r}"
        )
    cohort_key = selected_profiles[0].cohort_key()
    if any(profile.cohort_key() != cohort_key for profile in selected_profiles[1:]):
        raise MeasurementArchiveError(
            "profile id maps to incompatible model, prompt, budget, fixture, or runtime facts"
        )
    return (
        selected_profiles[0],
        tuple(selected_run_ids),
        tuple(executed),
        tuple(sorted({profile.repetition for profile in selected_profiles})),
    )


def _rate(numerator: int, denominator: int) -> RateMetric:
    return RateMetric(
        numerator=numerator,
        denominator=denominator,
        rate=(round(numerator / denominator, 6) if denominator else None),
    )


def _integer_metric(cases: tuple[_ExecutedCase, ...], field: str) -> IntegerMetric:
    values = [
        value
        for case in cases
        if case.measurement is not None
        and (value := getattr(case.measurement, field)) is not None
    ]
    return IntegerMetric(
        value=sum(values) if values else None,
        available_cases=len(values),
        expected_cases=len(cases),
    )


def _duration_metric(
    values: Iterable[float | None],
    *,
    expected_cases: int,
) -> DurationMetric:
    available = tuple(sorted(round(value, 6) for value in values if value is not None))
    return DurationMetric(
        raw_seconds=available,
        min_seconds=available[0] if available else None,
        median_seconds=round(float(median(available)), 6) if available else None,
        # A percentile over a handful of repetitions is false precision.
        p95_seconds=available[max(0, (95 * len(available) + 99) // 100 - 1)]
        if len(available) >= 20
        else None,
        available_cases=len(available),
        expected_cases=expected_cases,
    )


def build_metrics_report(
    *,
    trace_root: Path,
    profile_id: str,
    evidence_cases: Iterable[EvidenceCase] = EVIDENCE_CASES,
) -> MetricsReport:
    profile, run_ids, cases, repetitions = _load_cohort(
        trace_root=trace_root,
        profile_id=profile_id,
        evidence_cases=tuple(evidence_cases),
    )
    passed = sum(case.outcome == "passed" for case in cases)
    recovery_cases = tuple(
        case
        for case in cases
        if case.measurement is not None
        and (
            case.measurement.recovery_duration_seconds is not None
            or case.measurement.replay_new_side_effects is not None
        )
    )
    return MetricsReport(
        measurement_profile=profile,
        archive_run_ids=run_ids,
        repetitions=repetitions,
        case_ids=tuple(sorted({case.case_id for case in cases})),
        goal_completion_rate=_rate(passed, len(cases)),
        input_tokens=_integer_metric(cases, "input_tokens"),
        output_tokens=_integer_metric(cases, "output_tokens"),
        total_tokens=_integer_metric(cases, "total_tokens"),
        model_calls=_integer_metric(cases, "model_calls"),
        model_turns=_integer_metric(cases, "model_turns"),
        tool_calls=_integer_metric(cases, "tool_calls"),
        agent_calls=_integer_metric(cases, "agent_calls"),
        case_latency_seconds=_duration_metric(
            (case.call_duration_seconds for case in cases),
            expected_cases=len(cases),
        ),
        recovery_success_rate=_rate(
            sum(case.outcome == "passed" for case in recovery_cases),
            len(recovery_cases),
        ),
        recovery_duration_seconds=_duration_metric(
            (
                case.measurement.recovery_duration_seconds
                for case in recovery_cases
                if case.measurement is not None
            ),
            expected_cases=len(recovery_cases),
        ),
        replay_new_side_effects=_integer_metric(
            recovery_cases,
            "replay_new_side_effects",
        ),
    )


def write_metrics_report(report: MetricsReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="derive deterministic measurements from sealed E2E archives"
    )
    parser.add_argument("--trace-root", type=Path, default=Path("data/e2e_traces"))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--require-complete-profile", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_metrics_report(
            trace_root=args.trace_root,
            profile_id=args.profile,
        )
    except MeasurementArchiveError as exc:
        parser.error(str(exc))
    rendered = report.model_dump_json(indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        write_metrics_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MeasurementArchiveError",
    "MetricsReport",
    "build_metrics_report",
    "write_metrics_report",
]

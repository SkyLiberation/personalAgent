from __future__ import annotations

import json

import pytest

from evals.e2e_quality.evidence_catalog import (
    BaselineKind,
    EntryBoundary,
    EvidenceCase,
    EvidenceClass,
    UserOutcomeContract,
)
from evals.e2e_quality.measurements import (
    BudgetProfile,
    CaseMeasurement,
    MeasurementProfile,
)
from evals.e2e_quality.metrics_report import (
    MeasurementArchiveError,
    build_metrics_report,
    write_metrics_report,
)
from evals.e2e_quality.trace_archive import TraceArchive


def _profile() -> MeasurementProfile:
    return MeasurementProfile(
        profile_id="current-runtime",
        runtime_implementation="personal-agent-conversation-loop",
        structured_provider="openai-compatible",
        structured_model="test-model",
        prompt_revision="interaction-loop-v1",
        capability_catalog_revision="evidence-catalog-v1",
        budget=BudgetProfile(
            max_model_turns=8,
            max_tool_calls=12,
            max_agent_calls=4,
            max_total_tokens=32_000,
            max_concurrency=4,
        ),
        fixture_revision="fixture-v1",
        repetition=1,
    )


def _case(test_name: str, *, release_eligible: bool = True) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{test_name}.evidence",
        case_id=test_name,
        module="test_measurement_product.py",
        test_name=test_name,
        layers=frozenset(),
        entry_boundary=(
            EntryBoundary.HTTP_PROCESS
            if release_eligible
            else EntryBoundary.IN_PROCESS_SERVICE
        ),
        evidence_class=EvidenceClass.PRODUCT_E2E,
        raw_user_input=release_eligible,
        real_model_required=release_eligible,
        real_postgres_required=release_eligible,
        user_outcome_contract=(
            UserOutcomeContract(
                outcome_id=test_name,
                persona="tester",
                source_ref="test-contract",
                natural_goal="exercise the measured product outcome",
                observable_result="the user-visible result is asserted",
                counterfactuals=("no hidden side effect",),
                baseline_kind=BaselineKind.REGRESSION_CONTRACT,
                baseline_ref="test-baseline",
                assertion_owner="this test",
            )
            if release_eligible
            else None
        ),
    )


def _record(
    archive: TraceArchive,
    case: EvidenceCase,
    *,
    outcome: str,
    duration: float,
    measurement: CaseMeasurement | None,
) -> None:
    nodeid = f"evals/e2e_quality/{case.module}::{case.test_name}"
    archive.write_trace(
        nodeid=nodeid,
        case_id=case.evidence_id,
        trace={"result": "user-visible"},
        measurement=measurement,
    )
    archive.record_test_result(
        nodeid=nodeid,
        phase="call",
        outcome=outcome,
        duration_seconds=duration,
    )


def test_report_aggregates_only_executed_release_cases_and_preserves_missing_usage(
    temp_dir,
) -> None:
    passed = _case("test_passed")
    failed = _case("test_failed")
    diagnostic = _case("test_diagnostic", release_eligible=False)
    archive = TraceArchive(
        temp_dir,
        run_id="measurement-run",
        measurement_profile=_profile(),
    )
    _record(
        archive,
        passed,
        outcome="passed",
        duration=1.25,
        measurement=CaseMeasurement(
            total_tokens=120,
            model_turns=2,
            tool_calls=1,
            agent_calls=0,
        ),
    )
    _record(
        archive,
        failed,
        outcome="failed",
        duration=2.75,
        measurement=None,
    )
    _record(
        archive,
        diagnostic,
        outcome="passed",
        duration=50,
        measurement=CaseMeasurement(total_tokens=9_999),
    )
    archive.finalize(exit_status=1)

    report = build_metrics_report(
        trace_root=temp_dir,
        profile_id="current-runtime",
        evidence_cases=(passed, failed, diagnostic),
    )

    assert report.goal_completion_rate.numerator == 1
    assert report.goal_completion_rate.denominator == 2
    assert report.goal_completion_rate.rate == 0.5
    assert report.case_latency_seconds.raw_seconds == (1.25, 2.75)
    assert report.total_tokens.value == 120
    assert report.total_tokens.available_cases == 1
    assert report.total_tokens.expected_cases == 2
    assert report.input_tokens.value is None
    assert report.input_tokens.available_cases == 0
    assert report.case_ids == ("test_failed", "test_passed")


def test_report_is_byte_stable_and_rejects_tampered_measurement(temp_dir) -> None:
    case = _case("test_stable")
    archive = TraceArchive(
        temp_dir,
        run_id="stable-run",
        measurement_profile=_profile(),
    )
    _record(
        archive,
        case,
        outcome="passed",
        duration=0.5,
        measurement=CaseMeasurement(
            input_tokens=30,
            output_tokens=10,
            total_tokens=40,
            model_calls=1,
            model_turns=1,
            tool_calls=0,
            agent_calls=0,
        ),
    )
    archive.finalize(exit_status=0)
    first = temp_dir / "first.json"
    second = temp_dir / "second.json"
    report = build_metrics_report(
        trace_root=temp_dir,
        profile_id="current-runtime",
        evidence_cases=(case,),
    )
    write_metrics_report(report, first)
    write_metrics_report(report, second)
    assert first.read_bytes() == second.read_bytes()

    trace_path = next(archive.run_dir.glob("*.trace.json"))
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    payload["measurement"]["total_tokens"] = 999
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MeasurementArchiveError, match="checksum"):
        build_metrics_report(
            trace_root=temp_dir,
            profile_id="current-runtime",
            evidence_cases=(case,),
        )


def test_case_measurement_rejects_inconsistent_provider_token_facts() -> None:
    with pytest.raises(ValueError, match=r"input_tokens \+ output_tokens"):
        CaseMeasurement(input_tokens=3, output_tokens=4, total_tokens=8)


def test_measurement_cohort_digest_ignores_label_and_repetition_only() -> None:
    first = _profile()
    second = first.model_copy(update={"profile_id": "renamed", "repetition": 9})
    changed_model = first.model_copy(update={"structured_model": "other-model"})

    assert first.cohort_digest() == second.cohort_digest()
    assert first.cohort_digest() != changed_model.cohort_digest()

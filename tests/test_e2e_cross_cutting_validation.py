from __future__ import annotations

from pathlib import Path

import pytest

from evals.e2e_quality.cross_cutting_validation import (
    ValidationArchiveError,
    evaluate_suite,
    suite_nodeids,
)
from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES
from evals.e2e_quality.trace_archive import TraceArchive
from evals.e2e_quality.validation_catalog import (
    VALIDATION_SUITE_BY_ID,
    ValidationSuiteId,
)


def _nodeid(evidence_id: str) -> str:
    case = next(case for case in EVIDENCE_CASES if case.evidence_id == evidence_id)
    return f"evals/e2e_quality/{case.module}::{case.test_name}"


def _write_validation_archive(
    output_root: Path,
    cases: tuple[tuple[str, str, list[dict[str, object]]], ...],
    *,
    run_id: str = "validation-run",
    manifest_metadata: dict[str, object] | None = None,
) -> Path:
    archive = TraceArchive(
        output_root,
        run_id=run_id,
        manifest_metadata=manifest_metadata,
    )
    for evidence_id, outcome, inputs in cases:
        nodeid = _nodeid(evidence_id)
        archive.write_trace(
            nodeid=nodeid,
            case_id=evidence_id,
            trace={"interaction_trace": {"inputs": inputs}},
        )
        archive.record_test_result(
            nodeid=nodeid,
            phase="call",
            outcome=outcome,
            duration_seconds=0.1,
        )
    archive.finalize(exit_status=1 if any(case[1] == "failed" for case in cases) else 0)
    return archive.run_dir


def _tool_result(capability_id: str, *, status: str = "succeeded") -> dict[str, object]:
    return {
        "kind": "tool_result",
        "capability_id": capability_id,
        "status": status,
        "payload": {"ok": status == "succeeded"},
    }


def _agent_observation(capability_id: str) -> dict[str, object]:
    return {
        "kind": "agent_artifact",
        "capability_id": capability_id,
        "status": "succeeded",
        "payload": {"artifact_refs": ["aart_test"]},
    }


def test_tool_protocol_suite_uses_critical_checkpoints_not_pytest_outcome(
    temp_dir: Path,
) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        (
            (
                "L01.complex_loop_http",
                "failed",
                [_tool_result("search_personal_knowledge")],
            ),
            (
                "L06.complex_loop_http",
                "passed",
                [_tool_result("verify_interaction_draft")],
            ),
            (
                "RUN-001.baseline",
                "passed",
                [
                    _tool_result("external_records.read_one"),
                    _tool_result("external_records.read_one"),
                ],
            ),
            (
                "E16.capability_profile",
                "failed",
                [_tool_result("github.get_file_contents", status="failed")],
            ),
        ),
    )

    report = evaluate_suite(ValidationSuiteId.TOOL_CALLING_PROTOCOL, [run_dir])

    assert report.capability_passed is True
    assert report.passed_cases == report.total_cases == 4
    by_evidence = {case.evidence_id: case for case in report.cases}
    assert by_evidence["L01.complex_loop_http"].pytest_outcome == "failed"
    assert by_evidence["E16.capability_profile"].pytest_outcome == "failed"
    assert by_evidence["E16.capability_profile"].capability_passed is True


def test_tool_protocol_suite_fails_the_case_that_never_reaches_gateway(
    temp_dir: Path,
) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        (
            (
                "L06.complex_loop_http",
                "failed",
                [{
                    "kind": "decision_feedback",
                    "reason_code": "verification_capability_unavailable",
                }],
            ),
        ),
    )

    report = evaluate_suite(ValidationSuiteId.TOOL_CALLING_PROTOCOL, [run_dir])
    l06 = next(
        case for case in report.cases if case.evidence_id == "L06.complex_loop_http"
    )

    assert l06.capability_passed is False
    assert l06.checks[0].detail == "required>=1; observed=0"
    assert report.capability_passed is False


def test_protocol_rejection_fails_even_when_a_tool_result_exists(temp_dir: Path) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        (
            (
                "L01.complex_loop_http",
                "failed",
                [
                    _tool_result("search_personal_knowledge"),
                    {
                        "kind": "decision_feedback",
                        "reason_code": "invalid_arguments",
                    },
                ],
            ),
        ),
    )

    report = evaluate_suite(ValidationSuiteId.TOOL_CALLING_PROTOCOL, [run_dir])
    l01 = next(
        case for case in report.cases if case.evidence_id == "L01.complex_loop_http"
    )

    assert l01.capability_passed is False
    assert l01.checks[1].detail == "forbidden feedback: invalid_arguments"


def test_one_e2e_can_belong_to_multiple_validation_suites() -> None:
    tool_cases = {
        case.evidence_id
        for case in VALIDATION_SUITE_BY_ID[
            ValidationSuiteId.TOOL_CALLING_PROTOCOL
        ].cases
    }
    mcp_cases = {
        case.evidence_id
        for case in VALIDATION_SUITE_BY_ID[ValidationSuiteId.MCP_DISPATCH].cases
    }

    assert tool_cases & mcp_cases == {
        "RUN-001.baseline",
        "E16.capability_profile",
    }


def test_a2a_validation_reuses_l04_instead_of_a_duplicate_profile_case() -> None:
    suite = VALIDATION_SUITE_BY_ID[ValidationSuiteId.A2A_ARTIFACT_RETURN]
    current_case_ids = {case.case_id for case in EVIDENCE_CASES}

    assert [case.evidence_id for case in suite.cases] == ["L04.complex_loop_http"]
    assert "E17" not in current_case_ids


def test_narrow_research_routing_is_independent_from_product_outcome(
    temp_dir: Path,
) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        ((
            "ASK-001B.product_http",
            "failed",
            [
                _tool_result("search_personal_knowledge"),
                _tool_result("web_search"),
            ],
        ),),
    )

    report = evaluate_suite(ValidationSuiteId.NARROW_RESEARCH_ROUTING, [run_dir])

    assert report.capability_passed is True
    assert report.cases[0].pytest_outcome == "failed"
    assert report.cases[0].checks[2].detail == "required>=0 and <=0; observed=0"


def test_narrow_research_routing_rejects_whole_request_delegation(
    temp_dir: Path,
) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        ((
            "ASK-001B.product_http",
            "passed",
            [
                _tool_result("search_personal_knowledge"),
                _tool_result("web_search"),
                _agent_observation("gpt_researcher"),
            ],
        ),),
    )

    report = evaluate_suite(ValidationSuiteId.NARROW_RESEARCH_ROUTING, [run_dir])

    assert report.capability_passed is False
    assert report.cases[0].checks[2].detail == "required>=0 and <=0; observed=1"


def test_suite_nodeids_are_existing_canonical_pytest_nodes() -> None:
    suite = VALIDATION_SUITE_BY_ID[ValidationSuiteId.TOOL_CALLING_PROTOCOL]
    known = {
        f"evals/e2e_quality/{case.module}::{case.test_name}"
        for case in EVIDENCE_CASES
    }

    assert set(suite_nodeids(suite)) <= known


def test_validation_rejects_unsealed_archive(temp_dir: Path) -> None:
    run_dir = _write_validation_archive(
        temp_dir,
        (("L01.complex_loop_http", "passed", []),),
    )
    (run_dir / "checksums.sha256").unlink()

    with pytest.raises(ValidationArchiveError, match="invalid sealed archive"):
        evaluate_suite(ValidationSuiteId.TOOL_CALLING_PROTOCOL, [run_dir])


def test_validation_rejects_cross_identity_archive_stitching(temp_dir: Path) -> None:
    first = _write_validation_archive(
        temp_dir,
        (("L01.complex_loop_http", "passed", []),),
        run_id="identity-one",
        manifest_metadata={"provider_variant": "one"},
    )
    second = _write_validation_archive(
        temp_dir,
        (("L06.complex_loop_http", "passed", []),),
        run_id="identity-two",
        manifest_metadata={"provider_variant": "two"},
    )

    with pytest.raises(ValidationArchiveError, match="different repository"):
        evaluate_suite(ValidationSuiteId.TOOL_CALLING_PROTOCOL, [first, second])

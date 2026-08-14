from __future__ import annotations

import json

from evals.e2e_quality.evidence_catalog import (
    BaselineKind,
    EntryBoundary,
    EvidenceCase,
    EvidenceClass,
    UserOutcomeContract,
)
from evals.e2e_quality.release_gate import (
    LOOP_CAPABILITIES,
    NATIVE_CAPABILITIES,
    REQUIRED_NATIVE_EVIDENCE_IDS,
    REQUIRED_LOOP_EVIDENCE_IDS,
    evaluate_release_capabilities,
)
from evals.e2e_quality.trace_archive import TraceArchive


REVISION = "a" * 40


def _case(
    evidence_id: str,
    *,
    test_doubles: frozenset[str] = frozenset(),
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{evidence_id}.release",
        case_id=evidence_id,
        module="test_product_capabilities.py",
        test_name=f"test_{evidence_id.lower()}",
        layers=frozenset(),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        test_doubles=test_doubles,
        user_outcome_contract=UserOutcomeContract(
            outcome_id=f"outcome-{evidence_id}",
            persona="tester",
            source_ref="test-contract",
            natural_goal="exercise the release outcome",
            observable_result="the asserted user-visible result is returned",
            counterfactuals=("no hidden side effect",),
            baseline_kind=BaselineKind.REGRESSION_CONTRACT,
            baseline_ref="test-baseline",
            assertion_owner="this test",
        ),
    )


def _catalog() -> tuple[EvidenceCase, ...]:
    native = tuple(
        _case(evidence_id)
        for evidence_id in REQUIRED_NATIVE_EVIDENCE_IDS
    )
    loops = tuple(
        _case(evidence_id)
        for evidence_id in REQUIRED_LOOP_EVIDENCE_IDS
    )
    return native + loops


def _write_passing_archive(temp_dir, cases: tuple[EvidenceCase, ...]) -> None:
    archive = TraceArchive(temp_dir, run_id="release-run")
    manifest_path = archive.run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["repository"] = {
        "commit": REVISION,
        "branch": "main",
        "dirty": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for case in cases:
        nodeid = f"evals/e2e_quality/{case.module}::{case.test_name}"
        archive.write_trace(
            nodeid=nodeid,
            case_id=case.evidence_id,
            trace={"result": "user-visible"},
        )
        archive.record_test_result(
            nodeid=nodeid,
            phase="call",
            outcome="passed",
            duration_seconds=0.1,
        )
    archive.finalize(exit_status=0)


def test_gate_trusts_only_same_revision_catalog_and_trace_intersection(temp_dir) -> None:
    cases = _catalog()
    _write_passing_archive(temp_dir, cases)

    report = evaluate_release_capabilities(
        revision=REVISION,
        target_dirty=False,
        trace_root=temp_dir,
        evidence_cases=cases,
    )

    assert len(report.trusted_native_capability_ids) == len(NATIVE_CAPABILITIES)
    assert len(report.trusted_loop_capability_ids) == len(LOOP_CAPABILITIES)


def test_catalog_or_implementation_presence_without_trace_is_unverified(temp_dir) -> None:
    report = evaluate_release_capabilities(
        revision=REVISION,
        target_dirty=False,
        trace_root=temp_dir,
        evidence_cases=_catalog(),
    )

    assert report.trusted_native_capability_ids == ()
    assert all(
        result.status == "unverified"
        for result in report.native_capabilities
    )


def test_dirty_target_revision_fails_closed_even_with_passing_archive(temp_dir) -> None:
    cases = _catalog()
    _write_passing_archive(temp_dir, cases)

    report = evaluate_release_capabilities(
        revision=REVISION,
        target_dirty=True,
        trace_root=temp_dir,
        evidence_cases=cases,
    )

    assert report.trusted_native_capability_ids == ()
    assert all(
        "target_revision_dirty" in evidence.reasons
        for evidence in report.native_evidence
    )


def test_test_double_cannot_become_release_evidence(temp_dir) -> None:
    cases = list(_catalog())
    target_id = REQUIRED_NATIVE_EVIDENCE_IDS[0]
    cases[0] = _case(
        target_id,
        test_doubles=frozenset({"FakeProvider"}),
    )
    frozen_cases = tuple(cases)
    _write_passing_archive(temp_dir, frozen_cases)

    report = evaluate_release_capabilities(
        revision=REVISION,
        target_dirty=False,
        trace_root=temp_dir,
        evidence_cases=frozen_cases,
    )

    target = next(
        item for item in report.native_evidence if item.evidence_id == target_id
    )
    assert target.status == "unverified"
    assert "release_catalog_entry_ineligible" in target.reasons

from evals.e2e_quality.evidence_catalog import (
    EVIDENCE_CASES,
    EvidenceClaimKind,
    EntryBoundary,
    FaultMechanism,
)
from evals.e2e_quality.release_gate import REQUIRED_NATIVE_EVIDENCE_IDS


def test_legacy_architecture_catalog_remains_fully_classified() -> None:
    assert {case.case_id for case in EVIDENCE_CASES} == {
        f"E{index:02d}" for index in range(1, 18)
    }


def test_legacy_architecture_ids_do_not_claim_native_product_evidence() -> None:
    product_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.claim_kind is EvidenceClaimKind.PRODUCT_CAPABILITY
    }

    assert product_ids == set()
    assert set(REQUIRED_NATIVE_EVIDENCE_IDS) - product_ids == set(
        REQUIRED_NATIVE_EVIDENCE_IDS
    )


def test_release_evidence_cannot_use_internal_boundaries_or_test_mechanisms() -> None:
    release_cases = [case for case in EVIDENCE_CASES if case.release_eligible]

    assert release_cases
    for case in release_cases:
        assert case.entry_boundary is EntryBoundary.HTTP_PROCESS
        assert case.fault_mechanism is not FaultMechanism.IN_PROCESS_HOOK
        assert case.test_doubles == frozenset()
        assert case.raw_user_input is True
        assert case.real_model_required is True
        assert case.real_postgres_required is True

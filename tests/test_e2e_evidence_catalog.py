from evals.e2e_quality.evidence_catalog import (
    CapabilityProfile,
    EVIDENCE_CASES,
    EvidenceClass,
    EntryBoundary,
    FaultMechanism,
)
from evals.e2e_quality.release_gate import (
    NATIVE_CAPABILITIES,
    REQUIRED_NATIVE_EVIDENCE_IDS,
)
from evals.e2e_quality.evidence_audit import build_overlap_graph
from evals.e2e_quality.test_release_user_outcomes import (
    _child_environment,
    _release_profile_settings,
)
from personal_agent.kernel.config import OpenAIConfig, Settings, StructuredConfig


def test_catalog_declares_one_explicit_evidence_responsibility_per_case() -> None:
    application_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.evidence_class is EvidenceClass.APPLICATION_E2E
    }
    profile_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.evidence_class is EvidenceClass.CAPABILITY_PROFILE
    }
    assert {"E08", "E12"} <= application_ids
    assert "IP01" not in application_ids
    assert profile_ids == {"E16", "E17", "E18", "E19", "E21"}


def test_product_release_matrix_contains_only_qualified_user_outcomes() -> None:
    product_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.release_eligible
    }

    assert product_ids == set(REQUIRED_NATIVE_EVIDENCE_IDS) | {
        "L01", "L03", "L04", "L06", "L07"
    }
    assert {"IP01", "DUR-001", "L02", "E12"}.isdisjoint(product_ids)


def test_current_catalog_has_no_historical_failure_or_synthetic_comparison() -> None:
    current_ids = {case.case_id for case in EVIDENCE_CASES}

    assert "B03" not in current_ids
    assert "LT09" not in current_ids


def test_every_required_product_evidence_is_consumed_by_an_application_capability() -> None:
    owners = {evidence_id: [] for evidence_id in REQUIRED_NATIVE_EVIDENCE_IDS}
    for capability in NATIVE_CAPABILITIES:
        for evidence_id in capability.required_evidence_ids:
            owners[evidence_id].append(capability.capability_id)

    assert all(capability_ids for capability_ids in owners.values()), owners


def test_every_product_release_claim_has_typed_user_outcome_metadata() -> None:
    assert all(
        case.user_outcome_contract is not None
        for case in EVIDENCE_CASES
        if case.release_eligible
    )


def test_overlap_graph_exposes_shared_invariants_without_erasing_unique_ones() -> None:
    edges = build_overlap_graph(EVIDENCE_CASES)
    shared_pairs = {
        frozenset((edge.left_evidence_id, edge.right_evidence_id))
        for edge in edges
    }
    assert frozenset(("E14.product_http", "L07.complex_loop_http")) in shared_pairs
    assert frozenset(("L04.complex_loop_http", "E17.capability_profile")) in shared_pairs
    e08 = next(case for case in EVIDENCE_CASES if case.case_id == "E08")
    assert "knowledge_save.direct_solidify_contract" in e08.covered_invariants


def test_executable_assertions_and_profiles_own_outcomes_without_dead_metadata() -> None:
    assert all(not hasattr(case, "expected_terminal") for case in EVIDENCE_CASES)
    assert all(not hasattr(case, "real_provider_required") for case in EVIDENCE_CASES)


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


def test_real_mcp_evidence_uses_the_provider_profiles_it_executes() -> None:
    profiles = {
        case.case_id: case.capability_profile
        for case in EVIDENCE_CASES
        if case.case_id in {"E16", "E18"}
    }

    assert profiles == {
        "E16": CapabilityProfile.GITHUB_MCP,
        "E18": CapabilityProfile.NOTION_MCP,
    }


def test_release_model_profile_is_frozen_before_the_child_process(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_AGENT_E2E_MODEL_PROFILE", "chat")
    monkeypatch.setenv("PERSONAL_AGENT_E2E_MODEL_TIMEOUT_SECONDS", "90")
    settings = Settings(
        openai=OpenAIConfig(
            api_key="chat-key",
            base_url="https://chat.example/v1",
            model="chat-model",
        ),
        structured=StructuredConfig(
            api_key="planner-key",
            base_url="https://planner.example/v1",
            model="planner-model",
        ),
    )

    selected = _release_profile_settings(settings)

    assert selected.structured.api_key == "chat-key"
    assert selected.structured.base_url == "https://chat.example/v1"
    assert selected.structured.model == "chat-model"
    assert selected.structured.timeout_seconds == 90
    assert selected.openai.api_key == "chat-key"
    assert selected.openai.model == "chat-model"
    assert selected.openai.small_model == "chat-model"
    assert settings.structured.model == "planner-model"


def test_configured_release_profile_also_drives_conversation_model(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_AGENT_E2E_MODEL_PROFILE", "configured")
    settings = Settings(
        openai=OpenAIConfig(
            api_key="chat-key",
            base_url="https://chat.example/v1",
            model="chat-model",
        ),
        structured=StructuredConfig(
            api_key="configured-key",
            base_url="https://configured.example/v1",
            model="configured-model",
            extra_body={"reasoning": {"effort": "minimal"}},
        ),
    )

    selected = _release_profile_settings(settings)

    assert selected.openai.api_key == "configured-key"
    assert selected.openai.base_url == "https://configured.example/v1"
    assert selected.openai.model == "configured-model"
    assert selected.openai.small_model == "configured-model"
    assert selected.structured.extra_body == {"reasoning": {"effort": "minimal"}}
    assert settings.openai.model == "chat-model"


def test_release_child_materializes_the_frozen_model_retry_profile(
    monkeypatch,
    temp_dir,
) -> None:
    monkeypatch.setenv("PERSONAL_AGENT_E2E_MODEL_PROFILE", "configured")
    monkeypatch.setenv("PERSONAL_AGENT_E2E_MODEL_TIMEOUT_SECONDS", "73")
    settings = Settings(
        postgres_url="postgresql://example.invalid/database",
        structured=StructuredConfig(
            api_key="configured-key",
            base_url="https://configured.example/v1",
            model="configured-model",
            max_retries=4,
        ),
    )

    child = _child_environment(_release_profile_settings(settings), temp_dir)

    assert child["PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS"] == "73.0"
    assert child["PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS"] == "73.0"
    assert child["PERSONAL_AGENT_STRUCTURED_MAX_RETRIES"] == "4"
    assert child["PERSONAL_AGENT_OPENAI_MAX_RETRIES"] == "4"


def test_release_child_disables_unrelated_feishu_side_effects(
    monkeypatch,
    temp_dir,
) -> None:
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "configured-app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "configured-secret")

    child = _child_environment(Settings(), temp_dir)

    assert child["PERSONAL_AGENT_FEISHU_ENABLED"] == "false"
    assert "FEISHU_APP_ID" not in child
    assert "FEISHU_APP_SECRET" not in child

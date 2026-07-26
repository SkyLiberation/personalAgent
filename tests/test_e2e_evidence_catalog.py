from evals.e2e_quality.evidence_catalog import (
    CapabilityProfile,
    EVIDENCE_CASES,
    EvidenceClaimKind,
    EntryBoundary,
    FaultMechanism,
)
from evals.e2e_quality.release_gate import (
    REQUIRED_COMPOSITE_EVIDENCE_IDS,
    REQUIRED_NATIVE_EVIDENCE_IDS,
)
from evals.e2e_quality.test_release_user_outcomes import (
    _child_environment,
    _release_profile_settings,
)
from personal_agent.kernel.config import OpenAIConfig, Settings, StructuredConfig


def test_catalog_contains_only_product_loop_and_external_profile_evidence() -> None:
    legacy_architecture_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.claim_kind is EvidenceClaimKind.ARCHITECTURE
    }
    profile_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.claim_kind is EvidenceClaimKind.CAPABILITY_PROFILE
    }
    assert legacy_architecture_ids == set()
    assert profile_ids == {"E16", "E17", "E18", "E19"}


def test_product_and_composite_release_matrices_are_complete() -> None:
    product_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.claim_kind is EvidenceClaimKind.PRODUCT_CAPABILITY
    }

    composite_ids = {
        case.case_id
        for case in EVIDENCE_CASES
        if case.claim_kind is EvidenceClaimKind.COMPOSITE_CAPABILITY
    }

    assert product_ids == set(REQUIRED_NATIVE_EVIDENCE_IDS)
    assert composite_ids == set(REQUIRED_COMPOSITE_EVIDENCE_IDS)


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
        if case.case_id in {"E06", "E16", "E18"}
    }

    assert profiles == {
        "E06": CapabilityProfile.GITHUB_NOTION_MCP,
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

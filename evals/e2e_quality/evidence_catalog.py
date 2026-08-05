"""Canonical release and external-profile E2E classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceLayer(str, Enum):
    UNDERSTANDING = "understanding"
    PLANNING_CONTROL = "planning_control"
    AUTHORITY_GATEWAY = "authority_gateway"
    JOURNAL_RECOVERY = "journal_recovery"
    VERIFICATION_COMPLETION = "verification_completion"


class EntryBoundary(str, Enum):
    IN_PROCESS_SERVICE = "in_process_service"
    HTTP_PROCESS = "http_process"


class FaultMechanism(str, Enum):
    NONE = "none"
    IN_PROCESS_HOOK = "in_process_hook"
    PROCESS_TERMINATION = "process_termination"


class EvidenceClaimKind(str, Enum):
    ARCHITECTURE = "architecture"
    PRODUCT_CAPABILITY = "product_capability"
    CAPABILITY_PROFILE = "capability_profile"
    COMPLEX_LOOP = "complex_loop"
    DURABLE_INVESTIGATION = "durable_investigation"
    BOUNDARY_EVALUATION = "boundary_evaluation"


class CapabilityProfile(str, Enum):
    BASELINE = "baseline"
    WEB_READER = "baseline+web_reader"
    WEB_SEARCH = "baseline+web_search"
    FILESYSTEM_MCP = "baseline+filesystem_mcp"
    GITHUB_MCP = "baseline+github_mcp"
    NOTION_MCP = "baseline+notion_mcp"
    GITHUB_NOTION_MCP = "baseline+github_mcp+notion_mcp"
    GPT_RESEARCHER_A2A = "baseline+gpt_researcher_a2a"
    WEB_SEARCH_DELIVERY = "baseline+web_search+delivery"


@dataclass(frozen=True, slots=True)
class EvidenceCase:
    evidence_id: str
    case_id: str
    module: str
    test_name: str
    layers: frozenset[EvidenceLayer]
    entry_boundary: EntryBoundary
    fault_mechanism: FaultMechanism = FaultMechanism.NONE
    raw_user_input: bool = True
    real_model_required: bool = True
    real_postgres_required: bool = True
    test_doubles: frozenset[str] = frozenset()
    limitation: str = ""
    claim_kind: EvidenceClaimKind = EvidenceClaimKind.ARCHITECTURE
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE

    @property
    def release_eligible(self) -> bool:
        return (
            self.claim_kind in {
                EvidenceClaimKind.PRODUCT_CAPABILITY,
                EvidenceClaimKind.COMPLEX_LOOP,
            }
            and self.entry_boundary is EntryBoundary.HTTP_PROCESS
            and self.fault_mechanism is not FaultMechanism.IN_PROCESS_HOOK
            and self.raw_user_input
            and self.real_model_required
            and self.real_postgres_required
            and not self.test_doubles
        )

    @property
    def node_key(self) -> tuple[str, str]:
        return self.module, self.test_name


def _product(
    case_id: str,
    test_name: str,
    *layers: EvidenceLayer,
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE,
    fault_mechanism: FaultMechanism = FaultMechanism.NONE,
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.product_http",
        case_id=case_id,
        module="test_product_capability_outcomes.py",
        test_name=test_name,
        layers=frozenset(layers),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=fault_mechanism,
        claim_kind=EvidenceClaimKind.PRODUCT_CAPABILITY,
        capability_profile=capability_profile,
    )


def _loop(
    case_id: str,
    test_name: str,
    *,
    fault_mechanism: FaultMechanism = FaultMechanism.NONE,
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE,
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.complex_loop_http",
        case_id=case_id,
        module="test_complex_loop_outcomes.py",
        test_name=test_name,
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=fault_mechanism,
        claim_kind=EvidenceClaimKind.COMPLEX_LOOP,
        capability_profile=capability_profile,
    )


def _profile(
    case_id: str,
    test_name: str,
    capability_profile: CapabilityProfile,
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.capability_profile",
        case_id=case_id,
        module="test_release_user_outcomes.py",
        test_name=test_name,
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        claim_kind=EvidenceClaimKind.CAPABILITY_PROFILE,
        capability_profile=capability_profile,
        limitation=(
            "Connector profile evidence; product release claims are owned by "
            "E01-E14, E20 and IP01."
        ),
    )


def _investigation(
    case_id: str,
    test_name: str,
    *,
    module: str,
    fault_mechanism: FaultMechanism = FaultMechanism.NONE,
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE,
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.durable_investigation",
        case_id=case_id,
        module=module,
        test_name=test_name,
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.IN_PROCESS_SERVICE,
        fault_mechanism=fault_mechanism,
        raw_user_input=False,
        real_model_required=False,
        test_doubles=frozenset({"scripted_model", "frozen_provider"}),
        claim_kind=EvidenceClaimKind.DURABLE_INVESTIGATION,
        capability_profile=capability_profile,
        limitation=(
            "Diagnostic durable-project state-machine evidence. It uses the production "
            "application/domain/persistence path with scripted semantic decisions and "
            "frozen providers; it is not release evidence for live model/provider behavior."
        ),
    )


EVIDENCE_CASES: tuple[EvidenceCase, ...] = (
    _product("E01", "test_product_e01_conversation_journey", EvidenceLayer.UNDERSTANDING, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E02", "test_product_e02_grounded_workspace_ask", EvidenceLayer.UNDERSTANDING, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E03", "test_product_e03_selected_upload_artifact_ask", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E04", "test_product_e04_governed_delete_recovery", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.JOURNAL_RECOVERY, EvidenceLayer.VERIFICATION_COMPLETION, fault_mechanism=FaultMechanism.PROCESS_TERMINATION),
    _product("E05", "test_product_e05_research_run_journey", EvidenceLayer.PLANNING_CONTROL, EvidenceLayer.JOURNAL_RECOVERY, EvidenceLayer.VERIFICATION_COMPLETION, capability_profile=CapabilityProfile.WEB_SEARCH),
    _product("E08", "test_product_e08_ask_then_explicit_save", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E09", "test_product_e09_multi_source_capture", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.VERIFICATION_COMPLETION, capability_profile=CapabilityProfile.WEB_READER),
    _product("E10", "test_product_e10_knowledge_lifecycle", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.JOURNAL_RECOVERY, EvidenceLayer.VERIFICATION_COMPLETION, fault_mechanism=FaultMechanism.PROCESS_TERMINATION),
    _product("E11", "test_product_e11_review_feedback_journey", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E12", "test_product_e12_knowledge_maintenance_journey", EvidenceLayer.PLANNING_CONTROL, EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.VERIFICATION_COMPLETION),
    _product("E13", "test_product_e13_scheduled_intelligence_journey", EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.JOURNAL_RECOVERY, EvidenceLayer.VERIFICATION_COMPLETION, capability_profile=CapabilityProfile.WEB_SEARCH_DELIVERY, fault_mechanism=FaultMechanism.PROCESS_TERMINATION),
    _product("E14", "test_product_e14_conversation_governed_save", EvidenceLayer.UNDERSTANDING, EvidenceLayer.AUTHORITY_GATEWAY, EvidenceLayer.JOURNAL_RECOVERY, EvidenceLayer.VERIFICATION_COMPLETION, fault_mechanism=FaultMechanism.PROCESS_TERMINATION),
    _product(
        "E20",
        "test_product_e20_workspace_answer_has_independent_verification",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _product(
        "E22",
        "test_product_e22_governed_delete_from_goal_entry",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _product(
        "E23",
        "test_product_e23_durable_investigation_from_goal_entry",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        capability_profile=CapabilityProfile.WEB_SEARCH,
    ),
    _product(
        "IP01",
        "test_product_ip01_live_investigation_report",
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        capability_profile=CapabilityProfile.WEB_SEARCH,
    ),
    _loop("L01", "test_l01_http_natural_recall_uses_observed_personal_knowledge"),
    _loop("L02", "test_l02_http_independent_reads_use_safe_concurrency"),
    _loop("L03", "test_l03_http_process_restart_rebuilds_from_committed_facts", fault_mechanism=FaultMechanism.PROCESS_TERMINATION),
    _loop("L04", "test_l04_http_manager_synthesizes_bounded_specialist_artifact", capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A),
    _loop("L05", "test_l05_http_budget_exhaustion_fails_closed"),
    _loop("L06", "test_l06_http_user_requested_review_returns_receipt_bound_safe_revision"),
    _profile("E16", "test_e16_http_process_reads_github_through_real_mcp_gateway", CapabilityProfile.GITHUB_MCP),
    _profile("E17", "test_e17_http_process_delegates_to_real_a2a_and_verifies_parent_result", CapabilityProfile.GPT_RESEARCHER_A2A),
    _profile("E18", "test_e18_http_process_reads_notion_through_real_mcp_gateway", CapabilityProfile.NOTION_MCP),
    _profile("E19", "test_e19_http_process_mcp_capability_unavailable_fails_closed", CapabilityProfile.BASELINE),
    _profile(
        "E21",
        "test_e21_http_process_answers_from_oversized_read_within_budget",
        CapabilityProfile.GITHUB_MCP,
    ),
    EvidenceCase(
        evidence_id="E24.research_boundary_evaluation",
        case_id="E24",
        module="test_product_capability_outcomes.py",
        test_name="test_e24_research_boundary_paired_baseline",
        layers=frozenset({
            EvidenceLayer.PLANNING_CONTROL,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        capability_profile=CapabilityProfile.WEB_SEARCH,
        claim_kind=EvidenceClaimKind.BOUNDARY_EVALUATION,
        limitation=(
            "Paired product-boundary measurement; it compares ResearchRun, Conversation, "
            "and Investigation Project but does not itself produce a release claim."
        ),
    ),
    _investigation(
        "LT01",
        "test_lt01_complete_architecture_investigation",
        module="test_durable_investigation_project.py",
        capability_profile=CapabilityProfile.GITHUB_NOTION_MCP,
    ),
    _investigation(
        "LT02",
        "test_lt02_command_dispatch_recovers_without_duplicate",
        module="test_durable_investigation_recovery.py",
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT03",
        "test_lt03_steering_preserves_frozen_work_and_user_requirements",
        module="test_durable_investigation_project.py",
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT04",
        "test_lt04_parallel_children_join_only_after_verified_outcomes",
        module="test_durable_investigation_project.py",
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT05",
        "test_lt05_external_delegation_waits_for_digest_bound_approval",
        module="test_durable_investigation_project.py",
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT06",
        "test_lt06_budget_exhaustion_pauses_with_partial_coverage",
        module="test_durable_investigation_project.py",
    ),
    _investigation(
        "LT07",
        "test_lt07_cancel_quarantines_late_result",
        module="test_durable_investigation_project.py",
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT08",
        "test_lt08_security_scope_isolation_survives_recovery",
        module="test_durable_investigation_project.py",
    ),
    _investigation(
        "LT10",
        "test_lt10_child_submit_reconciles_stable_submission_key",
        module="test_durable_investigation_recovery.py",
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
    ),
    _investigation(
        "LT11",
        "test_lt11_missing_capability_fails_closed_without_fallback",
        module="test_durable_investigation_project.py",
    ),
    _investigation(
        "LT12",
        "test_lt12_observation_revises_only_unfrozen_dynamic_plan",
        module="test_durable_investigation_project.py",
    ),
    _investigation(
        "LT13",
        "test_lt13_async_create_and_read_only_recovery",
        module="test_durable_investigation_recovery.py",
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
    ),
)

EVIDENCE_BY_NODE = {case.node_key: case for case in EVIDENCE_CASES}


def validate_catalog() -> None:
    evidence_ids = [case.evidence_id for case in EVIDENCE_CASES]
    node_keys = [case.node_key for case in EVIDENCE_CASES]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence_id in E2E evidence catalog")
    if len(node_keys) != len(set(node_keys)):
        raise ValueError("one E2E test node cannot own multiple evidence classifications")
    expected = {
        EvidenceClaimKind.PRODUCT_CAPABILITY: {
            "E01", "E02", "E03", "E04", "E05",
            "E08", "E09", "E10", "E11", "E12", "E13", "E14",
            "E20",
            "E22", "E23",
            "IP01",
        },
        EvidenceClaimKind.COMPLEX_LOOP: {f"L{index:02d}" for index in range(1, 7)},
        EvidenceClaimKind.CAPABILITY_PROFILE: {"E16", "E17", "E18", "E19", "E21"},
        EvidenceClaimKind.DURABLE_INVESTIGATION: {
            *(f"LT{index:02d}" for index in range(1, 9)),
            "LT10", "LT11", "LT12", "LT13",
        },
        EvidenceClaimKind.BOUNDARY_EVALUATION: {"E24"},
    }
    for kind, case_ids in expected.items():
        actual = {case.case_id for case in EVIDENCE_CASES if case.claim_kind is kind}
        if actual != case_ids:
            raise ValueError(f"{kind.value} E2E catalog coverage mismatch: {sorted(actual ^ case_ids)}")
    if any(case.claim_kind is EvidenceClaimKind.ARCHITECTURE for case in EVIDENCE_CASES):
        raise ValueError("legacy architecture cases are not allowed in the release catalog")


validate_catalog()


__all__ = [
    "CapabilityProfile",
    "EVIDENCE_BY_NODE",
    "EVIDENCE_CASES",
    "EntryBoundary",
    "EvidenceCase",
    "EvidenceClaimKind",
    "EvidenceLayer",
    "FaultMechanism",
    "validate_catalog",
]

"""Canonical classification for architecture E2E evidence.

The catalog owns only test-evidence metadata. Business facts remain owned by
the production contracts and stores that each test asserts against.
"""

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
    COMPOSITE_CAPABILITY = "composite_capability"
    COMPLEX_LOOP = "complex_loop"


class CapabilityProfile(str, Enum):
    BASELINE = "baseline"
    WEB_READER = "baseline+web_reader"
    WEB_SEARCH = "baseline+web_search"
    GITHUB_MCP = "baseline+github_mcp"
    NOTION_MCP = "baseline+notion_mcp"
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
    real_provider_required: bool = True
    test_doubles: frozenset[str] = frozenset()
    expected_terminal: str = "completed"
    limitation: str = ""
    claim_kind: EvidenceClaimKind = EvidenceClaimKind.ARCHITECTURE
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE

    @property
    def release_eligible(self) -> bool:
        """Whether a passing trace is allowed to count toward release evidence."""
        return (
            self.entry_boundary is EntryBoundary.HTTP_PROCESS
            and self.fault_mechanism is not FaultMechanism.IN_PROCESS_HOOK
            and self.raw_user_input
            and self.real_model_required
            and self.real_postgres_required
            and not self.test_doubles
        )

    @property
    def node_key(self) -> tuple[str, str]:
        return self.module, self.test_name


def _diagnostic(
    case_id: str,
    test_name: str,
    *layers: EvidenceLayer,
    fault_mechanism: FaultMechanism = FaultMechanism.NONE,
    expected_terminal: str = "completed",
    limitation: str = "进程内 AgentService 入口，不计发布级黑盒证据。",
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.diagnostic",
        case_id=case_id,
        module="test_core_user_outcomes.py",
        test_name=test_name,
        layers=frozenset(layers),
        entry_boundary=EntryBoundary.IN_PROCESS_SERVICE,
        fault_mechanism=fault_mechanism,
        expected_terminal=expected_terminal,
        limitation=limitation,
    )


EVIDENCE_CASES: tuple[EvidenceCase, ...] = (
    _diagnostic(
        "E01",
        "test_simple_request_is_understood_answered_and_verified_live",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _diagnostic(
        "E02",
        "test_compound_write_then_answer_runs_from_live_understanding",
        *EvidenceLayer,
    ),
    _diagnostic(
        "E03",
        "test_missing_unsupported_mutation_input_never_fabricates_success_live",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        expected_terminal="fail_closed",
    ),
    _diagnostic(
        "E04",
        "test_live_delete_request_never_mutates_before_confirmation",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        expected_terminal="waiting_confirmation",
    ),
    _diagnostic(
        "E06",
        "test_live_user_rejection_of_delete_never_mutates",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        expected_terminal="rejected",
    ),
    _diagnostic(
        "E07",
        "test_live_dispatch_window_recovers_without_replaying_provider_call",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        fault_mechanism=FaultMechanism.IN_PROCESS_HOOK,
        limitation="使用 post_gateway_dispatch_hook，定位恢复不变量但不计发布级故障证据。",
    ),
    _diagnostic(
        "E10",
        "test_live_task_compilation_commit_is_atomic_across_recovery",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.JOURNAL_RECOVERY,
        fault_mechanism=FaultMechanism.IN_PROCESS_HOOK,
        limitation="使用 post_task_compilation_commit_hook，不计真实进程故障证据。",
    ),
    _diagnostic(
        "E08",
        "test_live_explicit_task_analysis_is_accepted_without_rewrite",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        expected_terminal="waiting_confirmation",
    ),
    _diagnostic(
        "E05",
        "test_live_missing_remote_capability_fails_closed_before_grant",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        expected_terminal="capability_gap",
    ),
    _diagnostic(
        "E14",
        "test_live_capability_acquisition_approval_never_fabricates_provider",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        expected_terminal="awaiting_environment_change",
    ),
    _diagnostic(
        "E09",
        "test_live_compiler_owns_shared_and_goal_local_resource_scope",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.PLANNING_CONTROL,
    ),
    _diagnostic(
        "E11",
        "test_live_plan_monitor_only_patches_the_capability_gap_branch",
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.VERIFICATION_COMPLETION,
        expected_terminal="capability_gap",
    ),
    _diagnostic(
        "E12",
        "test_live_planner_admission_has_no_deterministic_repair",
        EvidenceLayer.PLANNING_CONTROL,
        expected_terminal="revised_or_fail_closed",
    ),
    _diagnostic(
        "E13",
        "test_live_scope_expanded_control_proposal_has_no_execution_facts",
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.AUTHORITY_GATEWAY,
        expected_terminal="denied",
    ),
    _diagnostic(
        "E15",
        "test_live_untrusted_retrieval_instruction_is_never_verification_evidence",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        expected_terminal="verified_without_tainted_evidence_or_fail_closed",
    ),
    EvidenceCase(
        evidence_id="E01.release_http",
        case_id="E01",
        module="test_release_user_outcomes.py",
        test_name="test_e01_http_process_completes_verified_response",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.PLANNING_CONTROL,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        real_provider_required=False,
        expected_terminal="completed",
    ),
    EvidenceCase(
        evidence_id="E02.release_http_restart_confirm",
        case_id="E02",
        module="test_release_user_outcomes.py",
        test_name="test_e02_http_process_restart_confirm_completes_compound_task",
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        expected_terminal="completed",
    ),
    EvidenceCase(
        evidence_id="E03.release_http_fail_closed",
        case_id="E03",
        module="test_release_user_outcomes.py",
        test_name="test_e03_http_process_missing_mutation_input_fails_closed",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        real_provider_required=False,
        expected_terminal="fail_closed",
    ),
    EvidenceCase(
        evidence_id="E04.release_http_confirmation_boundary",
        case_id="E04",
        module="test_release_user_outcomes.py",
        test_name="test_e04_http_process_delete_waits_for_confirmation_without_effect",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="waiting_confirmation",
    ),
    EvidenceCase(
        evidence_id="E06.release_http_restart_reject",
        case_id="E06",
        module="test_release_user_outcomes.py",
        test_name="test_e06_http_process_restart_rejects_delete_without_effect",
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.JOURNAL_RECOVERY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        expected_terminal="rejected",
    ),
    EvidenceCase(
        evidence_id="E07.release_http_process_dispatch_recovery",
        case_id="E07",
        module="test_release_user_outcomes.py",
        test_name="test_e07_http_process_recovers_dispatched_result_without_duplicate_effect",
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.JOURNAL_RECOVERY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        expected_terminal="completed",
    ),
    EvidenceCase(
        evidence_id="E10.release_http_process_compilation_recovery",
        case_id="E10",
        module="test_release_user_outcomes.py",
        test_name="test_e10_http_process_recovers_atomic_compilation_commit",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.PLANNING_CONTROL,
            EvidenceLayer.JOURNAL_RECOVERY,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        real_provider_required=False,
        expected_terminal="completed",
    ),
    EvidenceCase(
        evidence_id="E08.release_http_analysis_freeze",
        case_id="E08",
        module="test_release_user_outcomes.py",
        test_name="test_e08_http_process_accepts_explicit_analysis_without_rewrite",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="waiting_confirmation",
    ),
    EvidenceCase(
        evidence_id="E05.release_http_capability_gap",
        case_id="E05",
        module="test_release_user_outcomes.py",
        test_name="test_e05_http_process_missing_provider_fails_closed_before_grant",
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        real_provider_required=False,
        expected_terminal="capability_gap",
    ),
    EvidenceCase(
        evidence_id="E14.release_http_acquisition_approval",
        case_id="E14",
        module="test_release_user_outcomes.py",
        test_name=(
            "test_e14_http_process_acquisition_approval_awaits_real_environment_change"
        ),
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.JOURNAL_RECOVERY,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        real_provider_required=False,
        expected_terminal="awaiting_environment_change",
    ),
    EvidenceCase(
        evidence_id="E09.release_http_resource_ownership",
        case_id="E09",
        module="test_release_user_outcomes.py",
        test_name=(
            "test_e09_http_process_compiler_owns_shared_and_goal_local_resources"
        ),
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.PLANNING_CONTROL,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        real_provider_required=False,
        expected_terminal="compiled_resource_ownership",
    ),
    EvidenceCase(
        evidence_id="E11.release_http_required_provider_acquisition",
        case_id="E11",
        module="test_release_user_outcomes.py",
        test_name="test_e11_http_process_unavailable_required_provider_requests_acquisition",
        layers=frozenset({
            EvidenceLayer.PLANNING_CONTROL,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="capability_acquisition_required",
    ),
    EvidenceCase(
        evidence_id="E12.release_http_planner_admission",
        case_id="E12",
        module="test_release_user_outcomes.py",
        test_name="test_e12_http_process_planner_admission_has_no_code_repair",
        layers=frozenset({EvidenceLayer.PLANNING_CONTROL}),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        real_provider_required=False,
        expected_terminal="accepted_or_feedback_without_fallback",
    ),
    EvidenceCase(
        evidence_id="E13.release_http_cross_user_scope",
        case_id="E13",
        module="test_release_user_outcomes.py",
        test_name="test_e13_http_process_cross_user_note_scope_fails_closed",
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="cross_user_scope_denied",
    ),
    EvidenceCase(
        evidence_id="E15.release_http_untrusted_evidence",
        case_id="E15",
        module="test_release_user_outcomes.py",
        test_name=(
            "test_e15_http_process_rejects_retrieved_instruction_as_verification_evidence"
        ),
        layers=frozenset({
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="verified_without_tainted_evidence_or_fail_closed",
    ),
    EvidenceCase(
        evidence_id="E16.release_http_real_mcp_gateway",
        case_id="E16",
        module="test_release_user_outcomes.py",
        test_name="test_e16_http_process_reads_through_real_mcp_gateway_and_verifies",
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="completed",
        claim_kind=EvidenceClaimKind.CAPABILITY_PROFILE,
        capability_profile=CapabilityProfile.GITHUB_MCP,
    ),
    EvidenceCase(
        evidence_id="E17.release_http_real_a2a_delegation",
        case_id="E17",
        module="test_release_user_outcomes.py",
        test_name=(
            "test_e17_http_process_delegates_to_real_a2a_and_verifies_parent_result"
        ),
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        expected_terminal="completed",
        claim_kind=EvidenceClaimKind.CAPABILITY_PROFILE,
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
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
    covered = {case.case_id for case in EVIDENCE_CASES}
    expected = {f"E{index:02d}" for index in range(1, 18)}
    if covered != expected:
        raise ValueError(f"E2E catalog coverage mismatch: {sorted(covered ^ expected)}")


validate_catalog()

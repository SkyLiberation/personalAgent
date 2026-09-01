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


class EvidenceClass(str, Enum):
    PRODUCT_E2E = "product_e2e"
    APPLICATION_E2E = "application_e2e"
    RUNTIME_CONFORMANCE = "runtime_conformance"
    CAPABILITY_PROFILE = "capability_profile"
    BOUNDARY_EVALUATION = "boundary_evaluation"


class BaselineKind(str, Enum):
    IMPLEMENTATION_FAILURE = "implementation_failure"
    REGRESSION_CONTRACT = "regression_contract"


@dataclass(frozen=True, slots=True)
class UserOutcomeContract:
    """Why one Product E2E may contribute to product completion claims."""

    outcome_id: str
    persona: str
    source_ref: str
    natural_goal: str
    observable_result: str
    counterfactuals: tuple[str, ...]
    baseline_kind: BaselineKind
    baseline_ref: str
    assertion_owner: str


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
    evidence_class: EvidenceClass
    fault_mechanism: FaultMechanism = FaultMechanism.NONE
    raw_user_input: bool = True
    real_model_required: bool = True
    real_postgres_required: bool = True
    test_doubles: frozenset[str] = frozenset()
    limitation: str = ""
    user_outcome_contract: UserOutcomeContract | None = None
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE
    covered_invariants: frozenset[str] = frozenset()

    @property
    def release_eligible(self) -> bool:
        return (
            self.evidence_class is EvidenceClass.PRODUCT_E2E
            and self.user_outcome_contract is not None
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
    evidence_class: EvidenceClass = EvidenceClass.APPLICATION_E2E,
    user_outcome_contract: UserOutcomeContract | None = None,
    limitation: str = "",
    covered_invariants: frozenset[str] = frozenset(),
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.product_http",
        case_id=case_id,
        module="test_product_capability_outcomes.py",
        test_name=test_name,
        layers=frozenset(layers),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=fault_mechanism,
        evidence_class=evidence_class,
        user_outcome_contract=user_outcome_contract,
        limitation=limitation,
        covered_invariants=covered_invariants,
        capability_profile=capability_profile,
    )


def _loop(
    case_id: str,
    test_name: str,
    *,
    fault_mechanism: FaultMechanism = FaultMechanism.NONE,
    capability_profile: CapabilityProfile = CapabilityProfile.BASELINE,
    evidence_class: EvidenceClass = EvidenceClass.RUNTIME_CONFORMANCE,
    user_outcome_contract: UserOutcomeContract | None = None,
    covered_invariants: frozenset[str] = frozenset(),
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.complex_loop_http",
        case_id=case_id,
        module="test_complex_loop_outcomes.py",
        test_name=test_name,
        layers=frozenset(EvidenceLayer),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        fault_mechanism=fault_mechanism,
        evidence_class=evidence_class,
        user_outcome_contract=user_outcome_contract,
        covered_invariants=covered_invariants,
        capability_profile=capability_profile,
    )


def _profile(
    case_id: str,
    test_name: str,
    capability_profile: CapabilityProfile,
    *,
    covered_invariants: frozenset[str] = frozenset(),
) -> EvidenceCase:
    return EvidenceCase(
        evidence_id=f"{case_id}.capability_profile",
        case_id=case_id,
        module="test_release_user_outcomes.py",
        test_name=test_name,
        layers=frozenset(
            {
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.VERIFICATION_COMPLETION,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.CAPABILITY_PROFILE,
        capability_profile=capability_profile,
        covered_invariants=covered_invariants,
        limitation=(
            "Connector profile evidence; product release claims are owned by "
            "the product capability and complex-loop E2E suites."
        ),
    )


def _outcome(
    outcome_id: str,
    *,
    natural_goal: str,
    observable_result: str,
    counterfactuals: tuple[str, ...],
    baseline_ref: str,
    baseline_kind: BaselineKind = BaselineKind.REGRESSION_CONTRACT,
) -> UserOutcomeContract:
    return UserOutcomeContract(
        outcome_id=outcome_id,
        persona="使用个人知识 Agent 的知识工作者",
        source_ref="docs/evals/02-current-case-inventory.md",
        natural_goal=natural_goal,
        observable_result=observable_result,
        counterfactuals=counterfactuals,
        baseline_kind=baseline_kind,
        baseline_ref=baseline_ref,
        assertion_owner="the executable assertions in the catalogued pytest node",
    )


EVIDENCE_CASES: tuple[EvidenceCase, ...] = (
    EvidenceCase(
        evidence_id="ASK-001A.product_http",
        case_id="ASK-001A",
        module="test_conversation_grounded_answer.py",
        test_name=(
            "test_ask_001a_personal_only_answer_observes_quotes_and_conflict_without_web"
        ),
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "grounded_answer.personal_only",
            natural_goal="只根据我保存的资料回答并给出原文依据",
            observable_result="回答引用当前用户的保存资料并正确呈现冲突",
            counterfactuals=("不调用 Web", "不泄漏其他用户资料", "Ask 不写入知识"),
            baseline_ref="behavior-baseline:ASK-001A",
        ),
        covered_invariants=frozenset({"ask.zero_write", "grounded_answer.personal"}),
        capability_profile=CapabilityProfile.WEB_SEARCH,
    ),
    EvidenceCase(
        evidence_id="ASK-001B.product_http",
        case_id="ASK-001B",
        module="test_conversation_grounded_answer.py",
        test_name=(
            "test_ask_001b_one_conversation_combines_personal_and_official_web_evidence"
        ),
        layers=frozenset({
            EvidenceLayer.UNDERSTANDING,
            EvidenceLayer.AUTHORITY_GATEWAY,
            EvidenceLayer.VERIFICATION_COMPLETION,
        }),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "grounded_answer.personal_and_web",
            natural_goal="结合我的资料与官方 Web 证据回答",
            observable_result="一个回答同时包含正确个人事实与可追溯官方证据",
            counterfactuals=("不泄漏其他用户资料", "Ask 不写入知识"),
            baseline_ref="behavior-baseline:ASK-001B",
        ),
        covered_invariants=frozenset({"ask.zero_write", "grounded_answer.web"}),
        capability_profile=CapabilityProfile.WEB_SEARCH,
    ),
    _product(
        "E01",
        "test_product_e01_conversation_journey",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _product(
        "E04",
        "test_product_e04_governed_delete_recovery",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        covered_invariants=frozenset({
            "knowledge_delete.confirmed",
            "knowledge_delete.reject_and_multi_pending",
        }),
    ),
    _product(
        "E05",
        "test_product_e05_research_run_journey",
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        capability_profile=CapabilityProfile.WEB_SEARCH,
    ),
    _product(
        "E09",
        "test_product_e09_multi_source_capture",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        capability_profile=CapabilityProfile.WEB_READER,
    ),
    _product(
        "E10",
        "test_product_e10_knowledge_lifecycle",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        covered_invariants=frozenset({
            "knowledge_delete.confirmed",
            "knowledge_restore.replay",
            "knowledge_correction.answer",
        }),
    ),
    _product(
        "E11",
        "test_product_e11_review_feedback_journey",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _product(
        "E12",
        "test_product_e12_knowledge_maintenance_journey",
        EvidenceLayer.PLANNING_CONTROL,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.VERIFICATION_COMPLETION,
    ),
    _product(
        "E13",
        "test_product_e13_scheduled_intelligence_journey",
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        capability_profile=CapabilityProfile.WEB_SEARCH_DELIVERY,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
    ),
    _product(
        "E14",
        "test_product_e14_conversation_governed_save",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "knowledge_save.confirmed_exact_span",
            natural_goal="在确认后保存我明确要求记住的内容",
            observable_result="精确用户原文在确认后可恢复地保存",
            counterfactuals=("确认前零写入", "控制语义不写入", "重放不重复写入"),
            baseline_kind=BaselineKind.IMPLEMENTATION_FAILURE,
            baseline_ref="B01/B02 -> E14 archived failure chain",
        ),
        covered_invariants=frozenset({
            "knowledge_save.confirmed",
            "knowledge_save.replay",
        }),
    ),
    _product(
        "E22",
        "test_product_e22_governed_delete_from_goal_entry",
        EvidenceLayer.UNDERSTANDING,
        EvidenceLayer.AUTHORITY_GATEWAY,
        EvidenceLayer.JOURNAL_RECOVERY,
        EvidenceLayer.VERIFICATION_COMPLETION,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "knowledge_delete.natural_confirmed",
            natural_goal="用自然语言定位并删除我保存的一条知识",
            observable_result="确认后目标知识被删除且重放返回同一结果",
            counterfactuals=("确认前目标仍存在", "不泄漏其他用户知识", "不重复副作用"),
            baseline_kind=BaselineKind.IMPLEMENTATION_FAILURE,
            baseline_ref="archive:20260803T142932.564456Z-23720-19ba8517",
        ),
        covered_invariants=frozenset({"knowledge_delete.confirmed"}),
    ),
    _loop(
        "L01",
        "test_l01_http_natural_recall_uses_observed_personal_knowledge",
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "personal_knowledge.natural_recall",
            natural_goal="回忆我之前保存的一条个人知识",
            observable_result="回答包含当前用户保存的精确随机事实",
            counterfactuals=("不泄漏其他用户事实", "不在无证据时声称找到"),
            baseline_kind=BaselineKind.IMPLEMENTATION_FAILURE,
            baseline_ref="archive:20260803T142413.474927Z-4864-39fedcf5",
        ),
        covered_invariants=frozenset({"personal_knowledge.recall"}),
    ),
    _loop(
        "L07",
        "test_l07_http_conversation_save_is_recalled_in_a_new_conversation",
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "personal_knowledge.save_then_cross_conversation_recall",
            natural_goal="确认保存后在新会话回忆同一事实",
            observable_result="新会话准确返回已确认保存的随机事实",
            counterfactuals=("确认前不写入",),
            baseline_ref="behavior-baseline:L07",
        ),
        covered_invariants=frozenset({
            "knowledge_save.confirmed",
            "personal_knowledge.cross_conversation_recall",
        }),
    ),
    _loop("L02", "test_l02_http_independent_reads_use_safe_concurrency"),
    _loop(
        "L03",
        "test_l03_http_process_restart_rebuilds_from_committed_facts",
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "conversation.recover_committed_read",
            natural_goal="服务中断后仍完成同一知识查询",
            observable_result="恢复后回答包含正确保存事实",
            counterfactuals=("已提交读取不重复", "不泄漏其他用户事实"),
            baseline_ref="behavior-baseline:L03",
        ),
    ),
    _loop(
        "L04",
        "test_l04_http_manager_synthesizes_bounded_specialist_artifact",
        capability_profile=CapabilityProfile.GPT_RESEARCHER_A2A,
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "deep_research.bounded_specialist_synthesis",
            natural_goal="深入研究并综合四个安全边界及来源",
            observable_result="最终答复覆盖要求的四个方面并提供来源依据",
            counterfactuals=("不暴露内部 artifact 控制文本", "不只返回简短概述"),
            baseline_ref="behavior-baseline:L04",
        ),
        covered_invariants=frozenset({"a2a.deep_research"}),
    ),
    _loop("L05", "test_l05_http_budget_exhaustion_fails_closed"),
    _loop(
        "L06", "test_l06_http_user_requested_review_returns_receipt_bound_safe_revision",
        evidence_class=EvidenceClass.PRODUCT_E2E,
        user_outcome_contract=_outcome(
            "answer_review.safe_revision",
            natural_goal="审查并修订一段缺少执行证据的答复",
            observable_result="只返回不再虚假声称已写入的安全文本",
            counterfactuals=("不发送未通过审查的草稿",),
            baseline_kind=BaselineKind.IMPLEMENTATION_FAILURE,
            baseline_ref="paired-eval:L06 5/9 -> 9/9",
        ),
    ),
    EvidenceCase(
        evidence_id="CTX-001.baseline",
        case_id="CTX-001",
        module="test_conversation_context_growth.py",
        test_name="test_long_conversation_retains_correction_and_early_document_evidence",
        layers=frozenset(
            {
                EvidenceLayer.UNDERSTANDING,
                EvidenceLayer.PLANNING_CONTROL,
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.VERIFICATION_COMPLETION,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.RUNTIME_CONFORMANCE,
        test_doubles=frozenset({"frozen_external_document_provider"}),
        limitation=(
            "The real model and production HTTP/MCP/Gateway/Conversation path are used; "
            "only the external read-only documents are frozen for repeatable facts and size."
        ),
    ),
    EvidenceCase(
        evidence_id="GOV-001.baseline",
        case_id="GOV-001",
        module="test_governance_and_budget.py",
        test_name="test_gov_001_external_content_cannot_reach_a_hidden_interaction_tool",
        layers=frozenset(
            {
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.VERIFICATION_COMPLETION,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.RUNTIME_CONFORMANCE,
        test_doubles=frozenset({"frozen_external_document_provider"}),
        limitation=(
            "The real model and production HTTP/MCP/Admission/Gateway path are used; "
            "only the untrusted external document is frozen and its provider records calls."
        ),
    ),
    EvidenceCase(
        evidence_id="RUN-001.baseline",
        case_id="RUN-001",
        module="test_governance_and_budget.py",
        test_name="test_run_001_batch_never_executes_past_the_tool_call_budget",
        layers=frozenset(
            {
                EvidenceLayer.PLANNING_CONTROL,
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.VERIFICATION_COMPLETION,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.RUNTIME_CONFORMANCE,
        test_doubles=frozenset({"frozen_external_record_provider"}),
        limitation=(
            "The real model and production HTTP/MCP/Conversation budget path are used; "
            "only the external records are frozen and their provider records calls."
        ),
    ),
    EvidenceCase(
        evidence_id="DUR-001.baseline",
        case_id="DUR-001",
        module="test_durable_scope_and_diagnosis.py",
        test_name="test_dur_001_durable_interaction_scope_survives_process_restart",
        layers=frozenset(
            {
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.JOURNAL_RECOVERY,
                EvidenceLayer.VERIFICATION_COMPLETION,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.RUNTIME_CONFORMANCE,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
    ),
    EvidenceCase(
        evidence_id="OBS-001.baseline",
        case_id="OBS-001",
        module="test_durable_scope_and_diagnosis.py",
        test_name="test_obs_001_scope_failure_is_diagnosable_from_the_same_run_ref",
        layers=frozenset(
            {
                EvidenceLayer.AUTHORITY_GATEWAY,
                EvidenceLayer.JOURNAL_RECOVERY,
            }
        ),
        entry_boundary=EntryBoundary.HTTP_PROCESS,
        evidence_class=EvidenceClass.RUNTIME_CONFORMANCE,
        fault_mechanism=FaultMechanism.PROCESS_TERMINATION,
        limitation=(
            "Operator diagnosis evidence for the same natural authorization failure; "
            "it does not itself claim improved answer quality."
        ),
    ),
    _profile(
        "E16",
        "test_e16_http_process_reads_github_through_real_mcp_gateway",
        CapabilityProfile.GITHUB_MCP,
    ),
    _profile(
        "E18",
        "test_e18_http_process_reads_notion_through_real_mcp_gateway",
        CapabilityProfile.NOTION_MCP,
    ),
    _profile(
        "E19",
        "test_e19_http_process_mcp_capability_unavailable_fails_closed",
        CapabilityProfile.BASELINE,
    ),
    _profile(
        "E21",
        "test_e21_http_process_answers_from_oversized_read_within_budget",
        CapabilityProfile.GITHUB_MCP,
    ),
)

EVIDENCE_BY_NODE = {case.node_key: case for case in EVIDENCE_CASES}


def validate_catalog() -> None:
    evidence_ids = [case.evidence_id for case in EVIDENCE_CASES]
    node_keys = [case.node_key for case in EVIDENCE_CASES]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence_id in E2E evidence catalog")
    if len(node_keys) != len(set(node_keys)):
        raise ValueError(
            "one E2E test node cannot own multiple evidence classifications"
        )
    expected = {
        EvidenceClass.PRODUCT_E2E: {
            "E14",
            "E22",
            "ASK-001A",
            "ASK-001B",
            "L01",
            "L03",
            "L04",
            "L06",
            "L07",
        },
        EvidenceClass.APPLICATION_E2E: {
            "E01", "E04", "E05", "E09", "E10", "E11", "E12", "E13",
        },
        EvidenceClass.RUNTIME_CONFORMANCE: {
            "L02", "L05",
            "CTX-001",
            "RUN-001",
            "GOV-001", "DUR-001", "OBS-001",
        },
        EvidenceClass.CAPABILITY_PROFILE: {"E16", "E18", "E19", "E21"},
        EvidenceClass.BOUNDARY_EVALUATION: set(),
    }
    for evidence_class, case_ids in expected.items():
        actual = {
            case.case_id
            for case in EVIDENCE_CASES
            if case.evidence_class is evidence_class
        }
        if actual != case_ids:
            raise ValueError(
                f"{evidence_class.value} catalog coverage mismatch: "
                f"{sorted(actual ^ case_ids)}"
            )
    outcome_ids = [
        case.user_outcome_contract.outcome_id
        for case in EVIDENCE_CASES
        if case.user_outcome_contract is not None
    ]
    if len(outcome_ids) != len(set(outcome_ids)):
        raise ValueError("one canonical product outcome cannot have multiple owners")


validate_catalog()


__all__ = [
    "CapabilityProfile",
    "BaselineKind",
    "EVIDENCE_BY_NODE",
    "EVIDENCE_CASES",
    "EntryBoundary",
    "EvidenceCase",
    "EvidenceClass",
    "EvidenceLayer",
    "FaultMechanism",
    "UserOutcomeContract",
    "validate_catalog",
]

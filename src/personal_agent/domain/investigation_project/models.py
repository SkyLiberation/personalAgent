"""Canonical contracts for the Durable Investigation Project domain."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope, SecurityScope


ProjectState = Literal[
    "planning",
    "active",
    "paused",
    "cancelling",
    "completing",
    "completed",
    "failed",
    "cancelled",
]
RequirementStatus = Literal["active", "waived"]
RequirementRelevance = Literal["required", "supporting"]
WaitingReasonCode = Literal[
    "approval_required",
    "user_input_required",
    "capability_missing",
    "provider_unavailable",
    "budget_exhausted",
    "dependency_pending",
    "outcome_unknown",
    "verification_repair",
]
FailureDisposition = Literal[
    "transient_retryable",
    "user_recoverable",
    "provider_recoverable",
    "replan_recoverable",
    "terminal",
]
BudgetCategory = Literal[
    "planning",
    "execution_proposal",
    "semantic_verification",
    "synthesis",
    "external_delegation",
]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_project_id() -> str:
    return f"iprj_{uuid4().hex[:20]}"


def new_event_id() -> str:
    return f"ipevt_{uuid4().hex[:20]}"


def new_proposal_id() -> str:
    return f"ipprop_{uuid4().hex[:20]}"


def canonical_digest(value: BaseModel | dict[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProjectBudgetLimit(DomainModel):
    total_tokens: int = Field(default=80_000, ge=0)
    total_cost: float = Field(default=20.0, ge=0)
    max_tool_calls: int = Field(default=40, ge=0)
    max_agent_calls: int = Field(default=8, ge=0)
    max_plan_revisions: int = Field(default=4, ge=0)
    max_evidence_repair_revisions: int = Field(default=8, ge=0)
    same_feedback_revision_limit: int = Field(default=1, ge=0)
    planning_tokens: int = Field(default=12_000, ge=0)
    execution_proposal_tokens: int = Field(default=12_000, ge=0)
    semantic_verification_tokens: int = Field(default=16_000, ge=0)
    synthesis_tokens: int = Field(default=20_000, ge=0)
    external_delegation_tokens: int = Field(default=20_000, ge=0)

    def category_token_limit(self, category: BudgetCategory) -> int:
        return {
            "planning": self.planning_tokens,
            "execution_proposal": self.execution_proposal_tokens,
            "semantic_verification": self.semantic_verification_tokens,
            "synthesis": self.synthesis_tokens,
            "external_delegation": self.external_delegation_tokens,
        }[category]


class UserRequirement(DomainModel):
    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    acceptance_contract: str = Field(min_length=1)
    status: RequirementStatus = "active"


class UserRequirementVersion(DomainModel):
    version: int = Field(ge=1)
    requirements: tuple[UserRequirement, ...]
    steering_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DerivedRequirement(DomainModel):
    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    acceptance_contract: str = Field(min_length=1)
    completion_relevance: RequirementRelevance = "required"


class CapabilityContract(DomainModel):
    contract_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    semantic_domain: str = Field(default="", max_length=200)
    resource_type: str = Field(default="", max_length=200)
    allowed_execution_kinds: tuple[Literal["tool", "agent", "synthesis", "user_input"], ...]


class PlanAssumption(DomainModel):
    assumption_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    affected_logical_subgoal_ids: tuple[str, ...] = ()


class SubGoalVersionRef(DomainModel):
    logical_subgoal_id: str = Field(min_length=1)
    subgoal_version: int = Field(ge=1)


class SubGoalDefinitionVersion(DomainModel):
    logical_subgoal_id: str = Field(min_length=1)
    subgoal_version: int = Field(ge=1)
    definition_digest: str = Field(min_length=16)
    supersedes_version: int | None = Field(default=None, ge=1)
    objective: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    required_output: str = Field(min_length=1)
    capability_contract: CapabilityContract
    repairs_frozen_subgoals: tuple[SubGoalVersionRef, ...] = ()


class RequirementMapping(DomainModel):
    requirement_id: str = Field(min_length=1)
    logical_subgoal_ids: tuple[str, ...] = Field(min_length=1)


class PlanProposal(DomainModel):
    project_id: str = Field(min_length=1)
    based_on_event_sequence: int = Field(ge=0)
    capability_snapshot_revision: str = Field(min_length=1)
    revision_reason: str = Field(min_length=1)
    assumptions: tuple[PlanAssumption, ...] = ()
    derived_requirements: tuple[DerivedRequirement, ...] = ()
    subgoals: tuple[SubGoalDefinitionVersion, ...] = Field(min_length=1)
    requirement_mappings: tuple[RequirementMapping, ...] = Field(min_length=1)


class AcceptedPlanVersion(DomainModel):
    plan_version: int = Field(ge=1)
    proposal: PlanProposal
    plan_digest: str = Field(min_length=16)
    accepted_at: datetime = Field(default_factory=utc_now)


class ToolExecutionOperation(DomainModel):
    kind: Literal["tool"] = "tool"
    tool_name: str = Field(min_length=1)
    typed_arguments: dict[str, Any]
    expected_artifact_type: str = Field(min_length=1)


class AgentExecutionOperation(DomainModel):
    kind: Literal["agent"] = "agent"
    agent_id: str = Field(min_length=1)
    bounded_sub_goal: str = Field(min_length=1)
    context_artifact_refs: tuple[ResourceRef, ...] = ()
    expected_artifact_types: tuple[str, ...] = Field(min_length=1)
    token_budget: int = Field(ge=0)
    cost_budget: float = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)


class SynthesisOperation(DomainModel):
    kind: Literal["synthesis"] = "synthesis"
    input_artifact_refs: tuple[ResourceRef, ...] = ()
    requirement_refs: tuple[str, ...] = Field(min_length=1)
    output_contract: str = Field(min_length=1)


class UserInputOperation(DomainModel):
    kind: Literal["user_input"] = "user_input"
    question: str = Field(min_length=1)
    required_fields: tuple[str, ...] = ()


ExecutionOperation = Annotated[
    ToolExecutionOperation | AgentExecutionOperation | SynthesisOperation | UserInputOperation,
    Field(discriminator="kind"),
]


class SubGoalExecutionProposal(DomainModel):
    project_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    logical_subgoal_id: str = Field(min_length=1)
    subgoal_version: int = Field(ge=1)
    based_on_event_sequence: int = Field(ge=0)
    proposal_id: str = Field(default_factory=new_proposal_id)
    operation: ExecutionOperation
    proposal_digest: str = Field(min_length=16)


class ExecutionRef(DomainModel):
    execution_id: str = Field(min_length=1)
    execution_kind: Literal["tool", "agent", "synthesis", "command"]
    owner_ref: str = Field(min_length=1)
    execution_digest: str = Field(min_length=16)


class EvidenceRef(DomainModel):
    evidence_id: str = Field(min_length=1)
    execution_ref: ExecutionRef
    artifact_ref: ResourceRef | None = None
    source: str = Field(min_length=1)
    content_digest: str = Field(min_length=16)
    summary: str = ""


class EvidenceAdmissionDecision(DomainModel):
    admission_id: str = Field(default_factory=lambda: f"ipead_{uuid4().hex[:20]}")
    evidence_ref: EvidenceRef
    admitted: bool
    reason: str = ""
    decided_at: datetime = Field(default_factory=utc_now)


class PlanObservation(DomainModel):
    observation_id: str = Field(default_factory=lambda: f"ipobs_{uuid4().hex[:20]}")
    statement: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    contradicted_assumption_ids: tuple[str, ...] = ()
    affected_logical_subgoal_ids: tuple[str, ...] = ()
    observation_digest: str = Field(min_length=16)


class DecisionFeedback(DomainModel):
    reason: str
    repairable_fields: tuple[str, ...] = ()
    immutable_fields: tuple[str, ...] = ()
    required_repair: str = ""
    revision_scope: tuple[str, ...] = ()
    disposition: str = "semantic_rejection"


class SubGoalVerificationAssessment(DomainModel):
    assessment_id: str = Field(default_factory=lambda: f"ipver_{uuid4().hex[:20]}")
    logical_subgoal_id: str
    subgoal_version: int
    satisfied: bool
    evidence_refs: tuple[str, ...] = ()
    feedback: str = ""
    observations: tuple[PlanObservation, ...] = ()
    assessment_digest: str = Field(min_length=16)


class SubGoalOutcome(DomainModel):
    outcome_id: str = Field(default_factory=lambda: f"ipout_{uuid4().hex[:20]}")
    logical_subgoal_id: str
    subgoal_version: int
    execution_ref: ExecutionRef
    assessment: SubGoalVerificationAssessment
    artifact_refs: tuple[ResourceRef, ...] = ()
    committed_at: datetime = Field(default_factory=utc_now)


class WaitingReason(DomainModel):
    logical_subgoal_id: str
    subgoal_version: int
    reason: WaitingReasonCode
    recovery_authority: Literal["runtime", "planner", "user", "provider"]
    blocking_required_work: bool = True
    detail: str = ""


class ProjectUsage(DomainModel):
    category: BudgetCategory
    reservation_id: str
    tokens: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    agent_calls: int = Field(default=0, ge=0)
    estimated: bool = False


class ReplanRequest(DomainModel):
    request_id: str = Field(default_factory=lambda: f"ipreplan_{uuid4().hex[:20]}")
    trigger_kind: Literal[
        "steering",
        "assumption_conflict",
        "capability_changed",
        "verification_gap",
        "coverage_deadlock",
        "admission_feedback",
    ]
    trigger_ref: str = Field(min_length=1)
    affected_requirement_ids: tuple[str, ...] = ()
    affected_logical_subgoal_ids: tuple[str, ...] = ()
    revision_scope: tuple[str, ...] = ()
    decision_feedback: DecisionFeedback | None = None
    trigger_digest: str = Field(min_length=16)


class SteeringCommand(DomainModel):
    steering_id: str = Field(default_factory=lambda: f"ipsteer_{uuid4().hex[:20]}")
    project_id: str
    expected_plan_version: int = Field(ge=1)
    statement: str = Field(min_length=1)
    waived_requirement_ids: tuple[str, ...] = ()
    added_requirements: tuple[UserRequirement, ...] = ()
    idempotency_key: str = Field(min_length=1)
    steering_digest: str = Field(min_length=16)
    created_at: datetime = Field(default_factory=utc_now)


class DisclosureManifest(DomainModel):
    manifest_id: str = Field(default_factory=lambda: f"ipdisc_{uuid4().hex[:20]}")
    artifact_refs: tuple[ResourceRef, ...]
    allowed_sections: tuple[str, ...] = ()
    redaction_policy: str = "private_excerpt"
    content_digest: str = Field(min_length=16)


class ExternalDelegationCommand(DomainModel):
    command_id: str = Field(default_factory=lambda: f"ipcmd_{uuid4().hex[:20]}")
    security_scope: SecurityScope
    execution_scope: ExecutionScope
    plan_version: int
    logical_subgoal_id: str
    subgoal_version: int
    execution_proposal_digest: str
    target_agent_id: str
    bounded_sub_goal: str
    context_artifact_refs: tuple[ResourceRef, ...]
    disclosure_manifest: DisclosureManifest
    token_budget: int
    cost_budget: float
    time_budget_seconds: int
    authorization_digest: str
    execution_command_digest: str
    approved: bool = False
    supersedes_command_ref: str | None = None


class CompletionReport(DomainModel):
    project_id: str
    plan_version: int
    requirement_assessment_refs: tuple[str, ...]
    final_artifact_ref: ResourceRef
    coverage: dict[str, Literal["verified", "waived", "unmet"]]
    completion_digest: str = Field(min_length=16)
    completed_at: datetime = Field(default_factory=utc_now)


class InvestigationProjectDefinition(DomainModel):
    project_id: str = Field(default_factory=new_project_id)
    principal: AuthenticatedPrincipal
    security_scope: SecurityScope
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    user_requirements: UserRequirementVersion
    budget: ProjectBudgetLimit = Field(default_factory=ProjectBudgetLimit)
    create_idempotency_key: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class PlanAcceptedData(DomainModel):
    kind: Literal["plan_accepted"] = "plan_accepted"
    plan: AcceptedPlanVersion


class StateChangedData(DomainModel):
    kind: Literal["state_changed"] = "state_changed"
    from_state: ProjectState
    to_state: ProjectState
    reason: str


class ExecutionProposalAcceptedData(DomainModel):
    kind: Literal["execution_proposal_accepted"] = "execution_proposal_accepted"
    proposal: SubGoalExecutionProposal


class ExecutionProposalRejectedData(DomainModel):
    kind: Literal["execution_proposal_rejected"] = "execution_proposal_rejected"
    logical_subgoal_id: str = Field(min_length=1)
    subgoal_version: int = Field(ge=1)
    feedback: DecisionFeedback
    rejection_digest: str = Field(min_length=16)


class BudgetReservedData(DomainModel):
    kind: Literal["budget_reserved"] = "budget_reserved"
    usage: ProjectUsage


class BudgetChargedData(DomainModel):
    kind: Literal["budget_charged"] = "budget_charged"
    usage: ProjectUsage


class BudgetReleasedData(DomainModel):
    kind: Literal["budget_released"] = "budget_released"
    reservation_id: str
    category: BudgetCategory


class ExecutionCommittedData(DomainModel):
    kind: Literal["execution_committed"] = "execution_committed"
    logical_subgoal_id: str
    subgoal_version: int
    execution_ref: ExecutionRef


class EvidenceAdmissionCommittedData(DomainModel):
    kind: Literal["evidence_admission_committed"] = "evidence_admission_committed"
    decision: EvidenceAdmissionDecision


class OutcomeCommittedData(DomainModel):
    kind: Literal["outcome_committed"] = "outcome_committed"
    outcome: SubGoalOutcome


class WaitingReasonSetData(DomainModel):
    kind: Literal["waiting_reason_set"] = "waiting_reason_set"
    waiting_reason: WaitingReason


class WaitingReasonClearedData(DomainModel):
    kind: Literal["waiting_reason_cleared"] = "waiting_reason_cleared"
    logical_subgoal_id: str
    subgoal_version: int


class ReplanRequestedData(DomainModel):
    kind: Literal["replan_requested"] = "replan_requested"
    request: ReplanRequest


class UserRequirementsRevisedData(DomainModel):
    kind: Literal["user_requirements_revised"] = "user_requirements_revised"
    steering: SteeringCommand
    requirements: UserRequirementVersion


class CommandPreparedData(DomainModel):
    kind: Literal["command_prepared"] = "command_prepared"
    command: ExternalDelegationCommand


class CommandApprovedData(DomainModel):
    kind: Literal["command_approved"] = "command_approved"
    command_id: str
    authorization_digest: str
    approved_by_principal_id: str


class AgentRunLinkedData(DomainModel):
    kind: Literal["agent_run_linked"] = "agent_run_linked"
    logical_subgoal_id: str
    subgoal_version: int
    agent_run_id: str
    submission_key: str


class ArtifactLinkedData(DomainModel):
    kind: Literal["artifact_linked"] = "artifact_linked"
    artifact_ref: ResourceRef
    disposition: Literal["active", "partial", "final", "late_quarantined"]
    logical_subgoal_id: str | None = None


class CompletionCommittedData(DomainModel):
    kind: Literal["completion_committed"] = "completion_committed"
    report: CompletionReport


class LateResultQuarantinedData(DomainModel):
    kind: Literal["late_result_quarantined"] = "late_result_quarantined"
    agent_run_id: str
    artifact_refs: tuple[ResourceRef, ...]


ProjectEventData = Annotated[
    PlanAcceptedData
    | StateChangedData
    | ExecutionProposalAcceptedData
    | ExecutionProposalRejectedData
    | BudgetReservedData
    | BudgetChargedData
    | BudgetReleasedData
    | ExecutionCommittedData
    | EvidenceAdmissionCommittedData
    | OutcomeCommittedData
    | WaitingReasonSetData
    | WaitingReasonClearedData
    | ReplanRequestedData
    | UserRequirementsRevisedData
    | CommandPreparedData
    | CommandApprovedData
    | AgentRunLinkedData
    | ArtifactLinkedData
    | CompletionCommittedData
    | LateResultQuarantinedData,
    Field(discriminator="kind"),
]


class ProjectEvent(DomainModel):
    event_id: str = Field(default_factory=new_event_id)
    project_id: str
    sequence: int = Field(ge=1)
    data: ProjectEventData
    created_at: datetime = Field(default_factory=utc_now)


class ProjectView(DomainModel):
    definition: InvestigationProjectDefinition
    state: ProjectState
    last_state_reason: str
    event_sequence: int
    user_requirements: UserRequirementVersion
    accepted_plan: AcceptedPlanVersion | None
    accepted_execution_proposals: tuple[SubGoalExecutionProposal, ...]
    execution_refs: tuple[ExecutionRef, ...]
    admitted_evidence: tuple[EvidenceRef, ...]
    outcomes: tuple[SubGoalOutcome, ...]
    waiting_reasons: tuple[WaitingReason, ...]
    commands: tuple[ExternalDelegationCommand, ...]
    artifact_refs: tuple[ResourceRef, ...]
    completion_report: CompletionReport | None
    plan_revision_count: int
    usage: tuple[ProjectUsage, ...]


__all__ = [
    "AcceptedPlanVersion",
    "AgentExecutionOperation",
    "AgentRunLinkedData",
    "ArtifactLinkedData",
    "BudgetCategory",
    "BudgetChargedData",
    "BudgetReleasedData",
    "BudgetReservedData",
    "CapabilityContract",
    "CommandApprovedData",
    "CommandPreparedData",
    "CompletionCommittedData",
    "CompletionReport",
    "DerivedRequirement",
    "DecisionFeedback",
    "DisclosureManifest",
    "EvidenceAdmissionCommittedData",
    "EvidenceAdmissionDecision",
    "EvidenceRef",
    "ExecutionCommittedData",
    "ExecutionOperation",
    "ExecutionProposalAcceptedData",
    "ExecutionProposalRejectedData",
    "ExecutionRef",
    "ExternalDelegationCommand",
    "FailureDisposition",
    "InvestigationProjectDefinition",
    "LateResultQuarantinedData",
    "OutcomeCommittedData",
    "PlanAcceptedData",
    "PlanAssumption",
    "PlanObservation",
    "PlanProposal",
    "ProjectBudgetLimit",
    "ProjectEvent",
    "ProjectState",
    "ProjectUsage",
    "ProjectView",
    "ReplanRequest",
    "ReplanRequestedData",
    "RequirementMapping",
    "StateChangedData",
    "SteeringCommand",
    "SubGoalDefinitionVersion",
    "SubGoalExecutionProposal",
    "SubGoalOutcome",
    "SubGoalVersionRef",
    "SubGoalVerificationAssessment",
    "SynthesisOperation",
    "ToolExecutionOperation",
    "UserInputOperation",
    "UserRequirement",
    "UserRequirementVersion",
    "UserRequirementsRevisedData",
    "WaitingReason",
    "WaitingReasonClearedData",
    "WaitingReasonSetData",
    "canonical_digest",
    "new_event_id",
    "new_project_id",
    "new_proposal_id",
    "utc_now",
]

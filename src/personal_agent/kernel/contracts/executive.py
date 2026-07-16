"""Provider-neutral contracts for the task-level executive control loop."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.contracts.capability import CapabilityRequirement
from personal_agent.kernel.contracts.procedure import (
    ProcedureCandidate,
    ProcedureInvocation,
    ProcedureRef,
)


def _short_id() -> str:
    return uuid4().hex[:12]


class DecisionBasis(BaseModel):
    unmet_criterion_ids: tuple[str, ...] = ()
    triggering_observation_ids: tuple[str, ...] = ()
    evidence_gap_ids: tuple[str, ...] = ()
    expected_state_change: str = ""
    rejected_action_codes: tuple[str, ...] = ()


class ResourceAccess(BaseModel):
    semantic_domain: str
    locator: str | None = None


class ProposedResourceAccessPlan(BaseModel):
    read_set: tuple[ResourceAccess, ...] = ()
    write_set: tuple[ResourceAccess, ...] = ()
    side_effect_class: str = "none"


class ResolvedResourceAccessPlan(ProposedResourceAccessPlan):
    source_refs: tuple[str, ...] = ()
    resolution_evidence: tuple[str, ...] = ()
    complete: bool = True


class BoundedAction(BaseModel):
    action_id: str = Field(default_factory=_short_id)
    goal_id: str
    meta_capability: Literal[
        "acquire", "explore", "reason", "verify", "transform", "delegate",
        "commit", "remember",
    ]
    description: str
    input_artifact_ids: tuple[str, ...] = ()
    output_contract: str = "ToolResult"
    requirement: CapabilityRequirement | None = None
    max_tool_calls: int = Field(default=4, ge=0, le=64)
    max_model_calls: int = Field(default=1, ge=0, le=16)
    max_iterations: int = Field(default=3, ge=1, le=12)
    deadline: datetime | None = None
    proposed_resource_access: ProposedResourceAccessPlan = Field(
        default_factory=ProposedResourceAccessPlan,
    )
    approval_dependencies: tuple[str, ...] = ()
    procedure_dependencies: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)


class SubtaskSpec(BaseModel):
    subtask_id: str = Field(default_factory=_short_id)
    goal: str
    parent_goal_id: str
    context_projection_ids: tuple[str, ...] = ()
    required_capability: CapabilityRequirement
    expected_artifact_contract: str = "AgentArtifact"
    verification_policy: str = "required"
    max_provider_calls: int = Field(default=1, ge=1, le=16)
    requested_capability_ids: tuple[str, ...] = ()
    requested_operations: tuple[str, ...] = ()
    token_budget: int = Field(default=4096, ge=1)
    cost_budget: float = Field(default=1.0, ge=0)
    time_budget_seconds: int = Field(default=120, ge=1)
    deadline: datetime | None = None


class CompletionClaim(BaseModel):
    goal_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    answer_artifact_id: str | None = None
    degraded: bool = False


class DecisionBase(BaseModel):
    target_goal_id: str
    basis: DecisionBasis = Field(default_factory=DecisionBasis)
    expected_progress: str = ""


class ClarifyDecision(DecisionBase):
    action: Literal["clarify"] = "clarify"
    question: str


class ActivateSkillDecision(DecisionBase):
    action: Literal["activate_skill"] = "activate_skill"
    skill_id: str


class ExecuteMetaCapabilityDecision(DecisionBase):
    action: Literal["execute_meta_capability"] = "execute_meta_capability"
    bounded_action: BoundedAction


class DelegateDecision(DecisionBase):
    action: Literal["delegate"] = "delegate"
    subtask: SubtaskSpec


class InvokeProcedureDecision(DecisionBase):
    action: Literal["invoke_procedure"] = "invoke_procedure"
    procedure_invocation: ProcedureInvocation


class RequestConfirmationDecision(DecisionBase):
    action: Literal["request_confirmation"] = "request_confirmation"
    title: str
    summary: str


class FinishDecision(DecisionBase):
    action: Literal["finish"] = "finish"
    completion_claim: CompletionClaim


class StopDecision(DecisionBase):
    action: Literal["stop"] = "stop"
    reason_code: str
    user_message: str


ControlDecision = Annotated[
    ClarifyDecision
    | ActivateSkillDecision
    | ExecuteMetaCapabilityDecision
    | DelegateDecision
    | InvokeProcedureDecision
    | RequestConfirmationDecision
    | FinishDecision
    | StopDecision,
    Field(discriminator="action"),
]


class CapabilityClassSummary(BaseModel):
    kind: str
    semantic_domains: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()


class ObservationRef(BaseModel):
    observation_id: str = Field(default_factory=_short_id)
    goal_id: str | None = None
    kind: str
    provenance: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CapabilityGapObservation(ObservationRef):
    kind: str = "capability_gap"
    requirement_id: str
    status: Literal["partial", "unavailable", "denied"]
    satisfied_operations: tuple[str, ...] = ()
    missing_operations: tuple[str, ...] = ()
    attempted_capability_classes: tuple[str, ...] = ()
    resolvable_by_authorization: bool = False
    resolvable_by_resource_binding: bool = False
    suggested_capability_classes: tuple[str, ...] = ()


class ActionOutcome(BaseModel):
    action_id: str
    goal_id: str
    status: Literal["succeeded", "failed", "blocked", "awaiting_input"]
    output_contract: str = "ToolResult"
    artifact_ids: tuple[str, ...] = ()
    observation: ObservationRef | None = None
    error_code: str | None = None
    retryable: bool = False
    provider_calls: int = 0


class RetryDirective(BaseModel):
    requirement_id: str
    retry_kind: Literal["same_provider", "equivalent_provider", "none"] = "none"
    excluded_provider_ids: tuple[str, ...] = ()
    preserve_contract: bool = True
    idempotency_key: str


class BudgetReservation(BaseModel):
    reservation_id: str = Field(default_factory=_short_id)
    token_budget: int = Field(default=0, ge=0)
    provider_call_budget: int = Field(default=0, ge=0)
    cost_budget: float = Field(default=0, ge=0)
    time_budget_seconds: int = Field(default=0, ge=0)


class ResolvedActionSpec(BaseModel):
    action_spec_id: str = Field(default_factory=_short_id)
    action_id: str
    decision_ref: str
    goal_id: str
    capability_refs: tuple[str, ...] = ()
    context_projection_ref: str
    resource_access_plan: ResolvedResourceAccessPlan
    retry_directive: RetryDirective | None = None
    budget_reservation: BudgetReservation
    verification_contract: str


class Escalation(BaseModel):
    action_id: str
    goal_id: str
    reason_code: str
    summary: str
    attempted_provider_ids: tuple[str, ...] = ()


class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["passed", "failed", "inconclusive"]
    evidence_refs: tuple[str, ...] = ()
    reason_code: str = ""


class VerificationReport(BaseModel):
    subject_id: str
    status: Literal["passed", "failed", "inconclusive"]
    checked_criteria: tuple[CriterionResult, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    gaps: tuple["VerificationGap", ...] = ()


class VerificationGap(BaseModel):
    gap_id: str = Field(default_factory=_short_id)
    gap_code: str
    affected_criteria: tuple[str, ...] = ()
    remediation_classes: tuple[str, ...] = ()
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence_refs: tuple[str, ...] = ()
    verifier_id: str
    verifier_version: str
    decision_basis: str
    calibration_profile: str


class CompletionReport(BaseModel):
    status: Literal["complete", "incomplete", "degraded", "stopped"]
    verified_goal_ids: tuple[str, ...] = ()
    unresolved_goal_ids: tuple[str, ...] = ()
    unmet_criterion_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


class ControlState(BaseModel):
    task_id: str
    task_revision: int
    task_goal: str
    ledger_revision: int
    active_goal_ids: tuple[str, ...] = ()
    active_skill_ids: tuple[str, ...] = ()
    available_capability_classes: tuple[CapabilityClassSummary, ...] = ()
    procedure_candidates: tuple[ProcedureCandidate, ...] = ()
    outstanding_evidence_gaps: tuple[str, ...] = ()
    pending_approval_ids: tuple[str, ...] = ()
    latest_observations: tuple[ObservationRef, ...] = ()
    remaining_provider_calls: int = 0
    remaining_executive_turns: int = 0


__all__ = [
    "ActionOutcome",
    "ActivateSkillDecision",
    "BoundedAction",
    "BudgetReservation",
    "CapabilityClassSummary",
    "CapabilityGapObservation",
    "ClarifyDecision",
    "CompletionClaim",
    "CompletionReport",
    "ControlDecision",
    "ControlState",
    "CriterionResult",
    "DecisionBasis",
    "DelegateDecision",
    "Escalation",
    "ExecuteMetaCapabilityDecision",
    "FinishDecision",
    "InvokeProcedureDecision",
    "ObservationRef",
    "ProposedResourceAccessPlan",
    "ProcedureInvocation",
    "ProcedureRef",
    "RequestConfirmationDecision",
    "ResourceAccess",
    "ResolvedActionSpec",
    "ResolvedResourceAccessPlan",
    "RetryDirective",
    "StopDecision",
    "SubtaskSpec",
    "VerificationReport",
    "VerificationGap",
]

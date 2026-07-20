"""Provider-neutral contracts for the task-level executive control loop."""

from __future__ import annotations

from datetime import datetime
from datetime import UTC, timedelta
from hashlib import sha256
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.execution import CapabilityRequirement
from personal_agent.kernel.contracts.interaction import InteractionDecision, InteractionRequest
from personal_agent.runtime.contracts.planning import DispatchGroup
from personal_agent.capabilities.contracts.procedure import (
    ProcedureCandidate,
    ProcedureInvocation,
    ProcedureRef,
)
from personal_agent.runtime.contracts.task import TaskTerminationReason
from personal_agent.kernel.contracts.derivation import (
    DerivationInvariantResults,
    DerivationRecord,
    canonical_digest,
)


def _short_id() -> str:
    return uuid4().hex[:12]


class ModelGroundingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(default_factory=_short_id)
    source_ref: str = Field(min_length=1)
    source_locator: str | None = None
    transform: Literal["identity", "summarize", "rewrite", "aggregate", "none"] = "none"
    origin: Literal["source_identity", "source_transform", "model_inference"]
    output_field_ref: str = Field(min_length=1)
    source_digest: str = Field(min_length=1)


class SystemProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance_id: str = Field(default_factory=_short_id)
    origin: Literal["deterministic_computation", "policy_derived"]
    derivation_record_ref: str | None = None
    policy_snapshot_ref: str | None = None
    source_refs: tuple[str, ...] = ()
    source_digests: tuple[str, ...] = ()
    output_ref: str
    output_digest: str


class AuthorityEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(default_factory=_short_id)
    authority_kind: Literal["user_confirmed", "provider_observed"]
    confirmation_ref: str | None = None
    observation_ref: str | None = None
    receipt_ref: str | None = None


class AuthorizationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    canonical_target_set: tuple[str, ...] = ()
    user_visible_payload: str = ""
    requested_result_contract: str
    side_effect_envelope: str = "none"
    data_egress_boundary: str = "none"
    trust_boundary: str = "local"
    confirmation_relevant_cost_and_risk: str = ""
    policy_required_provider_identity: str | None = None


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
    side_effect_class: str
    authority_scope: str
    data_egress_class: str
    trust_floor: str
    freshness_contract: str
    evidence_contract: str
    failure_semantics: str


class CapabilityActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["capability"] = "capability"
    task_text: str = Field(min_length=1)
    plan_step_ref: str | None = None
    information_goal: str | None = None
    execution_guidance: tuple[str, ...] = ()
    agentic_synthesis: bool = False


class ProcedureActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["procedure"] = "procedure"
    procedure_id: str = Field(min_length=1)
    procedure_run_id: str = Field(min_length=1)
    procedure_grant_ref: str = Field(min_length=1)


class DelegateActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["delegate"] = "delegate"
    task_text: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    capability_ids: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    token_budget: int = Field(ge=1)
    cost_budget: float = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)


BoundedActionInput = Annotated[
    CapabilityActionInput | ProcedureActionInput | DelegateActionInput,
    Field(discriminator="kind"),
]


class ResolvedResourceAccessPlan(ProposedResourceAccessPlan):
    source_refs: tuple[str, ...] = ()
    resolution_evidence: tuple[str, ...] = ()
    complete: bool = True


class BoundedAction(BaseModel):
    action_id: str = Field(default_factory=_short_id)
    goal_id: str
    execution_intent: Literal[
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
    proposed_resource_access: ProposedResourceAccessPlan
    approval_dependencies: tuple[str, ...] = ()
    procedure_dependencies: tuple[str, ...] = ()
    input: BoundedActionInput


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


class ExecuteBoundedActionDecision(DecisionBase):
    action: Literal["execute_bounded_action"] = "execute_bounded_action"
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


class RequestCapabilityAcquisitionDecision(DecisionBase):
    action: Literal["request_capability_acquisition"] = "request_capability_acquisition"
    requirement: CapabilityRequirement
    allowed_methods: tuple[Literal["suggest", "install", "enable", "connect", "request_auth"], ...] = (
        "suggest",
    )


class FinishDecision(DecisionBase):
    action: Literal["finish"] = "finish"
    completion_claim: CompletionClaim


class TerminateDecision(DecisionBase):
    action: Literal["terminate"] = "terminate"
    reason: TaskTerminationReason = "unrecoverable_failure"
    reason_code: str
    user_message: str


ControlDecision = Annotated[
    ClarifyDecision
    | ExecuteBoundedActionDecision
    | DelegateDecision
    | InvokeProcedureDecision
    | RequestConfirmationDecision
    | RequestCapabilityAcquisitionDecision
    | FinishDecision
    | TerminateDecision,
    Field(discriminator="action"),
]


class CapabilityClassSummary(BaseModel):
    kind: str
    semantic_domains: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()


class ObservationProvenance(BaseModel):
    source_type: Literal["user", "tool", "agent", "model", "runtime", "provider"]
    source_ref: str
    invocation_ref: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str


class ObservationRef(BaseModel):
    observation_id: str = Field(default_factory=_short_id)
    goal_id: str | None = None
    kind: str
    provenance: ObservationProvenance
    trust: Literal["trusted", "scoped", "external", "untrusted"] = "untrusted"
    taint: frozenset[Literal["external_content", "instruction", "sensitive", "derived"]] = frozenset()
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


def observation_provenance(
    source_type: Literal["user", "tool", "agent", "model", "runtime", "provider"],
    source_ref: str,
    content: str,
    *,
    invocation_ref: str | None = None,
) -> ObservationProvenance:
    return ObservationProvenance(
        source_type=source_type,
        source_ref=source_ref,
        invocation_ref=invocation_ref,
        content_hash=sha256(content.encode("utf-8")).hexdigest(),
    )


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
    execution_grant_ref: str | None = None
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


ControlPhase = Literal[
    "preparing_model_call", "proposing", "admitting", "routing",
    "resolving_execution", "preparing_dispatch", "awaiting_result",
    "accepting_result", "monitoring", "awaiting_input", "closed",
]

_CONTROL_PHASE_TRANSITIONS: dict[ControlPhase, frozenset[ControlPhase]] = {
    "preparing_model_call": frozenset({"proposing", "accepting_result", "closed"}),
    "proposing": frozenset({"admitting", "closed"}),
    "admitting": frozenset({
        "routing", "preparing_model_call", "awaiting_input", "closed",
    }),
    "routing": frozenset({
        "resolving_execution", "preparing_model_call", "awaiting_input", "closed",
    }),
    "resolving_execution": frozenset({
        "preparing_dispatch", "preparing_model_call", "accepting_result", "closed",
    }),
    "preparing_dispatch": frozenset({"awaiting_result", "accepting_result", "closed"}),
    "awaiting_result": frozenset({"accepting_result", "resolving_execution", "closed"}),
    "accepting_result": frozenset({
        "monitoring", "resolving_execution", "preparing_model_call", "closed",
    }),
    "monitoring": frozenset({"preparing_model_call", "awaiting_input", "closed"}),
    "awaiting_input": frozenset({"preparing_model_call", "closed"}),
    "closed": frozenset(),
}

RuntimeDisposition = Literal[
    "continue_control", "retry_invocation", "reassess_coordination",
    "patch_plan", "replace_plan", "await_input", "pause", "terminate",
    "propose_completion",
]

ExecutionRoute = Literal["atomic", "delegated", "procedure", "internal_reasoning"]


class RouteProposal(BaseModel):
    action_id: str
    proposed_route: ExecutionRoute
    reason_codes: tuple[str, ...] = ()


class ExecutionRouteDecision(BaseModel):
    action_id: str
    accepted_route: ExecutionRoute
    mandatory_constraints: tuple[str, ...] = ()
    denied_routes: tuple[ExecutionRoute, ...] = ()
    reason_codes: tuple[str, ...] = ()
    policy_revision: str = "v1"


class ControlTurnState(BaseModel):
    """Checkpoint-local state owned by one bounded executive control turn.

    This is deliberately not an event-sourced business aggregate. Task, plan,
    invocation, observation, and interaction facts remain owned by their
    respective contracts; this substate only keeps the resumable control
    cursor and references needed by orchestration.
    """

    turn_id: str = Field(default_factory=_short_id)
    phase: ControlPhase = "preparing_model_call"
    disposition: RuntimeDisposition = "continue_control"
    task_revision: int | None = Field(default=None, ge=1)
    task_event_cursor: int = Field(default=0, ge=0)
    coordination_mode: Literal["reactive", "deliberative"] | None = None
    execution_route_decision: ExecutionRouteDecision | None = None
    state: ControlState | None = None
    proposal: "ControlProposal | None" = None
    accepted_intent: "AcceptedIntent | None" = None
    resolved_command: "ResolvedExecutionCommand | None" = None
    actions: list[BoundedAction] = Field(default_factory=list)
    action_outcome: ActionOutcome | None = None
    resolved_actions: list[ResolvedActionSpec] = Field(default_factory=list)
    dispatch_groups: list[DispatchGroup] = Field(default_factory=list)
    retry_directive: RetryDirective | None = None
    observations: list[ObservationRef] = Field(default_factory=list)
    turn_index: int = 0
    last_intent_semantic_hash: str = ""
    last_submission_hash: str = ""
    seen_decision_cycle_keys: tuple[str, ...] = ()
    active_revision_lineage_id: str | None = None
    active_feedback_ref: str | None = None
    revision_attempt: int = Field(default=0, ge=0)
    cross_stage_revision_cycles: int = Field(default=0, ge=0)
    pending_interaction: InteractionRequest | None = None
    interaction_decision: InteractionDecision | None = None
    confirmed_invocation_id: str | None = None

    def advance_phase(self, next_phase: ControlPhase) -> None:
        if next_phase == self.phase:
            return
        if next_phase not in _CONTROL_PHASE_TRANSITIONS[self.phase]:
            raise ValueError(f"illegal control phase transition: {self.phase} -> {next_phase}")
        self.phase = next_phase


class ControlProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=_short_id)
    base_task_revision: int = Field(ge=1)
    base_runtime_revision: int = Field(ge=0)
    model_invocation_ref: str | None = None
    context_projection_ref: str | None = None
    source: Literal["model", "external_authority", "contract_derivation"] = "model"
    decision: ControlDecision
    grounding_claims: tuple[ModelGroundingClaim, ...] = ()
    supersedes_proposal_ref: str | None = None
    revision_feedback_ref: str | None = None
    revision_attempt: int = Field(default=0, ge=0)

    @property
    def intent_semantic_hash(self) -> str:
        return canonical_digest(self.decision)

    @property
    def submission_hash(self) -> str:
        return canonical_digest({
            "decision": self.decision.model_dump(mode="json"),
            "grounding_claims": [item.model_dump(mode="json") for item in self.grounding_claims],
        })


class AcceptedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_intent_id: str = Field(default_factory=_short_id)
    proposal_ref: str
    admission_ref: str
    task_id: str
    goal_id: str
    task_revision: int = Field(ge=1)
    runtime_revision: int = Field(ge=0)
    decision: ControlDecision
    grounding_claims: tuple[ModelGroundingClaim, ...] = ()
    semantic_digest: str


class ResolvedExecutionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str = Field(default_factory=_short_id)
    accepted_intent_ref: str
    supersedes_command_ref: str | None = None
    route: ExecutionRoute
    procedure_id: str | None = None
    procedure_version: str | None = None
    procedure_invocation: ProcedureInvocation | None = None
    canonical_target_refs: tuple[str, ...] = ()
    narrowed_scope_refs: tuple[str, ...] = ()
    provider_binding_refs: tuple[str, ...] = ()
    provider_binding_derivations: tuple[DerivationRecord, ...] = ()
    read_set: tuple[ResourceAccess, ...] = ()
    write_set: tuple[ResourceAccess, ...] = ()
    authorization_projection: AuthorizationProjection
    authorization_digest: str
    execution_command_digest: str
    derivation_record: DerivationRecord
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))


class FinalAnswerProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=_short_id)
    task_ref: str
    task_revision: int = Field(ge=1)
    verified_goal_refs: tuple[str, ...]
    verification_report_refs: tuple[str, ...]
    answer: str = Field(min_length=1)
    citation_refs: tuple[str, ...] = ()
    degraded_reason_refs: tuple[str, ...] = ()
    supersedes_proposal_ref: str | None = None
    revision_feedback_ref: str | None = None
    revision_attempt: int = Field(default=0, ge=0)


__all__ = [
    "ActionOutcome",
    "AcceptedIntent",
    "AuthorityEvidenceRef",
    "AuthorizationProjection",
    "BoundedAction",
    "BoundedActionInput",
    "BudgetReservation",
    "CapabilityActionInput",
    "CapabilityClassSummary",
    "CapabilityGapObservation",
    "ClarifyDecision",
    "CompletionClaim",
    "ControlDecision",
    "ControlState",
    "ControlPhase",
    "ControlProposal",
    "ControlTurnState",
    "DecisionBasis",
    "DelegateActionInput",
    "DerivationInvariantResults",
    "DerivationRecord",
    "DelegateDecision",
    "Escalation",
    "ExecuteBoundedActionDecision",
    "ExecutionRoute",
    "ExecutionRouteDecision",
    "FinishDecision",
    "FinalAnswerProposal",
    "InvokeProcedureDecision",
    "ObservationRef",
    "ObservationProvenance",
    "observation_provenance",
    "ModelGroundingClaim",
    "ProposedResourceAccessPlan",
    "ProcedureInvocation",
    "ProcedureActionInput",
    "ProcedureRef",
    "RequestConfirmationDecision",
    "RequestCapabilityAcquisitionDecision",
    "ResourceAccess",
    "ResolvedExecutionCommand",
    "ResolvedActionSpec",
    "ResolvedResourceAccessPlan",
    "RetryDirective",
    "RouteProposal",
    "RuntimeDisposition",
    "TaskTerminationReason",
    "TerminateDecision",
    "SubtaskSpec",
    "SystemProvenanceRecord",
    "canonical_digest",
]

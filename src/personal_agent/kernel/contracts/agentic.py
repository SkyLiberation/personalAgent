"""Goal, context, skill, and event-projected ledger contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.capability import CapabilityCoverage
from personal_agent.kernel.contracts.executive import VerificationReport


def _short_id() -> str:
    return uuid4().hex[:12]


TaskResultContract = Literal["response", "artifact", "external_state", "compound"]
ResourceRequirementOrigin = Literal["user_explicit", "model_inferred", "runtime_derived"]
GoalStatus = Literal[
    "pending", "active", "blocked", "awaiting_input", "candidate_complete",
    "verified", "degraded", "abandoned",
]
TaskLifecycle = Literal["active", "awaiting_input", "paused", "completed", "stopped"]
TrustTier = Literal["runtime", "working", "trusted", "evidence", "untrusted"]
CriterionSource = Literal["user_explicit", "contract_derived", "model_derived"]
CriterionMutability = Literal["immutable", "user_revisable", "runtime_derived"]
ConstraintSource = Literal["user", "policy", "procedure", "runtime", "model"]
ConstraintMutability = Literal[
    "immutable", "user_only", "validator_controlled", "model_revisable",
]
GoalDependencyKind = Literal[
    "consumes_output", "requires_completion", "ordering_preference",
]
GoalDependencyOrigin = Literal["user_explicit", "model_inferred", "runtime_derived"]


class ResourceRequirement(BaseModel):
    goal_id: str = ""
    semantic_domain: str
    locator: str | None = None
    resource_types: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    origin: ResourceRequirementOrigin = "model_inferred"
    freshness_required: bool = False
    authority: str | None = None
    preferred_providers: tuple[str, ...] = ()
    required_providers: tuple[str, ...] = ()


class EvidencePolicy(BaseModel):
    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    contradiction_check: bool = False


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str = Field(default_factory=_short_id)
    description: str
    required: bool = True
    source: CriterionSource = "contract_derived"
    mutability: CriterionMutability = "runtime_derived"
    evidence_policy: EvidencePolicy = Field(default_factory=EvidencePolicy)
    acceptance_contract: str = "GoalVerification"


class EvidenceRequirements(BaseModel):
    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    must_cover_all_subgoals: bool = True
    contradiction_check: bool = False


class TaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read_only: bool = True
    max_iterations: int = Field(default=3, ge=1, le=12)
    max_provider_calls: int = Field(default=8, ge=1, le=64)
    max_parallelism: int = Field(default=1, ge=1, le=8)
    max_executive_turns: int = Field(default=12, ge=1, le=64)
    goal_expansion_budget: int = Field(default=8, ge=1, le=32)
    max_derived_goal_depth: int = Field(default=3, ge=1, le=8)
    revision_budget: int = Field(default=4, ge=0, le=16)
    token_budget: int | None = Field(default=None, ge=1)


class MutationIntent(BaseModel):
    operation: str
    requires_confirmation: bool = True
    idempotency_key: str = ""


class TaskSpec(BaseModel):
    task_id: str = Field(default_factory=_short_id)
    schema_version: Literal[2] = 2
    revision: int = Field(default=1, ge=1)
    lifecycle: TaskLifecycle = "active"
    user_goal: str
    result_contract: TaskResultContract
    subjects: tuple[str, ...] = ()
    resource_requirements: tuple[ResourceRequirement, ...] = ()
    requested_operations: tuple[str, ...] = ()
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    success_criteria: tuple[SuccessCriterion, ...] = ()
    evidence_requirements: EvidenceRequirements = Field(default_factory=EvidenceRequirements)
    mutation_intent: MutationIntent | None = None
    clarification_needed: bool = False


class GoalConstraint(BaseModel):
    constraint_id: str = Field(default_factory=_short_id)
    description: str
    source: ConstraintSource
    mutability: ConstraintMutability


class ContextItem(BaseModel):
    ref_id: str
    kind: str
    provenance: str
    trust_tier: TrustTier
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    admitted: bool = False


class ContextEnvelope(BaseModel):
    run_context: tuple[ContextItem, ...] = ()
    working_memory: tuple[ContextItem, ...] = ()
    trusted_memory: tuple[ContextItem, ...] = ()
    evidence_context: tuple[ContextItem, ...] = ()
    untrusted_observations: tuple[ContextItem, ...] = ()
    active_skill_ids: tuple[str, ...] = ()


class BudgetAllocation(BaseModel):
    minimum: int = Field(default=0, ge=0)
    target: int = Field(default=0, ge=0)
    maximum: int = Field(default=0, ge=0)
    priority: int = Field(default=0, ge=0)
    spillover_allowed: bool = True


class ContextBudget(BaseModel):
    model_profile: str
    tokenizer_profile: str
    max_context_tokens: int = Field(ge=1)
    safety_margin: int = Field(default=512, ge=0)
    reserved_output_tokens: int = Field(default=1024, ge=1)
    allocations: dict[str, BudgetAllocation] = Field(default_factory=dict)


class ContextProjection(BaseModel):
    projection_id: str = Field(default_factory=_short_id)
    purpose: Literal[
        "task_analysis", "planning", "executive_decision", "action_execution", "bounded_react",
        "plan_monitoring", "semantic_verification", "subagent_delegation", "final_composition",
    ]
    item_refs: tuple[str, ...] = ()
    omitted_refs: tuple[str, ...] = ()
    token_estimate: int = Field(default=0, ge=0)
    compaction_refs: tuple[str, ...] = ()
    selection_reasons: dict[str, str] = Field(default_factory=dict)
    redacted_refs: tuple[str, ...] = ()
    ledger_revision: int = Field(ge=0)
    event_cursor: str = ""
    artifact_versions: dict[str, str] = Field(default_factory=dict)
    projection_policy_version: str = "v1"
    model_profile: str
    tokenizer_profile: str


class AttemptRef(BaseModel):
    attempt_id: str = Field(default_factory=_short_id)
    action_id: str
    meta_capability: str
    status: str
    artifact_ids: tuple[str, ...] = ()


class GoalDependency(BaseModel):
    """A typed predecessor relation attached to its successor goal."""

    dependency_goal_id: str
    kind: GoalDependencyKind
    origin: GoalDependencyOrigin
    rationale: str

    @property
    def blocks_execution(self) -> bool:
        return self.kind in {"consumes_output", "requires_completion"}

    @property
    def is_mutable(self) -> bool:
        return self.origin != "user_explicit"


class ExecutionLedgerItem(BaseModel):
    goal_id: str
    parent_goal_id: str | None = None
    dependencies: tuple[GoalDependency, ...] = ()
    description: str
    result_contract: Literal["response", "artifact", "external_state"] = "response"
    origin: Literal["user_explicit", "user_implicit", "runtime_derived"] = "user_explicit"
    decomposition_depth: int = Field(default=0, ge=0)
    status: GoalStatus = "pending"
    success_criterion_ids: tuple[str, ...] = ()
    input_artifacts: tuple[str, ...] = ()
    output_contract: str = "ToolResult"
    evidence_gaps: tuple[str, ...] = ()
    coverage: tuple[CapabilityCoverage, ...] = ()
    attempts: tuple[AttemptRef, ...] = ()
    replan_reason: str | None = None
    verification: VerificationReport | None = None


class ExecutionLedger(BaseModel):
    ledger_id: str = Field(default_factory=_short_id)
    task_id: str
    revision: int = 1
    goal_graph_revision: int = 1
    items: tuple[ExecutionLedgerItem, ...] = ()
    active_goal_ids: tuple[str, ...] = ()
    active_skill_ids: tuple[str, ...] = ()
    last_event_sequence: int = 0


class ExecutionEvent(BaseModel):
    event_id: str = Field(default_factory=_short_id)
    sequence: int = Field(ge=1)
    task_id: str
    event_type: Literal[
        "task_created", "goal_added", "goal_activated", "goal_blocked",
        "goal_candidate_complete", "goal_verified", "goal_degraded", "goal_abandoned",
        "goal_criterion_added",
        "goal_dependency_added", "goal_dependency_removed", "goal_dependency_updated",
        "skill_activated", "attempt_recorded", "coverage_recorded",
        "verification_recorded", "plan_revised", "completion_rejected", "task_completed",
        "task_stopped",
    ]
    goal_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AttemptRef",
    "BudgetAllocation",
    "ConstraintMutability",
    "ConstraintSource",
    "ContextBudget",
    "ContextEnvelope",
    "ContextItem",
    "ContextProjection",
    "CriterionMutability",
    "CriterionSource",
    "EvidencePolicy",
    "EvidenceRequirements",
    "ExecutionEvent",
    "ExecutionLedger",
    "ExecutionLedgerItem",
    "GoalStatus",
    "GoalDependency",
    "GoalDependencyKind",
    "GoalDependencyOrigin",
    "GoalConstraint",
    "MutationIntent",
    "ResourceRequirementOrigin",
    "TaskResultContract",
    "ResourceRequirement",
    "SuccessCriterion",
    "TaskConstraints",
    "TaskLifecycle",
    "TaskSpec",
]

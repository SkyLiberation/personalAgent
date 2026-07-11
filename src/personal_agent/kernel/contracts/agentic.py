"""Goal, context, skill, and event-projected ledger contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.contracts.capability import CapabilityCoverage
from personal_agent.kernel.contracts.executive import VerificationReport


def _short_id() -> str:
    return uuid4().hex[:12]


OutcomeKind = Literal[
    "answer", "investigation", "knowledge_change", "research", "operation", "compound",
]
GoalStatus = Literal[
    "pending", "active", "blocked", "awaiting_input", "candidate_complete",
    "verified", "degraded", "abandoned",
]
TaskLifecycle = Literal["active", "awaiting_input", "paused", "completed", "stopped"]
TrustTier = Literal["runtime", "working", "trusted", "evidence", "untrusted"]
CriterionOrigin = Literal[
    "user_explicit", "user_implicit", "policy_required", "runtime_derived",
    "skill_recommended", "macro_recommended",
]
CriterionMutability = Literal["immutable", "user_revisable", "runtime_revisable", "derived"]


class ResourceRequirement(BaseModel):
    semantic_domain: str
    locator: str | None = None
    resource_types: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    freshness_required: bool = False
    authority: str | None = None


class EvidencePolicy(BaseModel):
    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    contradiction_check: bool = False


class SuccessCriterion(BaseModel):
    criterion_id: str = Field(default_factory=_short_id)
    description: str
    required: bool = True
    origin: CriterionOrigin = "runtime_derived"
    mutability: CriterionMutability = "runtime_revisable"
    evidence_policy: EvidencePolicy = Field(default_factory=EvidencePolicy)
    acceptance_contract: str = "GoalVerification"


class EvidenceRequirements(BaseModel):
    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    must_cover_all_subgoals: bool = True
    contradiction_check: bool = False


class TaskConstraints(BaseModel):
    read_only: bool = True
    max_iterations: int = Field(default=3, ge=1, le=12)
    max_provider_calls: int = Field(default=8, ge=1, le=64)
    max_parallelism: int = Field(default=1, ge=1, le=8)
    max_executive_turns: int = Field(default=12, ge=1, le=64)
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
    outcome_kind: OutcomeKind
    subjects: tuple[str, ...] = ()
    resource_requirements: tuple[ResourceRequirement, ...] = ()
    requested_operations: tuple[str, ...] = ()
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    success_criteria: tuple[SuccessCriterion, ...] = ()
    evidence_requirements: EvidenceRequirements = Field(default_factory=EvidenceRequirements)
    mutation_intent: MutationIntent | None = None
    clarification_needed: bool = False


class SkillApplicability(BaseModel):
    semantic_domains: tuple[str, ...] = ()
    evidence_gap_codes: tuple[str, ...] = ()
    outcome_kinds: tuple[OutcomeKind, ...] = ()


class Skill(BaseModel):
    skill_id: str
    version: str = "v1"
    description: str
    applicability: SkillApplicability = Field(default_factory=SkillApplicability)
    instructions: str = ""
    verifier_profile: str = "default"
    output_contracts: tuple[str, ...] = ()
    capability_preferences: tuple[str, ...] = ()
    eval_contract: str = ""


class PlanMacro(BaseModel):
    macro_id: str
    version: str = "v1"
    description: str
    recommended_goal_kinds: tuple[str, ...] = ()
    verifier_profile: str = "default"
    stop_conditions: tuple[str, ...] = ()


class PlanMacroRef(BaseModel):
    macro_id: str
    version: str
    applied_revision: int


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


class AttemptRef(BaseModel):
    attempt_id: str = Field(default_factory=_short_id)
    action_id: str
    meta_capability: str
    status: str
    artifact_ids: tuple[str, ...] = ()


class ExecutionLedgerItem(BaseModel):
    goal_id: str
    parent_goal_id: str | None = None
    description: str
    goal_kind: str = "answer"
    protocol_id: str | None = None
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
    items: tuple[ExecutionLedgerItem, ...] = ()
    active_goal_ids: tuple[str, ...] = ()
    active_skill_ids: tuple[str, ...] = ()
    applied_macros: tuple[PlanMacroRef, ...] = ()
    last_event_sequence: int = 0


class ExecutionEvent(BaseModel):
    event_id: str = Field(default_factory=_short_id)
    sequence: int = Field(ge=1)
    task_id: str
    event_type: Literal[
        "task_created", "goal_added", "goal_activated", "goal_blocked",
        "goal_candidate_complete", "goal_verified", "goal_degraded", "goal_abandoned",
        "skill_activated", "macro_applied", "attempt_recorded", "coverage_recorded",
        "verification_recorded", "plan_revised", "completion_rejected", "task_completed",
        "task_stopped",
    ]
    goal_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryAdmissionDecision(BaseModel):
    status: Literal["admitted", "requires_confirmation", "denied"]
    reason: str
    target_kind: str


__all__ = [
    "AttemptRef",
    "ContextEnvelope",
    "ContextItem",
    "CriterionMutability",
    "CriterionOrigin",
    "EvidencePolicy",
    "EvidenceRequirements",
    "ExecutionEvent",
    "ExecutionLedger",
    "ExecutionLedgerItem",
    "GoalStatus",
    "MemoryAdmissionDecision",
    "MutationIntent",
    "OutcomeKind",
    "PlanMacro",
    "PlanMacroRef",
    "ResourceRequirement",
    "Skill",
    "SkillApplicability",
    "SuccessCriterion",
    "TaskConstraints",
    "TaskLifecycle",
    "TaskSpec",
]

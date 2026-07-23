"""Goal, context, skill, and event-projected ledger contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.execution import CapabilityCoverage
from personal_agent.kernel.contracts.resource import (
    OperationScope,
    ProviderConstraint,
    ResourceSelector,
)


def _short_id() -> str:
    return uuid4().hex[:12]


TaskResultContract = Literal["response", "artifact", "external_state", "compound"]
ResourceRequirementOrigin = Literal["user_explicit", "model_inferred", "runtime_derived"]
GoalStatus = Literal[
    "pending", "active", "blocked", "awaiting_input", "candidate_complete",
    "verified", "degraded", "abandoned",
]
TaskLifecycle = Literal["active", "awaiting_input", "paused", "completed", "terminated"]
TaskTerminationReason = Literal[
    "user_cancelled", "policy_denied", "budget_exhausted",
    "unrecoverable_failure", "superseded", "administrator_stop",
]
TrustTier = Literal["runtime", "working", "trusted", "evidence", "untrusted"]
ContextCategory = Literal[
    "run", "working_memory", "trusted_memory", "evidence", "observation",
]
ProjectionExclusionReason = Literal["budget", "policy", "redacted", "stale", "untrusted"]
AdmissionState = Literal["candidate", "admitted", "rejected"]
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

TaskId = Annotated[str, Field(min_length=1)]
GoalId = Annotated[str, Field(min_length=1)]
ArtifactId = Annotated[str, Field(min_length=1)]
ActionId = Annotated[str, Field(min_length=1)]
AttemptId = Annotated[str, Field(min_length=1)]
PlanId = Annotated[str, Field(min_length=1)]
PlanStepId = Annotated[str, Field(min_length=1)]
ObservationId = Annotated[str, Field(min_length=1)]
ProcedureRunId = Annotated[str, Field(min_length=1)]


class GoalRef(BaseModel):
    task_id: TaskId
    task_revision: int = Field(ge=1)
    goal_id: GoalId
    goal_graph_revision: int = Field(ge=1)


class ResourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: ResourceSelector
    operation_scope: OperationScope = Field(default_factory=OperationScope)
    provider_constraint: ProviderConstraint = Field(default_factory=ProviderConstraint)
    origin: ResourceRequirementOrigin = "model_inferred"
    authority: str | None = None

    @classmethod
    def from_dimensions(
        cls,
        *,
        semantic_domain: str,
        locator: str | None = None,
        resource_types: tuple[str, ...] = (),
        required_operations: tuple[str, ...] = (),
        origin: ResourceRequirementOrigin = "model_inferred",
        freshness_required: bool = False,
        authority: str | None = None,
        preferred_providers: tuple[str, ...] = (),
        required_providers: tuple[str, ...] = (),
    ) -> "ResourceRequirement":
        return cls(
            selector=ResourceSelector(
                semantic_domains=frozenset((semantic_domain,)),
                resource_types=frozenset(resource_types),
                locator=locator,
            ),
            operation_scope=OperationScope(operations=frozenset(required_operations)),
            provider_constraint=ProviderConstraint(
                required=frozenset(required_providers),
                preferred=preferred_providers,
                freshness_required=freshness_required,
            ),
            origin=origin,
            authority=authority,
        )

    @property
    def semantic_domain(self) -> str:
        return next(iter(sorted(self.selector.semantic_domains)), "")

    @property
    def locator(self) -> str | None:
        return self.selector.locator

    @property
    def resource_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.selector.resource_types))

    @property
    def required_operations(self) -> tuple[str, ...]:
        return tuple(sorted(self.operation_scope.operations))

    @property
    def freshness_required(self) -> bool:
        return self.provider_constraint.freshness_required

    @property
    def preferred_providers(self) -> tuple[str, ...]:
        return self.provider_constraint.preferred

    @property
    def required_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self.provider_constraint.required))


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    contradiction_check: bool = False


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    criterion_id: str = Field(default_factory=_short_id)
    description: str
    required: bool = True
    source: CriterionSource = "contract_derived"
    mutability: CriterionMutability = "runtime_derived"
    evidence_policy: EvidencePolicy = Field(default_factory=EvidencePolicy)
    acceptance_contract: str = "GoalVerification"


class EvidenceRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    must_cover_all_subgoals: bool = True
    contradiction_check: bool = False


class TaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
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
    model_config = ConfigDict(extra="forbid", frozen=True)

    operations: tuple[str, ...]
    requires_confirmation: bool = True
    idempotency_key: str | None = None


class GoalConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    constraint_id: str = Field(default_factory=_short_id)
    description: str
    source: ConstraintSource
    mutability: ConstraintMutability


class ContextItem(BaseModel):
    item_id: str
    category: ContextCategory
    kind: str
    provenance: str
    trust: TrustTier
    taint: frozenset[
        Literal["external_content", "instruction", "sensitive", "derived"]
    ] = frozenset()
    admission: AdmissionState = "candidate"
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str | None = None


class ContextInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, ContextItem] = Field(default_factory=dict)

    def selected(
        self,
        *,
        category: ContextCategory | None = None,
        trust: TrustTier | None = None,
    ) -> tuple[ContextItem, ...]:
        return tuple(
            item for item in self.items.values()
            if (category is None or item.category == category)
            and (trust is None or item.trust == trust)
        )

    def with_items(self, *items: ContextItem) -> "ContextInventory":
        updated = dict(self.items)
        updated.update((item.item_id, item) for item in items)
        return self.model_copy(update={"items": updated})


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


class RuntimeSnapshotRef(BaseModel):
    run_id: str = Field(min_length=1)
    task_id: TaskId | None = None
    task_revision: int | None = Field(default=None, ge=1)
    runtime_revision: int = Field(ge=0)
    event_sequence: int = Field(ge=0)
    artifact_versions: dict[str, str] = Field(default_factory=dict)


class ProjectionExclusion(BaseModel):
    item_id: str = Field(min_length=1)
    reason: ProjectionExclusionReason


class ContextProjection(BaseModel):
    projection_id: str = Field(default_factory=_short_id)
    purpose: Literal[
        "task_analysis", "planning", "executive_decision", "action_execution", "bounded_react",
        "plan_monitoring", "semantic_verification", "subagent_delegation", "final_composition",
    ]
    source_snapshot: RuntimeSnapshotRef
    selected_item_ids: tuple[str, ...] = ()
    omitted: tuple[ProjectionExclusion, ...] = ()
    token_estimate: int = Field(default=0, ge=0)
    compaction_refs: tuple[str, ...] = ()
    selection_reasons: dict[str, str] = Field(default_factory=dict)
    projection_policy_version: str = "v1"
    model_profile: str
    tokenizer_profile: str


class AttemptRef(BaseModel):
    attempt_id: str = Field(default_factory=_short_id)
    action_id: str
    execution_intent: str
    status: str
    artifact_ids: tuple[str, ...] = ()


class GoalDependency(BaseModel):
    """A typed predecessor relation attached to its successor goal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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


class GoalDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: GoalId
    parent_goal_id: str | None = None
    dependencies: tuple[GoalDependency, ...] = ()
    description: str
    result_contract: Literal["response", "artifact", "external_state"] = "response"
    origin: Literal["user_explicit", "user_implicit", "runtime_derived"] = "user_explicit"
    decomposition_depth: int = Field(default=0, ge=0)
    resources: tuple[ResourceRequirement, ...] = ()
    criteria: tuple[SuccessCriterion, ...] = ()
    constraints: tuple[GoalConstraint, ...] = ()
    output_contract: str = "ToolResult"

    @property
    def success_criterion_ids(self) -> tuple[str, ...]:
        return tuple(item.criterion_id for item in self.criteria)


class GoalGraphDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(default=1, ge=1)
    goals: tuple[GoalDefinition, ...]

    def by_id(self) -> dict[str, GoalDefinition]:
        return {goal.goal_id: goal for goal in self.goals}


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: TaskId = Field(default_factory=_short_id)
    schema_version: Literal[3] = 3
    revision: int = Field(default=1, ge=1)
    user_goal: str
    result_contract: TaskResultContract
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    shared_resources: tuple[ResourceRequirement, ...] = ()
    goal_graph: GoalGraphDefinition
    evidence_requirements: EvidenceRequirements = Field(default_factory=EvidenceRequirements)
    mutation_intent: MutationIntent | None = None
    clarification_needed: bool = False

    @property
    def subjects(self) -> tuple[str, ...]:
        return tuple(goal.description for goal in self.goal_graph.goals)

    @property
    def resource_requirements(self) -> tuple[ResourceRequirement, ...]:
        return (*self.shared_resources, *(
            resource
            for goal in self.goal_graph.goals
            for resource in goal.resources
        ))

    def resources_for_goal(self, goal_id: str) -> tuple[ResourceRequirement, ...]:
        """Return the effective resource scope for one known Goal, failing closed."""
        goal = self.goal_graph.by_id().get(goal_id)
        if goal is None:
            raise KeyError(f"unknown goal: {goal_id}")
        return (*self.shared_resources, *goal.resources)

    @property
    def requested_operations(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            operation
            for resource in self.resource_requirements
            for operation in resource.required_operations
        ))

    @property
    def success_criteria(self) -> tuple[SuccessCriterion, ...]:
        return tuple(
            criterion
            for goal in self.goal_graph.goals
            for criterion in goal.criteria
        )


class GoalRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: GoalStatus = "pending"
    input_artifacts: tuple[ArtifactId, ...] = ()
    evidence_gaps: tuple[str, ...] = ()
    coverage: tuple[CapabilityCoverage, ...] = ()
    attempts: tuple[AttemptRef, ...] = ()
    replan_reason: str | None = None
    verification_ref: str | None = None


class TaskRuntimeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: str = Field(default_factory=_short_id)
    task_id: TaskId
    task_revision: int = Field(default=1, ge=1)
    lifecycle: TaskLifecycle = "active"
    termination_reason: TaskTerminationReason | None = None
    revision: int = 1
    goal_graph_revision: int = 1
    goal_states: dict[str, GoalRuntimeState] = Field(default_factory=dict)
    active_skill_ids: tuple[str, ...] = ()
    last_event_sequence: int = 0

    @model_validator(mode="after")
    def _terminal_reason_is_total(self) -> "TaskRuntimeProjection":
        if self.lifecycle == "terminated" and self.termination_reason is None:
            raise ValueError("terminated task requires a typed termination_reason")
        if self.lifecycle != "terminated" and self.termination_reason is not None:
            raise ValueError("termination_reason is valid only for a terminated task")
        return self

    @property
    def active_goal_ids(self) -> tuple[str, ...]:
        return tuple(
            goal_id for goal_id, state in self.goal_states.items()
            if state.status not in {"verified", "degraded", "abandoned"}
        )


class MaterializedGoalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: GoalDefinition
    runtime: GoalRuntimeState

    @property
    def goal_id(self) -> str:
        return self.definition.goal_id

    @property
    def parent_goal_id(self) -> str | None:
        return self.definition.parent_goal_id

    @property
    def dependencies(self) -> tuple[GoalDependency, ...]:
        return self.definition.dependencies

    @property
    def description(self) -> str:
        return self.definition.description

    @property
    def result_contract(self) -> Literal["response", "artifact", "external_state"]:
        return self.definition.result_contract

    @property
    def origin(self) -> Literal["user_explicit", "user_implicit", "runtime_derived"]:
        return self.definition.origin

    @property
    def decomposition_depth(self) -> int:
        return self.definition.decomposition_depth

    @property
    def resources(self) -> tuple[ResourceRequirement, ...]:
        return self.definition.resources

    @property
    def success_criterion_ids(self) -> tuple[str, ...]:
        return self.definition.success_criterion_ids

    @property
    def constraints(self) -> tuple[GoalConstraint, ...]:
        return self.definition.constraints

    @property
    def output_contract(self) -> str:
        return self.definition.output_contract

    @property
    def status(self) -> GoalStatus:
        return self.runtime.status

    @property
    def input_artifacts(self) -> tuple[str, ...]:
        return self.runtime.input_artifacts

    @property
    def evidence_gaps(self) -> tuple[str, ...]:
        return self.runtime.evidence_gaps

    @property
    def coverage(self) -> tuple[CapabilityCoverage, ...]:
        return self.runtime.coverage

    @property
    def attempts(self) -> tuple[AttemptRef, ...]:
        return self.runtime.attempts

    @property
    def replan_reason(self) -> str | None:
        return self.runtime.replan_reason

    @property
    def verification_ref(self) -> str | None:
        return self.runtime.verification_ref


def materialize_goals(
    task: TaskContract,
    runtime: TaskRuntimeProjection,
) -> tuple[MaterializedGoalView, ...]:
    if task.task_id != runtime.task_id:
        raise ValueError("task contract and runtime task_id mismatch")
    if task.revision != runtime.task_revision:
        raise ValueError("task contract and runtime revision mismatch")
    views: list[MaterializedGoalView] = []
    for definition in task.goal_graph.goals:
        state = runtime.goal_states.get(definition.goal_id)
        if state is None:
            raise ValueError(f"missing runtime state for goal {definition.goal_id}")
        views.append(MaterializedGoalView(definition=definition, runtime=state))
    unknown = set(runtime.goal_states).difference(task.goal_graph.by_id())
    if unknown:
        raise ValueError(f"runtime contains unknown goals: {', '.join(sorted(unknown))}")
    return tuple(views)


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
        "accepted_intent_created", "execution_command_resolved",
        "task_paused", "task_resumed", "task_terminated",
    ]
    goal_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AttemptRef",
    "BudgetAllocation",
    "ConstraintMutability",
    "ConstraintSource",
    "ContextBudget",
    "ContextInventory",
    "ContextItem",
    "ContextProjection",
    "ProjectionExclusion",
    "ProjectionExclusionReason",
    "RuntimeSnapshotRef",
    "CriterionMutability",
    "CriterionSource",
    "EvidencePolicy",
    "EvidenceRequirements",
    "ExecutionEvent",
    "ArtifactId",
    "GoalStatus",
    "GoalRef",
    "GoalDefinition",
    "GoalGraphDefinition",
    "GoalId",
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
    "TaskTerminationReason",
    "GoalRuntimeState",
    "MaterializedGoalView",
    "TaskContract",
    "TaskId",
    "TaskRuntimeProjection",
    "materialize_goals",
]

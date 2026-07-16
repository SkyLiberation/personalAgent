"""Provider-neutral contracts for adaptive task planning."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.kernel.contracts.capability import CapabilityRequirement


def _short_id() -> str:
    return uuid4().hex[:12]


PlanningMode = Literal["reactive", "deliberative", "procedural"]
PlannerAuthority = Literal["shadow", "advisory", "bounded_execute", "mutation_execute"]
PlanStepKind = Literal["capability", "delegate", "procedure", "synthesize", "verify"]
PlanStepStatus = Literal[
    "proposed", "ready", "selected", "running", "observed", "satisfied",
    "invalidated", "cancelled",
]
JoinPolicy = Literal["all", "any", "quorum"]
StrategyImpact = Literal[
    "none", "local_retry", "step_invalidated", "branch_invalidated",
    "goal_assumption_invalidated",
]


class PlanningLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_mode_assessor_calls: int = Field(default=1, ge=0)
    max_planner_calls: int = Field(default=4, ge=0)
    max_semantic_monitor_calls: int = Field(default=4, ge=0)
    max_semantic_verifier_calls: int = Field(default=4, ge=0)
    max_plan_patches_per_horizon: int = Field(default=3, ge=0)
    max_horizon_replacements: int = Field(default=2, ge=0)


class PlanningUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode_assessor_calls: int = Field(default=0, ge=0)
    planner_calls: int = Field(default=0, ge=0)
    semantic_monitor_calls: int = Field(default=0, ge=0)
    semantic_verifier_calls: int = Field(default=0, ge=0)
    applied_patches: int = Field(default=0, ge=0)
    horizon_replacements: int = Field(default=0, ge=0)


class PlannerExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    authority: PlannerAuthority
    allowed_step_kinds: tuple[PlanStepKind, ...]
    max_frontier_width: int = Field(default=1, ge=1, le=8)
    allowed_side_effect_classes: tuple[str, ...] = ("none",)
    required_capability_gates: tuple[str, ...] = ()
    limits: PlanningLimits = Field(default_factory=PlanningLimits)


class PlanningFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_revision: int = Field(ge=1)
    goal_graph_revision: int = Field(ge=1)
    active_goal_count: int = Field(ge=0)
    hard_dependency_count: int = Field(ge=0)
    unresolved_user_ambiguity: bool = False
    write_or_external_effect_intent: bool = False
    freshness_requirement_count: int = Field(default=0, ge=0)
    evidence_requirement_count: int = Field(default=0, ge=0)
    mandatory_procedure_ids: tuple[str, ...] = ()
    mandatory_procedure_goal_ids: tuple[str, ...] = ()
    user_explicit_operation_count: int = Field(default=0, ge=0)
    provider_binding_present: bool = False
    enabled_execution_profile: str


class PlanningModeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: PlanningMode
    reason_codes: tuple[str, ...]
    target_goal_ids: tuple[str, ...] = ()
    recommended_horizon: int = Field(default=1, ge=1, le=5)
    uncertainty_summary: str = ""
    required_oversight: str = "none"
    model_version: str = ""
    policy_version: str = "v1"


class PlanningSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_revision: int = Field(ge=1)
    goal_graph_revision: int = Field(ge=1)
    plan_revision: int | None = Field(default=None, ge=1)
    ledger_event_cursor: int = Field(default=0, ge=0)
    artifact_version_refs: dict[str, str] = Field(default_factory=dict)
    capability_registry_revision: str = ""


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=_short_id)
    goal_id: str
    kind: PlanStepKind
    objective: str
    supports_criterion_ids: tuple[str, ...] = ()
    information_goal: str | None = None
    depends_on_step_ids: tuple[str, ...] = ()
    capability_requirement: CapabilityRequirement | None = None
    procedure_id: str | None = None
    success_observation_contract: str
    verification_requirement: str | None = None
    failure_classes: tuple[str, ...] = ()
    replan_policy: Literal["local_retry", "patch", "replace", "request_input", "stop"] = "patch"
    side_effect_intent: str = "none"

    @model_validator(mode="after")
    def _validate_binding(self) -> "PlanStep":
        if self.kind in {"capability", "delegate"} and self.capability_requirement is None:
            raise ValueError(f"{self.kind} plan step requires capability_requirement")
        if self.kind == "procedure" and not self.procedure_id:
            raise ValueError("procedure plan step requires procedure_id")
        if self.kind not in {"capability", "delegate"} and self.capability_requirement is not None:
            raise ValueError("only capability/delegate steps may carry a requirement")
        return self


class PlanDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(default_factory=_short_id)
    task_id: str
    revision: int = Field(default=1, ge=1)
    planning_snapshot: PlanningSnapshot
    planning_horizon: int = Field(default=3, ge=1, le=5)
    strategy_summary: str
    target_goal_ids: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()
    replan_triggers: tuple[str, ...] = ()
    created_from_observation_ids: tuple[str, ...] = ()
    created_from_gap_ids: tuple[str, ...] = ()


class AddPlanStep(BaseModel):
    op: Literal["add_step"] = "add_step"
    step: PlanStep


class ReplacePlanStep(BaseModel):
    op: Literal["replace_step"] = "replace_step"
    step_id: str
    replacement: PlanStep


class RemoveUnstartedPlanStep(BaseModel):
    op: Literal["remove_unstarted_step"] = "remove_unstarted_step"
    step_id: str


class CancelPlanBranch(BaseModel):
    op: Literal["cancel_branch"] = "cancel_branch"
    root_step_id: str


class ClosePlanHorizon(BaseModel):
    op: Literal["close_horizon"] = "close_horizon"


PlanPatchOperation = Annotated[
    AddPlanStep | ReplacePlanStep | RemoveUnstartedPlanStep | CancelPlanBranch
    | ClosePlanHorizon,
    Field(discriminator="op"),
]


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str = Field(default_factory=_short_id)
    plan_id: str
    base_plan_revision: int = Field(ge=1)
    base_task_revision: int = Field(ge=1)
    created_at_ledger_event_cursor: int = Field(default=0, ge=0)
    trigger_observation_ids: tuple[str, ...] = ()
    trigger_gap_ids: tuple[str, ...] = ()
    reason_code: str
    operations: tuple[PlanPatchOperation, ...]
    preserved_criterion_ids: tuple[str, ...] = ()
    expected_improvement: str


class ReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=_short_id)
    source: Literal["executive", "monitor", "verifier", "user_steering", "procedure"]
    task_revision: int = Field(ge=1)
    plan_revision: int | None = Field(default=None, ge=1)
    affected_goal_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    urgency: Literal["low", "normal", "high", "critical"] = "normal"
    reason_code: str
    suggested_direction: str | None = None


class RuntimeGoalCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(default_factory=_short_id)
    description: str
    acceptance_contract: str = "GoalVerification"


class DerivedGoalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    description: str
    result_contract: Literal["response", "artifact"] = "artifact"
    output_contract: str = "ToolResult"
    resource_requirements: tuple[CapabilityRequirement, ...] = ()
    criteria: tuple[RuntimeGoalCriterion, ...] = ()


class GoalDecompositionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=_short_id)
    parent_goal_id: str
    base_task_revision: int = Field(ge=1)
    base_goal_graph_revision: int = Field(ge=1)
    derived_from_observation_ids: tuple[str, ...] = Field(min_length=1)
    objective: str
    children: tuple[DerivedGoalSpec, ...] = Field(min_length=1)


class FrontierDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_step_ids: tuple[str, ...] = Field(min_length=1)
    priority_order: tuple[str, ...] = ()
    requested_join_policy: JoinPolicy = "all"
    rationale: str

    @model_validator(mode="after")
    def _validate_selection(self) -> "FrontierDecision":
        if len(set(self.selected_step_ids)) != len(self.selected_step_ids):
            raise ValueError("frontier selection contains duplicate steps")
        if self.priority_order and set(self.priority_order) != set(self.selected_step_ids):
            raise ValueError("priority_order must contain every selected step exactly once")
        return self


class DispatchGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(default_factory=_short_id)
    action_spec_ids: tuple[str, ...] = Field(min_length=1)
    join_policy: JoinPolicy = "all"
    quorum: int | None = Field(default=None, ge=1)
    failure_policy: Literal["fail_fast", "collect", "continue"] = "collect"
    resolved_resource_snapshot: tuple[str, ...] = ()


class PlanEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=_short_id)
    sequence: int = Field(ge=1)
    plan_id: str
    plan_revision: int = Field(ge=1)
    event_type: Literal[
        "plan_created", "plan_validated", "frontier_selected", "dispatch_grouped",
        "step_running", "step_observed", "step_satisfied", "step_invalidated",
        "step_cancelled", "replan_requested", "plan_patched", "plan_replaced",
        "plan_closed",
    ]
    step_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    payload: dict[str, object] = Field(default_factory=dict)


class PlanRuntimeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    step_statuses: dict[str, PlanStepStatus] = Field(default_factory=dict)
    last_event_sequence: int = 0
    seen_replan_signatures: tuple[str, ...] = ()


class PlanMonitorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact: StrategyImpact
    action: Literal["keep", "local_retry", "patch", "replace", "request_input", "stop"]
    affected_step_ids: tuple[str, ...] = ()
    reason_code: str
    replan_request: ReplanRequest | None = None
    decision_source: Literal["deterministic", "semantic"] = "deterministic"


__all__ = [
    "PlanDefinition", "AddPlanStep", "CancelPlanBranch", "ClosePlanHorizon",
    "DerivedGoalSpec", "DispatchGroup", "FrontierDecision", "GoalDecompositionProposal",
    "JoinPolicy", "PlanEvent", "PlanRuntimeProjection",
    "PlanMonitorDecision", "PlanPatch", "PlanPatchOperation", "PlanStep",
    "PlanStepKind", "PlanStepStatus", "PlannerAuthority", "PlannerExecutionProfile",
    "PlanningLimits", "PlanningUsage", "PlanningFacts", "PlanningMode", "PlanningModeAssessment",
    "PlanningSnapshot", "RemoveUnstartedPlanStep", "ReplacePlanStep", "ReplanRequest",
    "RuntimeGoalCriterion", "StrategyImpact",
]

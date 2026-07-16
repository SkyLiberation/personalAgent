"""Adaptive planning policies and deterministic governance."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from personal_agent.kernel.contracts.agentic import (
    TaskRuntimeProjection,
    TaskContract,
    materialize_goals,
)
from personal_agent.kernel.contracts.capability import CapabilityRequirement
from personal_agent.kernel.contracts.executive import ObservationRef
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS
from personal_agent.kernel.contracts.planning import (
    PlanDefinition,
    AddPlanStep,
    CancelPlanBranch,
    ClosePlanHorizon,
    FrontierDecision,
    PlanEvent,
    PlanRuntimeProjection,
    PlanMonitorDecision,
    PlanPatch,
    PlanStep,
    PlannerExecutionProfile,
    PlanningLimits,
    PlanningUsage,
    PlanningFacts,
    PlanningModeAssessment,
    PlanningSnapshot,
    RemoveUnstartedPlanStep,
    ReplacePlanStep,
    ReplanRequest,
)
from personal_agent.kernel.contracts.procedure import ProcedureCandidate

if TYPE_CHECKING:
    from personal_agent.infra.structured_model import StructuredModelClient

logger = logging.getLogger(__name__)


ADVISORY_READ_ONLY_PROFILE = PlannerExecutionProfile(
    profile_id="read_only_single_agent_v1",
    authority="advisory",
    allowed_step_kinds=("capability", "synthesize", "verify"),
    max_frontier_width=1,
    allowed_side_effect_classes=("none",),
    required_capability_gates=("context", "typed_observation", "plan_cas"),
)

BOUNDED_READ_ONLY_PROFILE = ADVISORY_READ_ONLY_PROFILE.model_copy(update={
    "profile_id": "bounded_read_only_single_agent_v1",
    "authority": "bounded_execute",
})

GOVERNED_MIXED_PROFILE = PlannerExecutionProfile(
    profile_id="governed_mixed_single_agent_v1",
    authority="mutation_execute",
    allowed_step_kinds=("capability", "procedure", "synthesize", "verify"),
    max_frontier_width=1,
    allowed_side_effect_classes=(
        "none", "mutation", "write_longterm", "delete_longterm", "external_network",
    ),
    required_capability_gates=(
        "context", "typed_observation", "plan_cas", "procedure", "mutation_confirmation",
    ),
)


def profile_for_task(
    task: TaskContract,
    procedures: tuple[ProcedureCandidate, ...],
) -> PlannerExecutionProfile:
    if task.mutation_intent is not None or any(
        item.status == "mandatory" and item.side_effect_class != "none"
        for item in procedures
    ):
        return GOVERNED_MIXED_PROFILE
    return BOUNDED_READ_ONLY_PROFILE


class PlanningValidationError(ValueError):
    pass


class PlanningConflictError(PlanningValidationError):
    pass


class _ModelPlanProposal(BaseModel):
    strategy_summary: str
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()
    replan_triggers: tuple[str, ...] = ()


class _ModelModeChoice(BaseModel):
    mode: str
    reason_codes: tuple[str, ...]
    recommended_horizon: int = Field(default=3, ge=1, le=5)
    uncertainty_summary: str = ""


class _SemanticMonitorChoice(BaseModel):
    impact: Literal["none", "local_retry", "step_invalidated", "branch_invalidated"]
    affected_step_ids: tuple[str, ...] = ()
    reason_code: str


class PlanningFactProjector:
    """Projection pattern: derive policy facts without making a strategy choice."""

    def project(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        procedures: tuple[ProcedureCandidate, ...],
        profile: PlannerExecutionProfile,
    ) -> PlanningFacts:
        open_items = tuple(
            item for item in materialize_goals(task, ledger)
            if item.status not in {"verified", "degraded", "abandoned"}
        )
        hard_dependencies = sum(
            dependency.blocks_execution
            for item in open_items
            for dependency in item.dependencies
        )
        scoped_resources = (
            *(
                resource
                for item in open_items
                for resource in task.resources_for_goal(item.goal_id)
            ),
        )
        explicit_operations = {
            operation
            for resource in scoped_resources
            if getattr(resource, "origin", "model_inferred") == "user_explicit"
            for operation in resource.required_operations
        }
        return PlanningFacts(
            task_revision=task.revision,
            goal_graph_revision=ledger.goal_graph_revision,
            active_goal_count=len(open_items),
            hard_dependency_count=hard_dependencies,
            unresolved_user_ambiguity=task.clarification_needed,
            write_or_external_effect_intent=task.mutation_intent is not None,
            freshness_requirement_count=sum(item.freshness_required for item in scoped_resources),
            evidence_requirement_count=sum(
                criterion.evidence_policy.citation_required
                or criterion.evidence_policy.contradiction_check
                for criterion in task.success_criteria
            ),
            mandatory_procedure_ids=tuple(dict.fromkeys(
                item.procedure_id for item in procedures if item.status == "mandatory"
            )),
            mandatory_procedure_goal_ids=tuple(dict.fromkeys(
                item.goal_id for item in procedures if item.status == "mandatory"
            )),
            user_explicit_operation_count=len(explicit_operations),
            provider_binding_present=any(item.required_providers for item in scoped_resources),
            enabled_execution_profile=profile.profile_id,
        )


class PlanningModePolicy:
    """Strategy selector with deterministic admissions and an optional model assessor."""

    def __init__(self, model_client: "StructuredModelClient | None" = None) -> None:
        self._model_client = model_client

    def assess(
        self,
        facts: PlanningFacts,
        *,
        target_goal_ids: tuple[str, ...],
        limits: PlanningLimits,
        usage: PlanningUsage,
    ) -> tuple[PlanningModeAssessment, PlanningUsage]:
        if (
            facts.mandatory_procedure_goal_ids
            and len(facts.mandatory_procedure_goal_ids) == facts.active_goal_count
        ):
            return PlanningModeAssessment(
                mode="procedural",
                reason_codes=("mandatory_procedure",),
                target_goal_ids=target_goal_ids,
            ), usage
        if facts.active_goal_count > 1 or facts.hard_dependency_count > 0:
            return PlanningModeAssessment(
                mode="deliberative",
                reason_codes=("compound_goal_graph",),
                target_goal_ids=target_goal_ids,
                recommended_horizon=min(max(facts.active_goal_count, 2), 5),
            ), usage
        if (
            facts.active_goal_count == 1
            and facts.user_explicit_operation_count == 1
            and not facts.write_or_external_effect_intent
            and not facts.unresolved_user_ambiguity
        ):
            return PlanningModeAssessment(
                mode="reactive",
                reason_codes=("single_explicit_atomic_operation",),
                target_goal_ids=target_goal_ids,
            ), usage
        assessed = self._assess_with_model(facts, target_goal_ids, limits, usage)
        if assessed is not None:
            return assessed, usage.model_copy(update={
                "mode_assessor_calls": usage.mode_assessor_calls + 1,
            })
        return PlanningModeAssessment(
            mode="deliberative",
            reason_codes=("strategy_ambiguous_model_unavailable",),
            target_goal_ids=target_goal_ids,
            uncertainty_summary="No safe deterministic admission applies.",
        ), usage

    def _assess_with_model(
        self,
        facts: PlanningFacts,
        target_goal_ids: tuple[str, ...],
        limits: PlanningLimits,
        usage: PlanningUsage,
    ) -> PlanningModeAssessment | None:
        if (
            self._model_client is None
            or usage.mode_assessor_calls >= limits.max_mode_assessor_calls
        ):
            return None
        try:
            from personal_agent.infra.structured_model import StructuredModelRequest

            response = self._model_client.generate(StructuredModelRequest(
                operation="planning_mode_assessment",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Choose reactive only when one bounded next action can safely close the goal. "
                            "Choose deliberative when strategy, evidence routes, or dependencies require a short plan. "
                            "Do not choose tools, providers, delegation, or execution topology."
                        ),
                    },
                    {"role": "user", "content": facts.model_dump_json()},
                ],
                output_type=_ModelModeChoice,
                temperature=0,
                max_tokens=220,
            ))
            choice = response.value
            if choice.mode not in {"reactive", "deliberative"}:
                return None
            return PlanningModeAssessment(
                mode=choice.mode,
                reason_codes=choice.reason_codes,
                target_goal_ids=target_goal_ids,
                recommended_horizon=choice.recommended_horizon,
                uncertainty_summary=choice.uncertainty_summary,
                model_version=response.model,
            )
        except Exception:
            logger.exception("Planning mode assessment failed")
            return None


class PlanValidator:
    """Specification over plan safety, references, DAG shape, and profile authority."""

    def validate(
        self,
        plan: PlanDefinition,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        profile: PlannerExecutionProfile,
    ) -> None:
        if plan.task_id != task.task_id:
            raise PlanningValidationError("plan task does not match TaskContract")
        if plan.planning_snapshot.task_revision != task.revision:
            raise PlanningConflictError("plan was created from a stale task revision")
        if plan.planning_snapshot.goal_graph_revision != ledger.goal_graph_revision:
            raise PlanningConflictError("plan was created from a stale goal graph revision")
        if not plan.steps:
            raise PlanningValidationError("deliberative plan requires at least one step")
        if len(plan.steps) > plan.planning_horizon:
            raise PlanningValidationError("plan exceeds its short planning horizon")
        goal_ids = {item.goal_id for item in materialize_goals(task, ledger)}
        criterion_ids = {item.criterion_id for item in task.success_criteria}
        step_ids = {item.step_id for item in plan.steps}
        if len(step_ids) != len(plan.steps):
            raise PlanningValidationError("plan step IDs must be unique")
        graph: dict[str, set[str]] = {}
        for step in plan.steps:
            if step.goal_id not in goal_ids:
                raise PlanningValidationError("plan step targets an unknown goal")
            if step.kind not in profile.allowed_step_kinds:
                raise PlanningValidationError(
                    f"step kind {step.kind} is not enabled by profile {profile.profile_id}"
                )
            if step.side_effect_intent not in profile.allowed_side_effect_classes:
                raise PlanningValidationError("plan step exceeds profile side-effect authority")
            if not set(step.supports_criterion_ids).issubset(criterion_ids):
                raise PlanningValidationError("plan step references an unknown criterion")
            unknown_dependencies = set(step.depends_on_step_ids) - step_ids
            if unknown_dependencies:
                raise PlanningValidationError("plan step has unknown dependencies")
            requirement = step.capability_requirement
            if requirement is not None and requirement.required_providers:
                user_bound = {
                    provider
                    for resource in task.resource_requirements
                    for provider in resource.required_providers
                }
                if not set(requirement.required_providers).issubset(user_bound):
                    raise PlanningValidationError("planner cannot bind a provider")
            graph[step.step_id] = set(step.depends_on_step_ids)
        _validate_acyclic(graph)


class AdaptivePlanner:
    """Planning port adapter: semantic model first, contract compiler as safe fallback."""

    def __init__(self, model_client: "StructuredModelClient | None" = None) -> None:
        self._model_client = model_client

    def create_plan(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        assessment: PlanningModeAssessment,
        procedures: tuple[ProcedureCandidate, ...],
        limits: PlanningLimits,
        usage: PlanningUsage,
        *,
        model_context: dict[str, object] | None = None,
        observation_ids: tuple[str, ...] = (),
        gap_ids: tuple[str, ...] = (),
        capability_registry_revision: str = "",
    ) -> tuple[PlanDefinition | None, PlanningUsage]:
        if usage.planner_calls >= limits.max_planner_calls:
            return None, usage
        snapshot = PlanningSnapshot(
            task_revision=task.revision,
            goal_graph_revision=ledger.goal_graph_revision,
            ledger_event_cursor=ledger.last_event_sequence,
            capability_registry_revision=capability_registry_revision,
        )
        proposal = self._with_model(
            task, ledger, assessment, procedures, model_context=model_context,
        )
        calls = usage.planner_calls
        if proposal is not None:
            calls += 1
        else:
            proposal = self._compile_contract_plan(task, ledger, procedures)
        if proposal is None or not proposal.steps:
            return None, usage.model_copy(update={"planner_calls": calls})
        plan = PlanDefinition(
            task_id=task.task_id,
            planning_snapshot=snapshot,
            planning_horizon=min(max(len(proposal.steps), 1), 5),
            strategy_summary=proposal.strategy_summary,
            target_goal_ids=assessment.target_goal_ids,
            steps=proposal.steps[:5],
            assumptions=proposal.assumptions,
            replan_triggers=proposal.replan_triggers,
            created_from_observation_ids=observation_ids,
            created_from_gap_ids=gap_ids,
        )
        return plan, usage.model_copy(update={"planner_calls": calls})

    def create_patch(
        self,
        task: TaskContract,
        plan: PlanDefinition | None,
        plan_runtime: PlanRuntimeProjection,
        request: ReplanRequest,
        limits: PlanningLimits,
        usage: PlanningUsage,
        *,
        model_context: dict[str, object] | None,
    ) -> tuple[PlanPatch | None, PlanningUsage]:
        if (
            plan is None
            or self._model_client is None
            or model_context is None
            or usage.planner_calls >= limits.max_planner_calls
            or usage.applied_patches >= limits.max_plan_patches_per_horizon
        ):
            return None, usage
        try:
            from personal_agent.infra.structured_model import StructuredModelRequest

            class PatchProposal(BaseModel):
                operations: tuple[
                    AddPlanStep | ReplacePlanStep | RemoveUnstartedPlanStep
                    | CancelPlanBranch | ClosePlanHorizon,
                    ...,
                ]
                reason_code: str
                expected_improvement: str

            response = self._model_client.generate(StructuredModelRequest(
                operation="adaptive_plan_patch",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Patch only the invalidated part of this short plan. Do not change user goals, criteria, "
                            "providers, permissions, or already-running/satisfied steps. Prefer the smallest patch and "
                            "return typed operations only."
                        ),
                    },
                    {"role": "user", "content": json.dumps({
                        "model_context": model_context,
                    }, ensure_ascii=False)},
                ],
                output_type=PatchProposal,
                temperature=0,
                max_tokens=1200,
            ))
            proposal = response.value
            if not proposal.operations:
                return None, usage.model_copy(update={
                    "planner_calls": usage.planner_calls + 1,
                })
            return PlanPatch(
                plan_id=plan.plan_id,
                base_plan_revision=plan.revision,
                base_task_revision=task.revision,
                created_at_ledger_event_cursor=plan_runtime.last_event_sequence,
                trigger_observation_ids=request.observation_ids,
                trigger_gap_ids=request.gap_ids,
                reason_code=proposal.reason_code,
                operations=proposal.operations,
                preserved_criterion_ids=tuple(
                    criterion.criterion_id for criterion in task.success_criteria
                    if criterion.mutability == "immutable"
                ),
                expected_improvement=proposal.expected_improvement,
            ), usage.model_copy(update={
                "planner_calls": usage.planner_calls + 1,
            })
        except Exception:
            logger.exception("Adaptive plan patch failed")
            return None, usage

    def _with_model(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        assessment: PlanningModeAssessment,
        procedures: tuple[ProcedureCandidate, ...],
        *,
        model_context: dict[str, object] | None,
    ) -> _ModelPlanProposal | None:
        if self._model_client is None or model_context is None:
            return None
        try:
            from personal_agent.infra.structured_model import StructuredModelRequest

            state = {
                "model_context": model_context,
                "mode": assessment.model_dump(mode="json"),
            }
            response = self._model_client.generate(StructuredModelRequest(
                operation="adaptive_plan",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Create a provider-neutral plan of at most five semantic steps. "
                            "Every step must support existing criteria, declare expected observation and failure classes, "
                            "and use CapabilityRequirement rather than concrete tools. Treat procedures as atomic. "
                            "Do not weaken goals, invent providers, expose chain-of-thought, or pre-generate alternative branches."
                        ),
                    },
                    {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
                ],
                output_type=_ModelPlanProposal,
                temperature=0,
                max_tokens=1800,
                metadata={"task_id": task.task_id},
            ))
            return response.value
        except Exception:
            logger.exception("Adaptive planner model call failed")
            return None

    @staticmethod
    def _compile_contract_plan(
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        procedures: tuple[ProcedureCandidate, ...],
    ) -> _ModelPlanProposal | None:
        """Compile only explicit task contracts; never infer a semantic action sequence."""
        steps: list[PlanStep] = []
        procedure_by_goal = {
            item.goal_id: item for item in procedures if item.status == "mandatory"
        }
        goals = materialize_goals(task, ledger)
        status_by_goal = {item.goal_id: item.status for item in goals}
        for goal in goals:
            if goal.status in {"verified", "degraded", "abandoned"}:
                continue
            if any(
                dependency.blocks_execution
                and status_by_goal.get(dependency.dependency_goal_id) not in {"verified", "degraded"}
                for dependency in goal.dependencies
            ):
                continue
            procedure = procedure_by_goal.get(goal.goal_id)
            if procedure is not None:
                steps.append(PlanStep(
                    goal_id=goal.goal_id,
                    kind="procedure",
                    objective=goal.description,
                    supports_criterion_ids=goal.success_criterion_ids,
                    procedure_id=procedure.procedure_id,
                    success_observation_contract="ProcedureOutcome",
                    failure_classes=("procedure_failed", "confirmation_missing"),
                    replan_policy="request_input",
                    side_effect_intent=procedure.side_effect_class,
                ))
                continue
            resources = task.resources_for_goal(goal.goal_id)
            operations = tuple(dict.fromkeys(
                operation for item in resources for operation in item.required_operations
            ))
            if goal.result_contract == "external_state" or set(operations).intersection(
                MUTATING_OPERATIONS
            ):
                continue
            if operations:
                requirement = CapabilityRequirement.from_dimensions(
                    requirement_id=f"{goal.goal_id}:plan",
                    purpose=f"satisfy_goal_{goal.goal_id}",
                    semantic_domains=tuple(dict.fromkeys(
                        item.semantic_domain for item in resources
                    )),
                    resource_types=tuple(dict.fromkeys(
                        value for item in resources for value in item.resource_types
                    )),
                    operations=operations,
                    resource_locator=next((item.locator for item in resources if item.locator), None),
                    freshness_required=any(item.freshness_required for item in resources),
                    required_providers=tuple(dict.fromkeys(
                        provider for item in resources for provider in item.required_providers
                    )),
                    output_contract=goal.output_contract,
                )
                steps.append(PlanStep(
                    goal_id=goal.goal_id,
                    kind="capability",
                    objective=goal.description,
                    supports_criterion_ids=goal.success_criterion_ids,
                    information_goal=goal.description,
                    capability_requirement=requirement,
                    success_observation_contract=goal.output_contract,
                    verification_requirement="goal_criteria",
                    failure_classes=("capability_unavailable", "evidence_insufficient"),
                    replan_policy="patch",
                ))
            else:
                steps.append(PlanStep(
                    goal_id=goal.goal_id,
                    kind="synthesize",
                    objective=goal.description,
                    supports_criterion_ids=goal.success_criterion_ids,
                    success_observation_contract=goal.output_contract,
                    verification_requirement="goal_criteria",
                    failure_classes=("insufficient_context",),
                    replan_policy="request_input",
                ))
        if not steps:
            return None
        return _ModelPlanProposal(
            strategy_summary="Advance ready goals from their declared result and resource contracts.",
            steps=tuple(steps[:5]),
            replan_triggers=("capability_gap", "verification_gap", "task_revision_changed"),
        )


class PlanRuntimeProjector:
    """Event-sourced projection for plan state; PlanStep itself has no status field."""

    def create(self, plan: PlanDefinition) -> PlanRuntimeProjection:
        statuses = {step.step_id: "proposed" for step in plan.steps}
        ledger = PlanRuntimeProjection(
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            step_statuses=statuses,
        )
        ledger = self.append(plan, ledger, "plan_created", payload={
            "snapshot": plan.planning_snapshot.model_dump(mode="json"),
        })
        ledger = self.append(plan, ledger, "plan_validated")
        return self._project_ready(plan, ledger)

    def replace(
        self,
        previous: PlanDefinition | None,
        ledger: PlanRuntimeProjection,
        plan: PlanDefinition,
    ) -> PlanRuntimeProjection:
        """Replace the active definition while preserving the projection cursor."""
        if previous is None:
            return self.create(plan)
        statuses = {step.step_id: "proposed" for step in plan.steps}
        updated = ledger.model_copy(update={
            "plan_id": plan.plan_id,
            "plan_revision": plan.revision,
            "step_statuses": statuses,
        })
        updated = self.append(plan, updated, "plan_replaced", payload={
            "previous_plan_id": previous.plan_id,
            "previous_plan_revision": previous.revision,
            "snapshot": plan.planning_snapshot.model_dump(mode="json"),
        })
        updated = self.append(plan, updated, "plan_validated")
        return self._project_ready(plan, updated)

    def append(
        self,
        plan: PlanDefinition,
        ledger: PlanRuntimeProjection,
        event_type: str,
        *,
        step_ids: tuple[str, ...] = (),
        observation_ids: tuple[str, ...] = (),
        payload: dict[str, object] | None = None,
    ) -> PlanRuntimeProjection:
        if ledger.plan_id != plan.plan_id or ledger.plan_revision != plan.revision:
            raise PlanningValidationError("plan projection does not reference the supplied definition")
        event = PlanEvent(
            sequence=ledger.last_event_sequence + 1,
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            event_type=event_type,
            step_ids=step_ids,
            observation_ids=observation_ids,
            payload=payload or {},
        )
        statuses = dict(ledger.step_statuses)
        projected = {
            "frontier_selected": "selected",
            "step_running": "running",
            "step_observed": "observed",
            "step_satisfied": "satisfied",
            "step_invalidated": "invalidated",
            "step_cancelled": "cancelled",
        }.get(event_type)
        if projected is not None:
            for step_id in step_ids:
                if step_id not in statuses:
                    raise PlanningValidationError(f"unknown plan step: {step_id}")
                statuses[step_id] = projected
        updated = ledger.model_copy(update={
            "step_statuses": statuses,
            "last_event_sequence": event.sequence,
        })
        return self._project_ready(plan, updated)

    def frontier(
        self, plan: PlanDefinition, ledger: PlanRuntimeProjection,
    ) -> tuple[PlanStep, ...]:
        return tuple(
            step for step in plan.steps
            if ledger.step_statuses.get(step.step_id) == "ready"
        )

    def apply_patch(
        self,
        plan: PlanDefinition,
        ledger: PlanRuntimeProjection,
        patch: PlanPatch,
    ) -> tuple[PlanDefinition, PlanRuntimeProjection]:
        if patch.plan_id != plan.plan_id:
            raise PlanningConflictError("patch targets a different plan")
        if patch.base_plan_revision != plan.revision:
            raise PlanningConflictError("patch base revision is stale")
        if patch.base_task_revision != plan.planning_snapshot.task_revision:
            raise PlanningConflictError("patch task revision is stale")
        if patch.created_at_ledger_event_cursor != ledger.last_event_sequence:
            raise PlanningConflictError("patch plan-ledger cursor is stale")
        steps = list(plan.steps)
        statuses = dict(ledger.step_statuses)
        for operation in patch.operations:
            if isinstance(operation, AddPlanStep):
                if operation.step.step_id in statuses:
                    raise PlanningValidationError("patch adds a duplicate step")
                steps.append(operation.step)
                statuses[operation.step.step_id] = "proposed"
            elif isinstance(operation, ReplacePlanStep):
                if statuses.get(operation.step_id) not in {"proposed", "ready", "invalidated"}:
                    raise PlanningValidationError("only unstarted/invalidated steps may be replaced")
                original = next(
                    (item for item in steps if item.step_id == operation.step_id),
                    None,
                )
                if original is None or operation.replacement.goal_id != original.goal_id:
                    raise PlanningValidationError("replacement cannot retarget another goal")
                steps = [
                    operation.replacement if item.step_id == operation.step_id else item
                    for item in steps
                ]
                statuses.pop(operation.step_id, None)
                statuses[operation.replacement.step_id] = "proposed"
            elif isinstance(operation, RemoveUnstartedPlanStep):
                if statuses.get(operation.step_id) not in {"proposed", "ready", "invalidated"}:
                    raise PlanningValidationError("only unstarted/invalidated steps may be removed")
                steps = [item for item in steps if item.step_id != operation.step_id]
                statuses.pop(operation.step_id, None)
            elif isinstance(operation, CancelPlanBranch):
                descendants = _descendants(tuple(steps), operation.root_step_id)
                if any(
                    statuses.get(step_id) in {"selected", "running", "observed"}
                    for step_id in descendants | {operation.root_step_id}
                ):
                    raise PlanningValidationError("patch cannot cancel a started plan branch")
                for step_id in descendants | {operation.root_step_id}:
                    if statuses.get(step_id) not in {"satisfied", "cancelled"}:
                        statuses[step_id] = "cancelled"
            elif isinstance(operation, ClosePlanHorizon):
                for step_id, status in tuple(statuses.items()):
                    if status in {"proposed", "ready"}:
                        statuses[step_id] = "cancelled"
        revised = plan.model_copy(update={
            "revision": plan.revision + 1,
            "steps": tuple(steps),
            "planning_snapshot": plan.planning_snapshot.model_copy(update={
                "plan_revision": plan.revision + 1,
            }),
        })
        updated = ledger.model_copy(update={
            "plan_revision": revised.revision,
            "step_statuses": statuses,
        })
        updated = self.append(revised, updated, "plan_patched", payload={
            "patch_id": patch.patch_id,
            "reason_code": patch.reason_code,
        })
        return revised, updated

    @staticmethod
    def _project_ready(
        plan: PlanDefinition, ledger: PlanRuntimeProjection,
    ) -> PlanRuntimeProjection:
        statuses = dict(ledger.step_statuses)
        for step in plan.steps:
            if statuses.get(step.step_id) != "proposed":
                continue
            if all(statuses.get(dependency) == "satisfied" for dependency in step.depends_on_step_ids):
                statuses[step.step_id] = "ready"
        return ledger.model_copy(update={"step_statuses": statuses})


class FrontierSelector:
    """Policy selecting semantic work; physical concurrency remains Scheduler-owned."""

    def select(
        self,
        frontier: tuple[PlanStep, ...],
        profile: PlannerExecutionProfile,
    ) -> FrontierDecision | None:
        if not frontier:
            return None
        selected = tuple(step.step_id for step in frontier[:profile.max_frontier_width])
        return FrontierDecision(
            selected_step_ids=selected,
            priority_order=selected,
            requested_join_policy="all",
            rationale="highest-priority ready plan frontier",
        )


class PlanMonitor:
    """Deterministic monitor with a bounded semantic fallback for ambiguity."""

    def __init__(self, model_client: "StructuredModelClient | None" = None) -> None:
        self._model_client = model_client

    def inspect(
        self,
        task: TaskContract,
        task_runtime: TaskRuntimeProjection,
        plan: PlanDefinition | None,
        plan_runtime: PlanRuntimeProjection,
        observations: tuple[ObservationRef, ...],
        limits: PlanningLimits,
        usage: PlanningUsage,
        *,
        model_context: dict[str, object] | None = None,
    ) -> tuple[PlanMonitorDecision, PlanRuntimeProjection]:
        if plan is None:
            return PlanMonitorDecision(
                impact="none", action="keep", reason_code="no_active_plan",
            ), plan_runtime
        if task.revision != plan.planning_snapshot.task_revision:
            return self._request(
                task, plan, plan_runtime, observations, "goal_assumption_invalidated",
                "task_revision_changed",
            )
        if task_runtime.goal_graph_revision != plan.planning_snapshot.goal_graph_revision:
            return self._request(
                task, plan, plan_runtime, observations, "goal_assumption_invalidated",
                "goal_graph_revision_changed",
            )
        open_goal_ids = {
            item.goal_id for item in materialize_goals(task, task_runtime)
            if item.status not in {"verified", "degraded", "abandoned"}
        }
        if open_goal_ids and all(
            status in {"satisfied", "cancelled"}
            for status in plan_runtime.step_statuses.values()
        ):
            return self._request(
                task,
                plan,
                plan_runtime,
                observations,
                "goal_assumption_invalidated",
                "planning_horizon_exhausted",
            )
        latest = observations[-1] if observations else None
        if latest is None:
            return PlanMonitorDecision(
                impact="none", action="keep", reason_code="no_new_observation",
            ), plan_runtime
        selected = tuple(
            step_id for step_id, status in plan_runtime.step_statuses.items()
            if status in {"selected", "running", "observed"}
        )
        if latest.kind in {"capability_gap", "verification_gap"}:
            if usage.applied_patches >= limits.max_plan_patches_per_horizon:
                return PlanMonitorDecision(
                    impact="branch_invalidated",
                    action="request_input",
                    affected_step_ids=selected,
                    reason_code="plan_patch_budget_exhausted",
                ), plan_runtime
            return self._request(
                task, plan, plan_runtime, observations, "step_invalidated", latest.kind,
                affected_step_ids=selected,
            )
        if latest.kind in {"technical_error", "provider_timeout"} and latest.payload.get("retryable"):
            return PlanMonitorDecision(
                impact="local_retry",
                action="local_retry",
                affected_step_ids=selected,
                reason_code="technical_retry_available",
            ), plan_runtime
        semantic = self._semantic_impact(
            selected,
            limits,
            usage,
            model_context=model_context,
        )
        if semantic is not None:
            if semantic.impact in {"step_invalidated", "branch_invalidated"}:
                return self._request(
                    task,
                    plan,
                    plan_runtime,
                    observations,
                    semantic.impact,
                    semantic.reason_code,
                    affected_step_ids=semantic.affected_step_ids,
                    decision_source="semantic",
                )
            return PlanMonitorDecision(
                impact=semantic.impact,
                action="local_retry" if semantic.impact == "local_retry" else "keep",
                affected_step_ids=semantic.affected_step_ids,
                reason_code=semantic.reason_code,
                decision_source="semantic",
            ), plan_runtime
        return PlanMonitorDecision(
            impact="none", action="keep", reason_code="observation_preserves_strategy",
        ), plan_runtime

    @staticmethod
    def _request(
        task: TaskContract,
        plan: PlanDefinition,
        plan_runtime: PlanRuntimeProjection,
        observations: tuple[ObservationRef, ...],
        impact: str,
        reason_code: str,
        *,
        affected_step_ids: tuple[str, ...] = (),
        decision_source: str = "deterministic",
    ) -> tuple[PlanMonitorDecision, PlanRuntimeProjection]:
        observation_ids = tuple(item.observation_id for item in observations[-4:])
        signature = hashlib.sha256(json.dumps({
            "reason": reason_code,
            "observations": observation_ids,
            "steps": affected_step_ids,
        }, sort_keys=True).encode()).hexdigest()[:20]
        if signature in plan_runtime.seen_replan_signatures:
            return PlanMonitorDecision(
                impact="none", action="keep", reason_code="duplicate_replan_suppressed",
            ), plan_runtime
        request = ReplanRequest(
            source="monitor",
            task_revision=task.revision,
            plan_revision=plan.revision,
            affected_goal_ids=tuple(dict.fromkeys(
                step.goal_id for step in plan.steps if step.step_id in affected_step_ids
            )),
            observation_ids=observation_ids,
            reason_code=reason_code,
        )
        updated = plan_runtime.model_copy(update={
            "seen_replan_signatures": (*plan_runtime.seen_replan_signatures, signature),
        })
        updated = PlanRuntimeProjector().append(plan, updated, "replan_requested", payload={
            "request": request.model_dump(mode="json"),
            "impact": impact,
        })
        return PlanMonitorDecision(
            impact=impact,
            action="replace" if impact == "goal_assumption_invalidated" else "patch",
            affected_step_ids=affected_step_ids,
            reason_code=reason_code,
            replan_request=request,
            decision_source=decision_source,
        ), updated

    def _semantic_impact(
        self,
        selected_step_ids: tuple[str, ...],
        limits: PlanningLimits,
        usage: PlanningUsage,
        *,
        model_context: dict[str, object] | None,
    ) -> _SemanticMonitorChoice | None:
        if (
            self._model_client is None
            or model_context is None
            or usage.semantic_monitor_calls >= limits.max_semantic_monitor_calls
        ):
            return None
        try:
            from personal_agent.infra.structured_model import StructuredModelRequest

            response = self._model_client.generate(StructuredModelRequest(
                operation="plan_semantic_monitor",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify whether the latest observation preserves the active plan, permits a local retry, "
                            "invalidates the selected step, or invalidates its branch. Use only supplied projected "
                            "context. Never alter goals or criteria. Return none when evidence is insufficient."
                        ),
                    },
                    {"role": "user", "content": json.dumps({
                        "model_context": model_context,
                    }, ensure_ascii=False)},
                ],
                output_type=_SemanticMonitorChoice,
                temperature=0,
                max_tokens=300,
            ))
            choice = response.value
            allowed_impacts = {"none", "local_retry", "step_invalidated", "branch_invalidated"}
            if choice.impact not in allowed_impacts:
                return _SemanticMonitorChoice(
                    impact="none", reason_code="semantic_monitor_output_rejected",
                )
            if not set(choice.affected_step_ids).issubset(selected_step_ids):
                return _SemanticMonitorChoice(
                    impact="none", reason_code="semantic_monitor_step_scope_rejected",
                )
            if choice.impact in {"step_invalidated", "branch_invalidated"} and not choice.affected_step_ids:
                return _SemanticMonitorChoice(
                    impact="none", reason_code="semantic_monitor_missing_affected_steps",
                )
            return choice
        except Exception:
            logger.exception("Semantic plan monitoring failed; retaining deterministic plan")
            return _SemanticMonitorChoice(
                impact="none", reason_code="semantic_monitor_failed_closed",
            )


def _validate_acyclic(graph: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise PlanningValidationError("plan step dependencies contain a cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in graph[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in graph:
        visit(step_id)


def _descendants(steps: tuple[PlanStep, ...], root_step_id: str) -> set[str]:
    descendants: set[str] = set()
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step.step_id in descendants:
                continue
            if root_step_id in step.depends_on_step_ids or descendants.intersection(step.depends_on_step_ids):
                descendants.add(step.step_id)
                changed = True
    return descendants


__all__ = [
    "ADVISORY_READ_ONLY_PROFILE", "BOUNDED_READ_ONLY_PROFILE", "AdaptivePlanner",
    "GOVERNED_MIXED_PROFILE",
    "FrontierSelector", "PlanRuntimeProjector", "PlanMonitor", "PlanValidator",
    "PlanningConflictError", "PlanningFactProjector", "PlanningModePolicy",
    "PlanningValidationError", "profile_for_task",
]

"""Task-level executive decision policy with deterministic safety clamps."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from personal_agent.runtime.contracts.task import (
    TaskRuntimeProjection,
    MaterializedGoalView,
    TaskContract,
    materialize_goals,
)
from personal_agent.capabilities.contracts.execution import CapabilityRequirement
from personal_agent.runtime.contracts.control import (
    BoundedAction,
    CapabilityClassSummary,
    ClarifyDecision,
    CompletionClaim,
    ControlDecision,
    ControlState,
    DecisionBasis,
    DelegateDecision,
    ExecuteBoundedActionDecision,
    FinishDecision,
    InvokeProcedureDecision,
    ObservationRef,
    ProposedResourceAccessPlan,
    ProcedureInvocation,
    ProcedureRef,
    RequestConfirmationDecision,
    RequestCapabilityAcquisitionDecision,
    TerminateDecision,
    SubtaskSpec,
)
from personal_agent.capabilities.contracts.procedure import ProcedureCandidate
from personal_agent.runtime.contracts.planning import PlanStep
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS
from personal_agent.skills import SkillRegistry

if TYPE_CHECKING:
    from personal_agent.capabilities.contracts.model import StructuredModelClient

logger = logging.getLogger(__name__)


class _ModelExecutiveDecision(BaseModel):
    action: Literal[
        "acquire", "explore", "reason", "transform",
        "verify", "commit", "delegate", "clarify", "request_confirmation",
        "invoke_procedure", "finish", "terminate",
    ]
    target_goal_id: str
    skill_id: str = ""
    procedure_id: str = ""
    question: str = ""
    reason_code: str = ""
    expected_progress: str = ""


class ExecutiveController:
    def __init__(
        self,
        model_client: "StructuredModelClient | None" = None,
        *,
        skills: SkillRegistry | None = None,
        tenant_id: str = "default",
    ) -> None:
        self._model_client = model_client
        self.tenant_id = tenant_id
        self.skills = skills or SkillRegistry.with_builtin_trust(tenant_id)

    def decide(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        *,
        observations: tuple[ObservationRef, ...] = (),
        capability_classes: tuple[CapabilityClassSummary, ...] = (),
        control_state: ControlState | None = None,
        model_context: dict[str, object] | None = None,
    ) -> ControlDecision:
        goals = materialize_goals(task, ledger)
        open_goals = [
            item for item in goals
            if item.status not in {"verified", "degraded", "abandoned"}
        ]
        if not open_goals:
            return self._finish(task, ledger)
        ready_goals = [item for item in open_goals if _dependencies_satisfied(item, ledger)]
        procedure_candidates = (
            control_state.procedure_candidates if control_state is not None else ()
        )
        model_choice = self._model_choice(
            task,
            ledger,
            ready_goals,
            observations,
            capability_classes,
            control_state,
            model_context,
        )
        if not ready_goals:
            return TerminateDecision(
                target_goal_id=open_goals[0].goal_id,
                basis=DecisionBasis(expected_state_change="task_terminated"),
                expected_progress="stop_dependency_deadlock",
                reason_code="goal_dependency_deadlock",
                user_message="目标依赖未完成，且当前没有可继续推进的独立目标。",
            )
        fallback_goal = _select_goal(ready_goals)
        goal = next(
            (item for item in ready_goals if model_choice and item.goal_id == model_choice.target_goal_id),
            fallback_goal,
        )
        goal_observations = _observations_for_goal(goal, observations)
        basis = _basis(goal, goal_observations)
        capability_gap = next(
            (item for item in reversed(goal_observations) if item.kind == "capability_gap"),
            None,
        )
        if capability_gap is not None:
            return RequestCapabilityAcquisitionDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="request_missing_capability",
                requirement=_requirement(task, goal, "acquire"),
            )
        goal_procedures = tuple(
            item for item in procedure_candidates
            if item.goal_id == goal.goal_id and item.status in {"eligible", "mandatory"}
        )
        mandatory = tuple(item for item in goal_procedures if item.status == "mandatory")
        if mandatory:
            return self._procedure_decision(
                task, goal, basis, mandatory[0], goal_observations,
            )

        if model_choice is not None:
            materialized = self._materialize_choice(
                task,
                ledger,
                goal,
                basis,
                model_choice,
                capability_classes,
                goal_procedures,
            )
            if materialized is not None:
                return materialized

        if goal_procedures and not goal.attempts:
            return self._procedure_decision(task, goal, basis, goal_procedures[0])
        fallback = self._materialize_contract_action(task, ledger, goal, basis)
        if fallback is not None:
            return fallback
        return TerminateDecision(
            target_goal_id=goal.goal_id,
            basis=basis.model_copy(update={
                "rejected_action_codes": ("no_safe_contract_action",),
            }),
            expected_progress="stop_without_inventing_action_sequence",
            reason_code="executive_model_unavailable",
            user_message="当前没有足够信息生成安全的下一步动作，任务已停止。",
        )

    def decide_plan_step(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        step: PlanStep,
        *,
        observations: tuple[ObservationRef, ...] = (),
        control_state: ControlState | None = None,
    ) -> ControlDecision:
        goal = next(
            (item for item in materialize_goals(task, ledger) if item.goal_id == step.goal_id),
            None,
        )
        if goal is None:
            return TerminateDecision(
                target_goal_id=step.goal_id,
                reason_code="plan_step_goal_missing",
                user_message="计划引用的目标已失效，任务已安全停止。",
            )
        basis = _basis(goal, _observations_for_goal(goal, observations))
        procedures = tuple(
            item for item in (control_state.procedure_candidates if control_state else ())
            if item.goal_id == goal.goal_id and item.status in {"eligible", "mandatory"}
        )
        mandatory = next((item for item in procedures if item.status == "mandatory"), None)
        if mandatory is not None:
            return self._procedure_decision(task, goal, basis, mandatory, observations)
        if step.kind == "procedure":
            candidate = next((item for item in procedures if item.procedure_id == step.procedure_id), None)
            if candidate is None:
                return TerminateDecision(
                    target_goal_id=goal.goal_id,
                    basis=basis,
                    reason_code="planned_procedure_ineligible",
                    user_message="计划要求的受治理过程当前不可用，任务已安全停止。",
                )
            return self._procedure_decision(task, goal, basis, candidate, observations)
        if step.kind == "delegate":
            requirement = step.capability_requirement
            assert requirement is not None
            return DelegateDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress=step.objective,
                subtask=SubtaskSpec(
                    goal=step.objective,
                    parent_goal_id=goal.goal_id,
                    required_capability=requirement,
                    requested_operations=requirement.operations,
                    expected_artifact_contract=step.success_observation_contract,
                ),
            )
        return self._action_from_plan_step(task, ledger, goal, basis, step)

    def _action_from_plan_step(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        goal: MaterializedGoalView,
        basis: DecisionBasis,
        step: PlanStep,
    ) -> ControlDecision:
        requirement = step.capability_requirement
        operations = set(requirement.operations if requirement is not None else ())
        if step.kind == "verify":
            meta = "verify"
        elif step.kind == "synthesize":
            meta = "transform"
        elif operations.intersection(MUTATING_OPERATIONS):
            meta = "commit"
        else:
            meta = "acquire"
        resources = task.resources_for_goal(goal.goal_id)
        bounded = BoundedAction(
            goal_id=goal.goal_id,
            execution_intent=meta,
            description=step.objective,
            output_contract=step.success_observation_contract,
            requirement=requirement,
            max_tool_calls=2 if requirement is not None else 0,
            max_model_calls=1,
            max_iterations=task.constraints.max_iterations,
            proposed_resource_access=ProposedResourceAccessPlan(
                read_set=tuple(
                    {"semantic_domain": item.semantic_domain, "locator": item.locator}
                    for item in resources
                ),
                write_set=tuple(
                    {"semantic_domain": item.semantic_domain, "locator": item.locator}
                    for item in resources
                ) if meta == "commit" else (),
                side_effect_class=step.side_effect_intent,
            ),
            payload={
                "task_text": step.objective,
                "plan_step_id": step.step_id,
                "information_goal": step.information_goal,
                "execution_guidance": _execution_guidance(self, task, ledger, goal),
                "agentic_synthesis": self._model_client is not None,
            },
        )
        return ExecuteBoundedActionDecision(
            target_goal_id=goal.goal_id,
            basis=basis,
            expected_progress=step.objective,
            bounded_action=bounded,
        )

    def _materialize_contract_action(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        goal: MaterializedGoalView,
        basis: DecisionBasis,
    ) -> ControlDecision | None:
        """Compile one declared result contract; never infer a multi-action sequence."""
        resources = task.resources_for_goal(goal.goal_id)
        operations = tuple(dict.fromkeys(
            operation for item in resources for operation in item.required_operations
        ))
        if set(operations).intersection(MUTATING_OPERATIONS):
            return None
        if operations:
            requirement = CapabilityRequirement.from_dimensions(
                requirement_id=f"{goal.goal_id}:reactive",
                purpose=f"satisfy_goal_{goal.goal_id}",
                semantic_domains=tuple(dict.fromkeys(item.semantic_domain for item in resources)),
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
            step = PlanStep(
                goal_id=goal.goal_id,
                kind="capability",
                objective=goal.description,
                supports_criterion_ids=goal.success_criterion_ids,
                capability_requirement=requirement,
                success_observation_contract=goal.output_contract,
                failure_classes=("capability_unavailable",),
            )
        elif goal.result_contract in {"response", "artifact"}:
            step = PlanStep(
                goal_id=goal.goal_id,
                kind="synthesize",
                objective=goal.description,
                supports_criterion_ids=goal.success_criterion_ids,
                success_observation_contract=goal.output_contract,
                failure_classes=("insufficient_context",),
                replan_policy="request_input",
            )
        else:
            return None
        return self._action_from_plan_step(task, ledger, goal, basis, step)

    @staticmethod
    def _procedure_decision(
        task: TaskContract,
        goal: MaterializedGoalView,
        basis: DecisionBasis,
        candidate: ProcedureCandidate,
        observations: tuple[ObservationRef, ...] = (),
    ) -> ControlDecision:
        has_new_user_input = bool(observations) and observations[-1].kind in {
            "user_clarification", "user_confirmation",
        }
        if goal.attempts and not has_new_user_input:
            return TerminateDecision(
                target_goal_id=goal.goal_id,
                basis=basis.model_copy(update={
                    "expected_state_change": "task_terminated",
                    "rejected_action_codes": ("repeat_procedure_without_new_input",),
                }),
                expected_progress="stop_without_repeating_side_effect_procedure",
                reason_code="procedure_result_inconclusive",
                user_message="受治理过程已执行，但结果不足以证明目标完成；未重复执行可能产生副作用的操作。",
            )
        resources = task.resources_for_goal(goal.goal_id)
        procedure_text = goal.description
        if has_new_user_input:
            procedure_text = f"{procedure_text}\n补充信息：{observations[-1].summary}"
        return InvokeProcedureDecision(
            target_goal_id=goal.goal_id,
            basis=basis,
            expected_progress="execute_governed_procedure",
            procedure_invocation=ProcedureInvocation(
                procedure=ProcedureRef(
                    procedure_id=candidate.procedure_id,
                    version=candidate.version,
                ),
                goal_id=goal.goal_id,
                input={
                    "text": procedure_text,
                    "resource_types": sorted({value for item in resources for value in item.resource_types}),
                    "operations": sorted({value for item in resources for value in item.required_operations}),
                    "locator": next((item.locator for item in resources if item.locator), None),
                },
                idempotency_key=f"{task.task_id}:{goal.goal_id}:{candidate.procedure_id}",
                expected_output_contract="ProcedureOutcome",
            ),
        )

    def _model_choice(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        goals: list[MaterializedGoalView],
        observations: tuple[ObservationRef, ...],
        capability_classes: tuple[CapabilityClassSummary, ...],
        control_state: ControlState | None,
        model_context: dict[str, object] | None,
    ) -> _ModelExecutiveDecision | None:
        if self._model_client is None or model_context is None:
            return None
        try:
            from personal_agent.capabilities.contracts.model import StructuredModelRequest

            ready_goal_ids = {item.goal_id for item in goals}
            state = model_context
            response = self._model_client.generate(StructuredModelRequest(
                operation="executive_decision",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Choose one bounded control action with the best expected progress and target a ready goal. "
                            "Do not revise goals, criteria, dependencies, or the active plan; those belong to the planning layer. "
                            "Skills and their playbooks are optional methods; procedures are governed transactions, "
                            "and observations are feedback. Choose invoke_procedure only from eligible candidates and never "
                            "bypass a mandatory procedure. "
                            "Use their full contracts, respect budgets, avoid failed paths, and clarify when a resource binding "
                            "or authorization is required. Never choose finish unless the goal is verified. "
                            "Return only the requested structured object; do not reveal chain-of-thought."
                        ),
                    },
                    {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
                ],
                output_type=_ModelExecutiveDecision,
                context_projection_ref=str(state.get("projection_id") or ""),
                temperature=0,
                max_tokens=300,
                kind="structured",
                metadata={"task_id": task.task_id, "ready_goal_ids": sorted(ready_goal_ids)},
            ))
            choice = response.value
            if choice.target_goal_id not in ready_goal_ids:
                return None
            return choice
        except Exception:
            logger.exception("Executive model decision failed; using deterministic policy")
            return None

    def _materialize_choice(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        goal: MaterializedGoalView,
        basis: DecisionBasis,
        choice: _ModelExecutiveDecision | None,
        capability_classes: tuple[CapabilityClassSummary, ...],
        procedure_candidates: tuple[ProcedureCandidate, ...],
    ) -> ControlDecision | None:
        if choice is None:
            return None
        action = choice.action
        if action == "invoke_procedure":
            candidate = next((
                item for item in procedure_candidates
                if choice is not None and item.procedure_id == choice.procedure_id
            ), None)
            return self._procedure_decision(task, goal, basis, candidate) if candidate else None
        if action == "clarify":
            if choice is None or not choice.question.strip():
                return None
            return ClarifyDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress=choice.expected_progress or "obtain_missing_input",
                question=choice.question.strip(),
            )
        if action == "request_confirmation":
            if choice is None or task.mutation_intent is None:
                return None
            return RequestConfirmationDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress=choice.expected_progress or "obtain_mutation_confirmation",
                title="确认执行变更",
                summary=choice.question.strip() or goal.description,
            )
        if action == "finish":
            if goal.status == "verified":
                return self._finish(task, ledger)
            return None if choice is not None else self._finish(task, ledger)
        if action == "terminate":
            return TerminateDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="stop_without_unsafe_guessing",
                reason_code=choice.reason_code if choice and choice.reason_code else "executive_no_safe_progress",
                user_message="当前能力或证据不足，任务已停止。",
            )
        if action == "delegate":
            if not _has_exact_delegate(task, goal, capability_classes):
                return None
            requirement = _requirement(task, goal, "delegate")
            return DelegateDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="obtain_specialist_artifact",
                subtask=SubtaskSpec(
                    goal=goal.description,
                    parent_goal_id=goal.goal_id,
                    required_capability=requirement,
                    requested_operations=requirement.operations,
                    expected_artifact_contract="ResearchReport",
                ),
            )
        meta = action if action in {
            "acquire", "explore", "reason", "transform", "verify", "commit",
        } else "transform"
        if meta == "commit" and task.mutation_intent is None:
            return None
        requirement = _requirement(task, goal, meta)
        resources = task.resources_for_goal(goal.goal_id)
        bounded = BoundedAction(
            goal_id=goal.goal_id,
            execution_intent=meta,
            description=f"{meta}: {goal.description}",
            output_contract=_action_output_contract(meta),
            requirement=requirement,
            max_tool_calls=(6 if meta == "explore" else 2)
            if meta in {"acquire", "explore", "commit"} else 0,
            max_model_calls=1,
            max_iterations=task.constraints.max_iterations,
            proposed_resource_access=ProposedResourceAccessPlan(
                read_set=tuple(
                    {"semantic_domain": item.semantic_domain, "locator": item.locator}
                    for item in resources
                ),
                write_set=tuple(
                    {"semantic_domain": item.semantic_domain, "locator": item.locator}
                    for item in resources
                ) if meta == "commit" else (),
                side_effect_class="mutation" if meta == "commit" else "none",
            ),
            payload={
                "task_text": goal.description,
                "execution_guidance": _execution_guidance(self, task, ledger, goal),
                "agentic_synthesis": self._model_client is not None,
            },
        )
        return ExecuteBoundedActionDecision(
            target_goal_id=goal.goal_id,
            basis=basis,
            expected_progress=choice.expected_progress if choice and choice.expected_progress else f"complete_{meta}",
            bounded_action=bounded,
        )

    @staticmethod
    def _finish(task: TaskContract, ledger: TaskRuntimeProjection) -> FinishDecision:
        goals = materialize_goals(task, ledger)
        return FinishDecision(
            target_goal_id=goals[-1].goal_id,
            basis=DecisionBasis(expected_state_change="task_completed"),
            expected_progress="verified_completion",
            completion_claim=CompletionClaim(
                goal_ids=tuple(item.goal_id for item in goals),
                criterion_ids=tuple(item.criterion_id for item in task.success_criteria),
            ),
        )


def _select_goal(goals: list[MaterializedGoalView]) -> MaterializedGoalView:
    priority = {"active": 0, "blocked": 1, "candidate_complete": 2, "awaiting_input": 3, "pending": 4}
    return sorted(goals, key=lambda item: (priority.get(item.status, 9), item.goal_id))[0]


def _dependencies_satisfied(goal: MaterializedGoalView, ledger: TaskRuntimeProjection) -> bool:
    status_by_id = {
        goal_id: state.status for goal_id, state in ledger.goal_states.items()
    }
    return all(
        status_by_id.get(dependency.dependency_goal_id) in {"verified", "degraded"}
        for dependency in goal.dependencies
        if dependency.blocks_execution
    )


def _observations_for_goal(
    goal: MaterializedGoalView,
    observations: tuple[ObservationRef, ...],
) -> tuple[ObservationRef, ...]:
    scoped = tuple(item for item in observations if item.goal_id == goal.goal_id)
    return scoped or tuple(item for item in observations if not item.goal_id)


def _skill_candidates(catalog: SkillRegistry, task: TaskContract, goal: MaterializedGoalView) -> tuple:
    domains = {item.semantic_domain for item in task.resources_for_goal(goal.goal_id)}
    return tuple(
        skill for skill in catalog.candidates(
            semantic_domains=frozenset(
                item.semantic_domain for item in task.resource_requirements
            ),
            operations=frozenset(task.requested_operations),
            result_contract=task.result_contract,
        )
        if domains.intersection(skill.applicability.semantic_domains)
        or task.result_contract in skill.applicability.result_contracts
    )
def _execution_guidance(
    controller: ExecutiveController,
    task: TaskContract,
    ledger: TaskRuntimeProjection,
    goal: MaterializedGoalView,
) -> list[str]:
    guidance = []
    relevant_skill_ids = {
        item.skill_id for item in _skill_candidates(controller.skills, task, goal)
    }
    for skill_id in ledger.active_skill_ids:
        if skill_id not in relevant_skill_ids:
            continue
        # Active skills are task-scoped; only inject methods applicable to this goal.
        try:
            skill = controller.skills.get(controller.tenant_id, skill_id)
        except (KeyError, PermissionError):
            continue
        instructions = skill.instructions.strip()
        if instructions:
            guidance.append(instructions)
    return guidance


def _has_exact_delegate(
    task: TaskContract,
    goal: MaterializedGoalView,
    capability_classes: tuple[CapabilityClassSummary, ...],
) -> bool:
    requirement = _requirement(task, goal, "delegate")
    domains = set(requirement.semantic_domains)
    required_providers = set(requirement.required_providers)
    return any(
        item.kind == "agent"
        and "delegate" in item.operations
        and (not domains or bool(domains.intersection(item.semantic_domains)))
        and (not required_providers or bool(required_providers.intersection(item.providers)))
        for item in capability_classes
    )


def _basis(goal: MaterializedGoalView, observations: tuple[ObservationRef, ...]) -> DecisionBasis:
    return DecisionBasis(
        unmet_criterion_ids=goal.success_criterion_ids,
        triggering_observation_ids=tuple(item.observation_id for item in observations[-3:]),
        evidence_gap_ids=goal.evidence_gaps,
        expected_state_change="advance_goal",
    )


def _requirement(task: TaskContract, goal: MaterializedGoalView, meta: str) -> CapabilityRequirement:
    resources = task.resources_for_goal(goal.goal_id)
    domains = tuple(dict.fromkeys(item.semantic_domain for item in resources))
    resource_types = tuple(dict.fromkeys(value for item in resources for value in item.resource_types))
    locator = next((item.locator for item in resources if item.locator), None)
    if meta == "delegate":
        operations = ("delegate",)
    elif meta == "verify":
        operations = ("verify",)
    elif meta in {"acquire", "explore"}:
        operations = tuple(dict.fromkeys(
            operation for item in resources for operation in item.required_operations
            if operation in {"search", "read", "list"}
        )) or ("read",)
    elif meta == "commit":
        operations = tuple(dict.fromkeys(
            operation for item in resources for operation in item.required_operations
            if operation in MUTATING_OPERATIONS
        ))
    else:
        operations = ()
    return CapabilityRequirement.from_dimensions(
        requirement_id=f"{goal.goal_id}:{meta}",
        purpose=f"{meta}_{goal.result_contract}",
        semantic_domains=domains,
        resource_types=resource_types,
        operations=operations,
        resource_locator=locator,
        minimum_trust_level="external",
        freshness_required=any(item.freshness_required for item in resources),
        preferred_providers=tuple(dict.fromkeys(
            provider for item in resources for provider in item.preferred_providers
        )),
        required_providers=tuple(dict.fromkeys(
            provider for item in resources for provider in item.required_providers
        )),
        output_contract=_action_output_contract(meta),
        side_effect_class="none",
    )


def _action_output_contract(meta: str) -> str:
    return {
        "acquire": "ContextPack",
        "explore": "EvidencePack",
        "reason": "DraftAnswer",
        "transform": "Answer",
        "verify": "VerificationReport",
        "delegate": "AgentArtifact",
        "commit": "MutationReceipt",
    }.get(meta, "ToolResult")


__all__ = ["ExecutiveController"]

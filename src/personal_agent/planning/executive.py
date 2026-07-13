"""Task-level executive decision policy with deterministic safety clamps."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from personal_agent.kernel.contracts.agentic import (
    ExecutionLedger,
    ExecutionLedgerItem,
    TaskSpec,
)
from personal_agent.kernel.contracts.capability import CapabilityRequirement
from personal_agent.kernel.contracts.executive import (
    ActivateSkillDecision,
    BoundedAction,
    CapabilityClassSummary,
    CompletionClaim,
    ControlDecision,
    DecisionBasis,
    DelegateDecision,
    ExecuteMetaCapabilityDecision,
    ExecuteParallelDecision,
    FinishDecision,
    InvokeProtocolDecision,
    LedgerPatch,
    LedgerPatchOperation,
    ObservationRef,
    ProtocolCall,
    RevisePlanDecision,
    StopDecision,
    SubtaskSpec,
)
from personal_agent.planning.skills import PlanMacroCatalog, SkillCatalog

if TYPE_CHECKING:
    from personal_agent.infra.structured_model import StructuredModelClient

logger = logging.getLogger(__name__)


class _ModelExecutiveDecision(BaseModel):
    action: Literal[
        "activate_skill", "apply_macro", "acquire", "explore", "reason", "transform",
        "delegate", "finish", "stop",
    ]
    target_goal_id: str
    skill_id: str = ""
    expected_progress: str = ""


class ExecutiveController:
    def __init__(
        self,
        model_client: "StructuredModelClient | None" = None,
        *,
        skills: SkillCatalog | None = None,
        macros: PlanMacroCatalog | None = None,
    ) -> None:
        self._model_client = model_client
        self.skills = skills or SkillCatalog()
        self.macros = macros or PlanMacroCatalog()

    def decide(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        *,
        observations: tuple[ObservationRef, ...] = (),
        capability_classes: tuple[CapabilityClassSummary, ...] = (),
    ) -> ControlDecision:
        open_goals = [
            item for item in ledger.items
            if item.status not in {"verified", "degraded", "abandoned"}
        ]
        if not open_goals:
            return self._finish(task, ledger)
        goal = _select_goal(open_goals)
        basis = _basis(goal, observations)

        skill = next(
            (item for item in self.skills.candidates(task) if item.skill_id not in ledger.active_skill_ids),
            None,
        )
        if skill is not None and goal.goal_kind != "direct_response":
            return ActivateSkillDecision(
                target_goal_id=goal.goal_id,
                skill_id=skill.skill_id,
                basis=basis,
                expected_progress="load_task_method",
            )

        macro_goal = next((
            candidate for candidate in open_goals
            if (
                (candidate_macro := self.macros.for_goal_kind(candidate.goal_kind)) is not None
                and all(ref.macro_id != candidate_macro.macro_id for ref in ledger.applied_macros)
            )
        ), goal)
        macro = self.macros.for_goal_kind(macro_goal.goal_kind)
        if macro is not None and all(ref.macro_id != macro.macro_id for ref in ledger.applied_macros):
            return RevisePlanDecision(
                target_goal_id=macro_goal.goal_id,
                basis=_basis(macro_goal, observations),
                expected_progress="apply_plan_prior",
                proposed_ledger_patch=LedgerPatch(
                    reason_code="macro_recommended",
                    operations=(LedgerPatchOperation(
                        op="apply_macro",
                        goal_id=macro_goal.goal_id,
                        values={"macro_id": macro.macro_id, "version": macro.version},
                    ),),
                ),
            )

        parallel = self._parallel_decision(task, ledger, open_goals, observations)
        if parallel is not None:
            return parallel

        if goal.goal_kind == "protocol":
            if goal.attempts:
                return StopDecision(
                    target_goal_id=goal.goal_id,
                    basis=basis.model_copy(update={
                        "expected_state_change": "task_stopped",
                        "rejected_action_codes": ("repeat_protocol_without_new_input",),
                    }),
                    expected_progress="stop_without_repeating_side_effect_protocol",
                    reason_code="protocol_result_inconclusive",
                    user_message="协议已执行，但结果不足以证明目标完成；未重复执行可能产生副作用的操作。",
                )
            return InvokeProtocolDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="execute_governed_protocol",
                protocol_call=ProtocolCall(
                    protocol_id=goal.protocol_id or "unknown",
                    goal_id=goal.goal_id,
                    operation=goal.protocol_id or "unknown",
                    input={"text": goal.description},
                    requires_confirmation=task.mutation_intent is not None,
                ),
            )

        if (
            goal.status == "blocked"
            and goal.goal_kind in {"investigation", "evidence_answer"}
            and any(item.kind == "agent" and "delegate" in item.operations for item in capability_classes)
            and all(item.meta_capability != "delegate" for item in goal.attempts)
        ):
            requirement = _requirement(task, goal, "delegate")
            return DelegateDecision(
                target_goal_id=goal.goal_id,
                basis=basis.model_copy(update={"expected_state_change": "delegate_capability_gap"}),
                expected_progress="obtain_specialist_artifact",
                subtask=SubtaskSpec(
                    goal=goal.description,
                    parent_goal_id=goal.goal_id,
                    required_capability=requirement,
                    expected_artifact_contract="ResearchReport",
                ),
            )

        model_choice = self._model_choice(task, ledger, goal, observations, capability_classes)
        return self._materialize_choice(task, ledger, goal, basis, model_choice)

    def _parallel_decision(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        goals: list[ExecutionLedgerItem],
        observations: tuple[ObservationRef, ...],
    ) -> ExecuteParallelDecision | None:
        candidates = [
            item for item in goals
            if item.status == "active"
            and item.goal_kind in {"evidence_answer", "investigation"}
            and not item.attempts
        ]
        if len(candidates) < 2 or task.constraints.max_parallelism < 2:
            return None
        actions = []
        for goal in candidates[:task.constraints.max_parallelism]:
            meta = _next_meta_capability(goal, [])
            requirement = _requirement(task, goal, meta)
            actions.append(BoundedAction(
                goal_id=goal.goal_id,
                meta_capability=meta,
                description=f"{meta}: {goal.description}",
                output_contract=_action_output_contract(meta),
                requirement=requirement,
                max_tool_calls=6 if meta == "explore" else 2,
                max_model_calls=1,
                max_iterations=task.constraints.max_iterations,
                read_set=tuple(
                    {"semantic_domain": item.semantic_domain, "locator": item.locator}
                    for item in task.resource_requirements
                ),
                payload={"task_text": goal.description},
            ))
        return ExecuteParallelDecision(
            target_goal_id=actions[0].goal_id,
            basis=_basis(candidates[0], observations).model_copy(update={
                "expected_state_change": "parallel_evidence_acquisition",
            }),
            expected_progress="advance_independent_read_only_goals",
            parallel_actions=tuple(actions),
        )

    def _model_choice(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        goal: ExecutionLedgerItem,
        observations: tuple[ObservationRef, ...],
        capability_classes: tuple[CapabilityClassSummary, ...],
    ) -> _ModelExecutiveDecision | None:
        if self._model_client is None:
            return None
        try:
            from personal_agent.infra.structured_model import StructuredModelRequest

            state = {
                "task_goal": task.user_goal,
                "goal": goal.model_dump(mode="json"),
                "attempted_meta_capabilities": [item.meta_capability for item in goal.attempts],
                "latest_observations": [item.model_dump(mode="json") for item in observations[-4:]],
                "capability_classes": [item.model_dump(mode="json") for item in capability_classes],
                "active_skills": list(ledger.active_skill_ids),
                "applied_macros": [item.macro_id for item in ledger.applied_macros],
            }
            response = self._model_client.generate(StructuredModelRequest(
                operation="executive_decision",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Choose the single bounded semantic action that best advances the unmet goal. "
                            "Use observations, avoid repeating failed paths, and do not choose finish unless the goal is verified. "
                            "Return only the requested structured object; do not reveal chain-of-thought."
                        ),
                    },
                    {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
                ],
                output_type=_ModelExecutiveDecision,
                temperature=0,
                max_tokens=300,
                kind="structured",
                metadata={"task_id": task.task_id, "goal_id": goal.goal_id},
            ))
            choice = response.value
            if choice.target_goal_id != goal.goal_id:
                return None
            return choice
        except Exception:
            logger.exception("Executive model decision failed; using deterministic policy")
            return None

    def _materialize_choice(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        goal: ExecutionLedgerItem,
        basis: DecisionBasis,
        choice: _ModelExecutiveDecision | None,
    ) -> ControlDecision:
        attempted = [item.meta_capability for item in goal.attempts if item.status == "succeeded"]
        action = choice.action if choice is not None else _next_meta_capability(goal, attempted)
        if action == "finish":
            if goal.status == "verified":
                return self._finish(task, ledger)
            action = _next_meta_capability(goal, attempted)
        if action == "stop":
            return StopDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="stop_without_unsafe_guessing",
                reason_code="executive_no_safe_progress",
                user_message="当前能力或证据不足，任务已停止。",
            )
        if action == "delegate" or goal.goal_kind == "delegate":
            requirement = _requirement(task, goal, "delegate")
            return DelegateDecision(
                target_goal_id=goal.goal_id,
                basis=basis,
                expected_progress="obtain_specialist_artifact",
                subtask=SubtaskSpec(
                    goal=goal.description,
                    parent_goal_id=goal.goal_id,
                    required_capability=requirement,
                    expected_artifact_contract="ResearchReport",
                ),
            )
        if action in {"activate_skill", "apply_macro"}:
            # Mandatory skill/macro opportunities were handled before the model call.
            action = _next_meta_capability(goal, attempted)
        meta = action if action in {"acquire", "explore", "reason", "transform", "verify"} else "transform"
        requirement = _requirement(task, goal, meta)
        bounded = BoundedAction(
            goal_id=goal.goal_id,
            meta_capability=meta,
            description=f"{meta}: {goal.description}",
            output_contract=_action_output_contract(meta),
            requirement=requirement,
            max_tool_calls=6 if meta == "explore" else 2,
            max_model_calls=1,
            max_iterations=task.constraints.max_iterations,
            read_set=tuple(
                {"semantic_domain": item.semantic_domain, "locator": item.locator}
                for item in task.resource_requirements
            ),
            side_effect_class="none",
            payload={"task_text": goal.description},
        )
        return ExecuteMetaCapabilityDecision(
            target_goal_id=goal.goal_id,
            basis=basis,
            expected_progress=choice.expected_progress if choice and choice.expected_progress else f"complete_{meta}",
            bounded_action=bounded,
        )

    @staticmethod
    def _finish(task: TaskSpec, ledger: ExecutionLedger) -> FinishDecision:
        return FinishDecision(
            target_goal_id=ledger.items[-1].goal_id if ledger.items else "task",
            basis=DecisionBasis(expected_state_change="task_completed"),
            expected_progress="verified_completion",
            completion_claim=CompletionClaim(
                goal_ids=tuple(item.goal_id for item in ledger.items),
                criterion_ids=tuple(item.criterion_id for item in task.success_criteria),
            ),
        )


def _select_goal(goals: list[ExecutionLedgerItem]) -> ExecutionLedgerItem:
    priority = {"active": 0, "blocked": 1, "candidate_complete": 2, "awaiting_input": 3, "pending": 4}
    return sorted(goals, key=lambda item: (priority.get(item.status, 9), item.goal_id))[0]


def _basis(goal: ExecutionLedgerItem, observations: tuple[ObservationRef, ...]) -> DecisionBasis:
    return DecisionBasis(
        unmet_criterion_ids=goal.success_criterion_ids,
        triggering_observation_ids=tuple(item.observation_id for item in observations[-3:]),
        evidence_gap_ids=goal.evidence_gaps,
        expected_state_change="advance_goal",
    )


def _next_meta_capability(goal: ExecutionLedgerItem, attempted: list[str]) -> str:
    if goal.status == "blocked":
        if goal.goal_kind in {"investigation", "evidence_answer"} and attempted.count("explore") < 2:
            return "explore"
        return "stop"
    sequence = {
        "direct_response": ("transform",),
        "evidence_answer": ("acquire", "reason", "transform"),
        "investigation": ("explore", "transform"),
        "delegate": ("delegate", "transform"),
    }.get(goal.goal_kind, ("transform",))
    return next((item for item in sequence if item not in attempted), "transform")


def _requirement(task: TaskSpec, goal: ExecutionLedgerItem, meta: str) -> CapabilityRequirement:
    resources = task.resource_requirements
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
    else:
        operations = ()
    return CapabilityRequirement(
        requirement_id=f"{goal.goal_id}:{meta}",
        purpose=f"{meta}_{goal.goal_kind}",
        semantic_domains=domains,
        resource_types=resource_types,
        operations=operations,
        resource_locator=locator,
        minimum_trust_level="external",
        freshness_required=task.evidence_requirements.contradiction_check,
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
    }.get(meta, "ToolResult")


__all__ = ["ExecutiveController"]

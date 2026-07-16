"""Deterministic validation for model-proposed executive decisions."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import (
    TaskRuntimeProjection,
    TaskContract,
    materialize_goals,
)
from personal_agent.kernel.contracts.executive import (
    ControlState,
    ControlDecision,
    DelegateDecision,
    ExecuteMetaCapabilityDecision,
    InvokeProcedureDecision,
)
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS


class DecisionValidationError(ValueError):
    pass


class DecisionValidator:
    def validate(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        decision: ControlDecision,
        control_state: ControlState | None = None,
    ) -> None:
        goals = {
            item.goal_id: item for item in materialize_goals(task, ledger)
        }
        if decision.target_goal_id not in goals and decision.action not in {"finish", "stop"}:
            raise DecisionValidationError("decision targets an unknown goal")
        goal = goals.get(decision.target_goal_id)
        goal_procedures = tuple(
            candidate for candidate in (control_state.procedure_candidates if control_state else ())
            if candidate.goal_id == decision.target_goal_id
            and candidate.status in {"eligible", "mandatory"}
        )
        if (
            any(candidate.status == "mandatory" for candidate in goal_procedures)
            and not isinstance(decision, InvokeProcedureDecision)
            and decision.action not in {"stop", "clarify", "request_confirmation"}
        ):
            raise DecisionValidationError("mandatory governed procedure cannot be bypassed")
        if (
            goal is not None
            and decision.action not in {"finish", "stop"}
        ):
            unmet_dependencies = tuple(
                dependency.dependency_goal_id
                for dependency in goal.dependencies
                if dependency.blocks_execution and (
                    dependency.dependency_goal_id not in goals
                    or goals[dependency.dependency_goal_id].status not in {"verified", "degraded"}
                )
            )
            if unmet_dependencies:
                raise DecisionValidationError(
                    f"goal has unmet dependencies: {', '.join(unmet_dependencies)}"
                )
        if (
            goal is not None
            and goal.status in {"verified", "degraded", "abandoned"}
            and decision.action not in {"finish", "stop"}
        ):
            raise DecisionValidationError("decision targets a terminal goal")
        if isinstance(decision, ExecuteMetaCapabilityDecision):
            action = decision.bounded_action
            access = action.proposed_resource_access
            if action.goal_id != decision.target_goal_id:
                raise DecisionValidationError("bounded action goal does not match decision target")
            if access.side_effect_class != "none" and (
                action.meta_capability != "commit"
                or task.mutation_intent is None
                or not access.write_set
                or action.requirement is None
                or not set(action.requirement.operations).intersection(
                    MUTATING_OPERATIONS
                )
            ):
                raise DecisionValidationError(
                    "side effects require a declared commit, mutation intent, and write set"
                )
            if action.max_tool_calls > task.constraints.max_provider_calls:
                raise DecisionValidationError("bounded action exceeds task provider-call budget")
            if (
                control_state is not None
                and action.max_tool_calls > control_state.remaining_provider_calls
            ):
                raise DecisionValidationError("bounded action exceeds remaining provider-call budget")
        if isinstance(decision, InvokeProcedureDecision):
            call = decision.procedure_invocation
            if goal is None or call.goal_id != goal.goal_id:
                raise DecisionValidationError("procedure call goal does not match decision target")
            candidate = next((
                item for item in goal_procedures
                if item.procedure_id == call.procedure.procedure_id
                and item.version == call.procedure.version
            ), None)
            if candidate is None:
                raise DecisionValidationError("procedure call is not an eligible candidate")
            if control_state is not None and control_state.remaining_provider_calls < 1:
                raise DecisionValidationError("procedure requires a remaining provider call")
        if (
            isinstance(decision, DelegateDecision)
            and control_state is not None
            and decision.subtask.max_provider_calls > control_state.remaining_provider_calls
        ):
            raise DecisionValidationError("delegation exceeds remaining provider-call budget")

__all__ = ["DecisionValidationError", "DecisionValidator"]

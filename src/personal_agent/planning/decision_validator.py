"""Deterministic validation for model-proposed executive decisions."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import ExecutionLedger, TaskSpec
from personal_agent.kernel.contracts.executive import (
    ControlDecision,
    ExecuteMetaCapabilityDecision,
    ExecuteParallelDecision,
    InvokeProtocolDecision,
)


class DecisionValidationError(ValueError):
    pass


class DecisionValidator:
    def validate(self, task: TaskSpec, ledger: ExecutionLedger, decision: ControlDecision) -> None:
        goals = {item.goal_id: item for item in ledger.items}
        if decision.target_goal_id not in goals and decision.action not in {"finish", "stop"}:
            raise DecisionValidationError("decision targets an unknown goal")
        goal = goals.get(decision.target_goal_id)
        if (
            goal is not None
            and goal.status in {"verified", "degraded", "abandoned"}
            and decision.action not in {"finish", "stop"}
        ):
            raise DecisionValidationError("decision targets a terminal goal")
        if isinstance(decision, ExecuteMetaCapabilityDecision):
            action = decision.bounded_action
            if action.goal_id != decision.target_goal_id:
                raise DecisionValidationError("bounded action goal does not match decision target")
            if action.side_effect_class != "none":
                raise DecisionValidationError("side effects must execute through a protocol")
            if action.max_tool_calls > task.constraints.max_provider_calls:
                raise DecisionValidationError("bounded action exceeds task provider-call budget")
        if isinstance(decision, ExecuteParallelDecision):
            if len(decision.parallel_actions) > task.constraints.max_parallelism:
                raise DecisionValidationError("parallel action count exceeds task budget")
            self._validate_parallel(decision)
        if isinstance(decision, InvokeProtocolDecision):
            if goal is None or not goal.protocol_id:
                raise DecisionValidationError("protocol decision requires a protocol-owned goal")
            if decision.protocol_call.protocol_id != goal.protocol_id:
                raise DecisionValidationError("protocol call does not match the goal protocol")

    @staticmethod
    def _validate_parallel(decision: ExecuteParallelDecision) -> None:
        actions = decision.parallel_actions
        for action in actions:
            if action.side_effect_class != "none" or action.write_set:
                raise DecisionValidationError("parallel actions must be read-only")
        for index, left in enumerate(actions):
            left_reads = {(item.semantic_domain, item.locator) for item in left.read_set}
            left_outputs = set(left.input_artifact_ids)
            for right in actions[index + 1:]:
                right_reads = {(item.semantic_domain, item.locator) for item in right.read_set}
                if left_outputs.intersection(right.input_artifact_ids):
                    raise DecisionValidationError("parallel actions have artifact dependencies")
                if not left_reads or not right_reads:
                    raise DecisionValidationError("parallel resource declarations must be complete")


__all__ = ["DecisionValidationError", "DecisionValidator"]

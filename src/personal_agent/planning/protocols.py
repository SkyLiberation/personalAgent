"""Governed protocol boundary around deterministic domain state machines."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.execution import ExecutionPlan, ExecutionStep
from personal_agent.kernel.contracts.executive import ProtocolCall
from personal_agent.planning.router import Goal, RouterDecision
from personal_agent.planning.workflow_planner import WorkflowPlanner


@dataclass(frozen=True, slots=True)
class MaterializedProtocol:
    protocol_call: ProtocolCall
    plan: ExecutionPlan
    steps: tuple[ExecutionStep, ...]


class ProtocolRegistry:
    """Expose state machines by protocol ID without routing the whole task."""

    def __init__(self, workflow_planner: WorkflowPlanner) -> None:
        self._planner = workflow_planner

    def materialize(
        self,
        call: ProtocolCall,
        *,
        entry_text: str,
        routing_key: str,
    ) -> MaterializedProtocol:
        protocol_input = str(call.input.get("text") or entry_text)
        decision = RouterDecision(
            user_goal=protocol_input,
            goals=[Goal(
                goal_id=call.goal_id,
                intent=call.operation,
                input=protocol_input,
            )],
        )
        plan, steps = self._planner.plan(
            decision,
            entry_text=protocol_input,
            routing_key=routing_key,
        )
        for step in steps:
            step.projection_kind = "protocol_step"
            step.workflow_id = call.protocol_id
            step.task_id = call.goal_id
        return MaterializedProtocol(call, plan, tuple(steps))


__all__ = ["MaterializedProtocol", "ProtocolRegistry"]

"""Deterministic admission for an accepted command's execution route."""

from __future__ import annotations

from personal_agent.runtime.contracts.control import (
    ControlDecision,
    ControlState,
    DelegateDecision,
    ExecuteBoundedActionDecision,
    ExecutionRouteDecision,
    InvokeProcedureDecision,
    RouteProposal,
)


class RouteAdmissionError(ValueError):
    pass


class ExecutionRoutePolicy:
    policy_revision = "v1"

    def admit(
        self,
        proposal: RouteProposal,
        decision: ControlDecision,
        control_state: ControlState | None,
    ) -> ExecutionRouteDecision:
        expected = self.propose(decision)
        if proposal.action_id != expected.action_id or proposal.proposed_route != expected.proposed_route:
            raise RouteAdmissionError("route proposal does not match the accepted command")

        mandatory = tuple(
            item for item in (control_state.procedure_candidates if control_state else ())
            if item.goal_id == decision.target_goal_id and item.status == "mandatory"
        )
        if mandatory and proposal.proposed_route != "procedure":
            raise RouteAdmissionError("mandatory procedure forbids the proposed execution route")

        denied = tuple(
            route for route in ("atomic", "delegated", "procedure", "internal_reasoning")
            if route != proposal.proposed_route
        )
        constraints = tuple(
            f"procedure:{item.procedure_id}@{item.version}" for item in mandatory
        )
        return ExecutionRouteDecision(
            action_id=proposal.action_id,
            accepted_route=proposal.proposed_route,
            mandatory_constraints=constraints,
            denied_routes=denied,
            reason_codes=proposal.reason_codes,
            policy_revision=self.policy_revision,
        )

    @staticmethod
    def propose(decision: ControlDecision) -> RouteProposal:
        if isinstance(decision, InvokeProcedureDecision):
            return RouteProposal(
                action_id=decision.procedure_invocation.invocation_id,
                proposed_route="procedure",
                reason_codes=("governed_procedure_command",),
            )
        if isinstance(decision, DelegateDecision):
            return RouteProposal(
                action_id=decision.subtask.subtask_id,
                proposed_route="delegated",
                reason_codes=("delegation_command",),
            )
        if isinstance(decision, ExecuteBoundedActionDecision):
            action = decision.bounded_action
            internal = (
                action.requirement is None
                and action.execution_intent in {"reason", "transform", "verify"}
                and action.proposed_resource_access.side_effect_class == "none"
            )
            return RouteProposal(
                action_id=action.action_id,
                proposed_route="internal_reasoning" if internal else "atomic",
                reason_codes=("local_reasoning_boundary" if internal else "atomic_capability_required",),
            )
        raise RouteAdmissionError("non-executable control decision has no execution route")


__all__ = ["ExecutionRoutePolicy", "RouteAdmissionError"]


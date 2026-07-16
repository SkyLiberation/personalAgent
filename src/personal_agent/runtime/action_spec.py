"""Build the only dispatchable action contract."""

from __future__ import annotations

from datetime import UTC, datetime

from personal_agent.capabilities.contracts.execution import ExecutionResolutionResult
from personal_agent.runtime.contracts.control import (
    BoundedAction,
    BudgetReservation,
    ResolvedActionSpec,
    ResolvedResourceAccessPlan,
    RetryDirective,
)


def _remaining_seconds(deadline: datetime | None) -> int:
    if deadline is None:
        return 0
    normalized = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=UTC)
    return max(int((normalized - datetime.now(UTC)).total_seconds()), 0)


class ResolvedActionBuilder:
    def build(
        self,
        *,
        decision_ref: str,
        action: BoundedAction,
        context_projection_ref: str,
        access_plan: ResolvedResourceAccessPlan,
        capability_resolution: ExecutionResolutionResult | None = None,
        retry_directive: RetryDirective | None = None,
    ) -> ResolvedActionSpec:
        grant_ref = (
            capability_resolution.execution_grant.grant_id
            if capability_resolution is not None and capability_resolution.execution_grant is not None
            else None
        )
        return ResolvedActionSpec(
            action_id=action.action_id,
            decision_ref=decision_ref,
            goal_id=action.goal_id,
            execution_grant_ref=grant_ref,
            context_projection_ref=context_projection_ref,
            resource_access_plan=access_plan,
            retry_directive=retry_directive,
            budget_reservation=BudgetReservation(
                token_budget=max(action.max_model_calls, 0) * 2048,
                provider_call_budget=action.max_tool_calls,
                time_budget_seconds=_remaining_seconds(action.deadline),
            ),
            verification_contract=action.output_contract,
        )


__all__ = ["ResolvedActionBuilder"]

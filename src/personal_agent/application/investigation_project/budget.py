"""Durable Project budget admission and deterministic completion checks."""

from __future__ import annotations

from uuid import uuid4

from personal_agent.domain.investigation_project import (
    BudgetCategory,
    InvestigationProject,
    ProjectUsage,
)


class BudgetExceeded(RuntimeError):
    pass


class ProjectBudgetLedger:
    def reserve(
        self,
        project: InvestigationProject,
        *,
        category: BudgetCategory,
        tokens: int = 0,
        cost: float = 0,
        tool_calls: int = 0,
        agent_calls: int = 0,
        reservation_id: str | None = None,
    ) -> ProjectUsage:
        requested = ProjectUsage(
            category=category,
            reservation_id=reservation_id or f"ipbud_{uuid4().hex[:20]}",
            tokens=tokens,
            cost=cost,
            tool_calls=tool_calls,
            agent_calls=agent_calls,
        )
        limit = project.definition.budget
        total_tokens = (
            project.charged_tokens()
            + project.reserved_tokens()
            + requested.tokens
        )
        category_tokens = (
            project.charged_tokens(category)
            + project.reserved_tokens(category)
            + requested.tokens
        )
        total_cost = sum(item.cost for item in project.usages) + sum(
            item.cost for item in project.active_reservations.values()
        ) + requested.cost
        total_tool_calls = sum(item.tool_calls for item in project.usages) + sum(
            item.tool_calls for item in project.active_reservations.values()
        ) + requested.tool_calls
        total_agent_calls = sum(item.agent_calls for item in project.usages) + sum(
            item.agent_calls for item in project.active_reservations.values()
        ) + requested.agent_calls
        if total_tokens > limit.total_tokens:
            raise BudgetExceeded("project total token budget exhausted")
        if category_tokens > limit.category_token_limit(category):
            raise BudgetExceeded(f"{category} token budget exhausted")
        if total_cost > limit.total_cost:
            raise BudgetExceeded("project cost budget exhausted")
        if total_tool_calls > limit.max_tool_calls:
            raise BudgetExceeded("project tool-call budget exhausted")
        if total_agent_calls > limit.max_agent_calls:
            raise BudgetExceeded("project agent-call budget exhausted")
        return requested


class CompletionGate:
    @staticmethod
    def required_coverage_complete(project: InvestigationProject) -> bool:
        coverage = project.requirement_coverage()
        return bool(coverage) and all(
            status in {"verified", "waived"} for status in coverage.values()
        )

    @staticmethod
    def has_unresolved_blocking_failure(project: InvestigationProject) -> bool:
        return any(item.blocking_required_work for item in project.waiting_reasons.values())


__all__ = ["BudgetExceeded", "CompletionGate", "ProjectBudgetLedger"]


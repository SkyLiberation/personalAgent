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
    @staticmethod
    def remaining_total_tokens(project: InvestigationProject) -> int:
        return max(
            0,
            project.definition.budget.total_tokens
            - project.charged_tokens()
            - project.reserved_tokens(),
        )

    @staticmethod
    def remaining_category_tokens(
        project: InvestigationProject,
        category: BudgetCategory,
    ) -> int:
        return max(
            0,
            project.definition.budget.category_token_limit(category)
            - project.charged_tokens(category)
            - project.reserved_tokens(category),
        )

    def remaining_tokens(
        self,
        project: InvestigationProject,
        *,
        category: BudgetCategory,
    ) -> int:
        return min(
            self.remaining_total_tokens(project),
            self.remaining_category_tokens(project, category),
        )

    @staticmethod
    def remaining_cost(project: InvestigationProject) -> float:
        committed = sum(item.cost for item in project.usages) + sum(
            item.cost for item in project.active_reservations.values()
        )
        return max(0.0, project.definition.budget.total_cost - committed)

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
        total_tool_calls = sum(item.tool_calls for item in project.usages) + sum(
            item.tool_calls for item in project.active_reservations.values()
        ) + requested.tool_calls
        total_agent_calls = sum(item.agent_calls for item in project.usages) + sum(
            item.agent_calls for item in project.active_reservations.values()
        ) + requested.agent_calls
        if requested.tokens > self.remaining_total_tokens(project):
            raise BudgetExceeded("project total token budget exhausted")
        if requested.tokens > self.remaining_category_tokens(project, category):
            raise BudgetExceeded(f"{category} token budget exhausted")
        if requested.cost > self.remaining_cost(project):
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

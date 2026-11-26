"""Conversation quota decisions derived from committed run facts."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from personal_agent.application.bash_execution.models import BashExecutionAuthorization

from .journal import InMemoryInteractionJournal
from .models import (
    ActionProposal, CommittedUsage, DecisionFeedback, InteractionTrace, LoopBudgetPolicy,
    RunExecutionBudget, ToolCallProposal,
)
from .bash_authorization import require_bash_authorization


def deadline_elapsed(deadline_at: datetime | None) -> bool:
    return deadline_at is not None and datetime.now(UTC) >= deadline_at


@dataclass(frozen=True, slots=True)
class ConversationBudget:
    limits: LoopBudgetPolicy
    journal: InMemoryInteractionJournal
    bash_authorization: BashExecutionAuthorization | None = None

    def remaining_model_tokens(self, trace: InteractionTrace, usage: CommittedUsage) -> int:
        remaining = self.limits.max_total_tokens - usage.total_tokens
        if trace.bash_authorization_digest is not None:
            authorization = require_bash_authorization(trace, self.bash_authorization)
            consumed = self.journal.conversation_usage(trace).total_tokens
            consumed += max(0, usage.total_tokens - trace.usage.total_tokens)
            remaining = min(remaining, authorization.max_total_tokens - consumed)
        return max(0, remaining)

    def tool_calls_exhausted(self, usage: CommittedUsage) -> bool:
        limit = self.limits.max_tool_calls
        return limit is not None and usage.tool_calls >= limit

    def counted_tool_quota_exhausted(self, usage: CommittedUsage) -> bool:
        # Zero disables ordinary tools while leaving built-in goal and verification operations available.
        limit = self.limits.max_tool_calls
        return limit is not None and 0 < limit <= usage.tool_calls

    def new_decision_exhausted(self, trace: InteractionTrace, usage: CommittedUsage) -> bool:
        return (usage.model_turns >= self.limits.max_model_turns
                or self.remaining_model_tokens(trace, usage) <= 0)

    def model_send_rejection(
        self, trace: InteractionTrace, usage: CommittedUsage,
    ) -> Literal["run_deadline_exceeded", "model_token_budget_exhausted"] | None:
        if deadline_elapsed(trace.run_deadline_at):
            return "run_deadline_exceeded"
        if self.remaining_model_tokens(trace, usage) <= 0:
            return "model_token_budget_exhausted"
        return None

    def action_dispatch_exhausted(self, trace: InteractionTrace) -> bool:
        return (self.remaining_model_tokens(trace, trace.usage) <= 0
                or deadline_elapsed(trace.run_deadline_at))

    @staticmethod
    def execution_available(trace: InteractionTrace, execution: RunExecutionBudget) -> bool:
        return (trace.run_deadline_at is not None
                and not deadline_elapsed(trace.run_deadline_at)
                and execution.remaining_seconds > 0 and not execution.unsettled_action_ids)

    def allocate_actions(
        self, actions: Iterable[ActionProposal], usage: CommittedUsage,
    ) -> tuple[list[ActionProposal], list[DecisionFeedback]]:
        tool_limit = self.limits.max_tool_calls
        remaining: dict[Literal["tool", "agent"], int | None] = {
            "tool": None if tool_limit is None else max(0, tool_limit - usage.tool_calls),
            "agent": max(0, self.limits.max_agent_calls - usage.agent_calls),
        }
        runnable, denied = [], []
        for action in actions:
            kind: Literal["tool", "agent"] = "tool" if isinstance(action, ToolCallProposal) else "agent"
            available = remaining[kind]
            if available == 0:
                denied.append(DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="budget_exhausted",
                    message=f"The committed {kind} call budget is exhausted.",
                    immutable_fields=("action_id",),
                    required_repair="Stop or request additional budget.",
                    disposition="fail_closed",
                ))
                continue
            if available is not None:
                remaining[kind] = available - 1
            runnable.append(action)
        return runnable, denied

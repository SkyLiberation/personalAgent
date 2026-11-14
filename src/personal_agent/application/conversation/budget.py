"""Conversation quota decisions derived from committed run facts."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.python_execution.models import PythonExecutionAuthorization

from .journal import InMemoryInteractionJournal
from .models import (
    ActionProposal, CommittedUsage, DecisionFeedback, InteractionTrace, LoopBudgetPolicy,
    RunExecutionBudget, ToolCallProposal,
)
from .python_authorization import require_python_authorization


class RemainingInteractionBudget(BaseModel):
    """Read-only budget facts at decision input construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_turns: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    agent_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    wall_seconds_at_input: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def deadline_elapsed(deadline_at: datetime | None) -> bool:
    return deadline_at is not None and datetime.now(UTC) >= deadline_at


@dataclass(frozen=True, slots=True)
class ConversationBudget:
    limits: LoopBudgetPolicy
    journal: InMemoryInteractionJournal
    python_authorization: PythonExecutionAuthorization | None = None

    def remaining_model_tokens(self, trace: InteractionTrace, usage: CommittedUsage) -> int:
        remaining = self.limits.max_total_tokens - usage.total_tokens
        if trace.python_authorization_digest is not None:
            authorization = require_python_authorization(trace, self.python_authorization)
            consumed = self.journal.conversation_usage(trace).total_tokens
            consumed += max(0, usage.total_tokens - trace.usage.total_tokens)
            remaining = min(remaining, authorization.max_total_tokens - consumed)
        return max(0, remaining)

    def tool_calls_exhausted(self, usage: CommittedUsage) -> bool:
        return usage.tool_calls >= self.limits.max_tool_calls

    def tool_stop_reached(self, usage: CommittedUsage) -> bool:
        # A zero tool quota blocks ordinary tool dispatch without stopping main decisions.
        return self.limits.max_tool_calls > 0 and self.tool_calls_exhausted(usage)

    def new_decision_exhausted(self, trace: InteractionTrace, usage: CommittedUsage) -> bool:
        return (usage.model_turns >= self.limits.max_model_turns
                or self.remaining_model_tokens(trace, usage) <= 0
                or self.tool_stop_reached(usage))

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

    def model_snapshot(self, trace: InteractionTrace, usage: CommittedUsage) -> RemainingInteractionBudget:
        tokens = self.remaining_model_tokens(trace, usage)
        wall_seconds = (max(0.0, (trace.run_deadline_at - datetime.now(UTC)).total_seconds())
                        if trace.run_deadline_at is not None else None)
        return RemainingInteractionBudget(
            model_turns=max(0, self.limits.max_model_turns - usage.model_turns),
            tool_calls=max(0, self.limits.max_tool_calls - usage.tool_calls),
            agent_calls=max(0, self.limits.max_agent_calls - usage.agent_calls),
            # Keep the original projection of the effective positive policy limit.
            tokens=max(0, max(1, usage.total_tokens + tokens) - usage.total_tokens),
            wall_seconds_at_input=wall_seconds,
        )

    @staticmethod
    def should_warn_low_token_balance(usage: CommittedUsage, remaining: RemainingInteractionBudget) -> bool:
        effective_limit = usage.total_tokens + remaining.tokens
        return usage.model_turns > 0 and 0 < remaining.tokens * 10 < effective_limit

    def allocate_actions(
        self, actions: Iterable[ActionProposal], usage: CommittedUsage,
    ) -> tuple[list[ActionProposal], list[DecisionFeedback]]:
        remaining: dict[Literal["tool", "agent"], int] = {
            "tool": max(0, self.limits.max_tool_calls - usage.tool_calls),
            "agent": max(0, self.limits.max_agent_calls - usage.agent_calls),
        }
        runnable, denied = [], []
        for action in actions:
            kind: Literal["tool", "agent"] = "tool" if isinstance(action, ToolCallProposal) else "agent"
            if remaining[kind] == 0:
                denied.append(DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="budget_exhausted",
                    message=f"The committed {kind} call budget is exhausted.",
                    immutable_fields=("action_id",),
                    required_repair="Stop or request additional budget.",
                    disposition="fail_closed",
                ))
                continue
            remaining[kind] -= 1
            runnable.append(action)
        return runnable, denied

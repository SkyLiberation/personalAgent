from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationMessage(_StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class WorkingPlanSnapshot(_StrictModel):
    """Model-owned, transient plan display; never an execution fact."""

    summary: str = Field(min_length=1, max_length=2_000)
    constraints: tuple[str, ...] = ()
    remaining_work: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    revision_reason: Literal[
        "initial", "observation", "decision_feedback", "user_input", "context_rebuild"
    ] = "initial"


class ToolCallProposal(_StrictModel):
    kind: Literal["tool_call"] = "tool_call"
    action_id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:16]}", min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentDelegationProposal(_StrictModel):
    kind: Literal["agent_delegation"] = "agent_delegation"
    action_id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:16]}", min_length=1)
    agent_id: str = Field(min_length=1)
    bounded_sub_goal: str = Field(min_length=1, max_length=4_000)
    context_projection_refs: tuple[str, ...] = ()
    expected_artifact_types: tuple[str, ...] = ()
    token_budget: int = Field(default=4_000, ge=1)
    cost_budget: float = Field(default=1.0, ge=0)
    time_budget_seconds: int = Field(default=180, ge=1, le=180)


ActionProposal = ToolCallProposal | AgentDelegationProposal


class FinalMessage(_StrictModel):
    kind: Literal["final_message"] = "final_message"
    disposition: Literal[
        "answer", "clarification_required", "limitation", "failed"
    ]
    message: str = Field(min_length=1)


class ContinueTurnProposal(_StrictModel):
    kind: Literal["continue_turn"] = "continue_turn"
    working_plan: WorkingPlanSnapshot | None = None
    actions: tuple[ActionProposal, ...] = ()

    @model_validator(mode="after")
    def _action_ids_are_unique(self) -> "ContinueTurnProposal":
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("actions in one turn require unique action_id values")
        return self


class AgentTurnDecision(_StrictModel):
    """Object-root model-output envelope accepted by the interaction loop."""

    decision: FinalMessage | ContinueTurnProposal


class EffectiveToolCapability(_StrictModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    safely_retryable: bool


class EffectiveAgentCapability(_StrictModel):
    agent_id: str
    description: str
    task_types: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()


class EffectiveCapabilities(_StrictModel):
    """Transient projection from registries and current availability."""

    revision: str
    tools: tuple[EffectiveToolCapability, ...] = ()
    agents: tuple[EffectiveAgentCapability, ...] = ()


class DecisionFeedback(_StrictModel):
    kind: Literal["decision_feedback"] = "decision_feedback"
    action_id: str
    reason_code: str
    message: str
    repairable_fields: tuple[str, ...] = ()
    immutable_fields: tuple[str, ...] = ()
    required_repair: str = ""
    disposition: Literal["revise", "clarify", "fail_closed"] = "revise"


class ActionObservation(_StrictModel):
    kind: Literal["tool_result", "agent_status", "agent_artifact"]
    action_id: str
    capability_id: str
    status: Literal["succeeded", "failed", "running", "cancelled"]
    payload: dict[str, Any] = Field(default_factory=dict)


InteractionInput = DecisionFeedback | ActionObservation


class LoopBudgetPolicy(_StrictModel):
    policy_revision: str = "interaction-loop-v1"
    max_model_turns: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=12, ge=0)
    max_agent_calls: int = Field(default=4, ge=0)
    max_total_tokens: int = Field(default=32_000, ge=1)
    max_concurrency: int = Field(default=4, ge=1)


class CommittedUsage(_StrictModel):
    model_turns: int = 0
    tool_calls: int = 0
    agent_calls: int = 0
    total_tokens: int = 0


class InteractionTrace(_StrictModel):
    interaction_run_ref: str
    capability_revision: str
    messages: tuple[ConversationMessage, ...]
    working_plans: tuple[WorkingPlanSnapshot, ...] = ()
    inputs: tuple[InteractionInput, ...] = ()
    usage: CommittedUsage = Field(default_factory=CommittedUsage)
    execution_order: tuple[str, ...] = ()
    concurrent_batches: tuple[tuple[str, ...], ...] = ()
    final_message: FinalMessage | None = None


class ConversationTurnView(_StrictModel):
    interaction_run_ref: str = ""
    conversation_id: str
    disposition: Literal["answer", "clarification_required", "limitation", "failed"]
    message: ConversationMessage


__all__ = [
    "ActionObservation", "ActionProposal", "AgentDelegationProposal", "AgentTurnDecision",
    "CommittedUsage", "ContinueTurnProposal", "ConversationMessage", "ConversationTurnView",
    "DecisionFeedback", "EffectiveAgentCapability", "EffectiveCapabilities",
    "EffectiveToolCapability", "FinalMessage", "InteractionTrace", "LoopBudgetPolicy",
    "ToolCallProposal", "WorkingPlanSnapshot",
]

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationMessage(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


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


class KnowledgeSaveSelection(_StrictModel):
    source_message_index: int = Field(ge=0)
    text_span: str = Field(min_length=1)


class KnowledgeSaveArguments(_StrictModel):
    selections: tuple[KnowledgeSaveSelection, ...] = Field(min_length=1)


ActionProposal = ToolCallProposal | AgentDelegationProposal


class FinalMessage(_StrictModel):
    kind: Literal["final_message"] = "final_message"
    disposition: Literal[
        "answer", "clarification_required", "limitation", "failed"
    ]
    message: str = Field(min_length=1)


class ContinueTurnProposal(_StrictModel):
    kind: Literal["continue_turn"] = "continue_turn"
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


class ConversationKnowledgeSaveCommand(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str
    action_id: str
    interaction_run_ref: str
    tenant_id: str
    workspace_id: str
    user_id: str
    source_message_indexes: tuple[int, ...] = Field(min_length=1)
    messages: tuple[ConversationMessage, ...] = Field(min_length=1)
    policy_revision: str = "conversation-knowledge-save-v1"
    command_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _only_user_messages_are_frozen(self) -> "ConversationKnowledgeSaveCommand":
        if any(message.role != "user" for message in self.messages):
            raise ValueError("knowledge save command can freeze only user messages")
        return self


class ConversationKnowledgeSaveReceipt(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str = Field(default_factory=lambda: f"ksr_{uuid4().hex[:16]}")
    command_id: str
    command_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_ref: str = Field(min_length=1)
    artifact_id: str
    claim_ids: tuple[str, ...] = ()
    knowledge_item_ids: tuple[str, ...] = ()
    user_claim_count: int = Field(ge=0)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationKnowledgeSaveOperation(_StrictModel):
    command: ConversationKnowledgeSaveCommand
    status: Literal["awaiting_confirmation", "rejected", "executed"]
    receipt: ConversationKnowledgeSaveReceipt | None = None

    @model_validator(mode="after")
    def _receipt_matches_terminal_state(self) -> "ConversationKnowledgeSaveOperation":
        if (self.status == "executed") != (self.receipt is not None):
            raise ValueError("only an executed knowledge save operation has a receipt")
        if self.receipt is not None and (
            self.receipt.command_id != self.command.command_id
            or self.receipt.command_digest != self.command.command_digest
        ):
            raise ValueError("knowledge save receipt is not bound to its command")
        return self


class InteractionTrace(_StrictModel):
    revision: int = Field(default=1, ge=1)
    interaction_run_ref: str
    capability_revision: str
    messages: tuple[ConversationMessage, ...]
    inputs: tuple[InteractionInput, ...] = ()
    usage: CommittedUsage = Field(default_factory=CommittedUsage)
    execution_order: tuple[str, ...] = ()
    concurrent_batches: tuple[tuple[str, ...], ...] = ()
    final_message: FinalMessage | None = None
    knowledge_save_operation: ConversationKnowledgeSaveOperation | None = None


class ConversationTurnView(_StrictModel):
    interaction_run_ref: str = ""
    conversation_id: str
    disposition: Literal[
        "answer", "clarification_required", "confirmation_required", "limitation", "failed"
    ]
    message: ConversationMessage
    pending_confirmation: ConversationKnowledgeSaveOperation | None = None


__all__ = [
    "ActionObservation", "ActionProposal", "AgentDelegationProposal", "AgentTurnDecision",
    "CommittedUsage", "ContinueTurnProposal", "ConversationMessage", "ConversationTurnView",
    "ConversationKnowledgeSaveCommand", "ConversationKnowledgeSaveOperation",
    "ConversationKnowledgeSaveReceipt",
    "DecisionFeedback", "EffectiveAgentCapability", "EffectiveCapabilities",
    "EffectiveToolCapability", "FinalMessage", "InteractionTrace", "LoopBudgetPolicy",
    "KnowledgeSaveArguments", "KnowledgeSaveSelection", "ToolCallProposal",
]

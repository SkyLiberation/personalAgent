from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.application.knowledge_lifecycle.models import (
    KnowledgeDeleteOperationView,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


ConversationInteractionMode = Literal["default", "auto"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationMessage(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class WorkingPlanStepProposal(_StrictModel):
    step_id: str = Field(min_length=1, max_length=100)
    description: str = Field(
        min_length=1,
        max_length=1_000,
        description=(
            "In the user's language, state the verifiable work result and its acceptance "
            "condition using the equivalent of 'Result: ...; Complete when: ...'; do not "
            "state only a search, read, tool call, or other activity."
        ),
    )
    status: Literal["pending", "completed"] = "pending"


class WorkingPlanProposal(_StrictModel):
    """A short-horizon user-visible contract for unresolved result obligations.

    Propose this without waiting for the user to name planning when it materially
    prevents omission, repeated work, or loss across a budget, context, process,
    or user-turn boundary. It is not required merely because several actions are
    possible.
    """

    goal: str = Field(min_length=1, max_length=4_000)
    steps: tuple[WorkingPlanStepProposal, ...] = Field(min_length=2, max_length=12)


class ConversationWorkingPlanStep(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1, max_length=100)
    description: str = Field(
        min_length=1,
        max_length=1_000,
        description=(
            "The admitted verifiable work result and its explicit completion condition."
        ),
    )
    status: Literal["pending", "completed"]
    completion_action_ids: tuple[str, ...] = ()


class ConversationWorkingPlan(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=4_000)
    steps: tuple[ConversationWorkingPlanStep, ...] = Field(min_length=2, max_length=12)


class ToolCallProposal(_StrictModel):
    kind: Literal["tool_call"] = "tool_call"
    action_id: str = Field(
        default_factory=lambda: f"act_{uuid4().hex[:16]}", min_length=1
    )
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    plan_step_id: str | None = Field(default=None, min_length=1, max_length=100)


class AgentDelegationProposal(_StrictModel):
    kind: Literal["agent_delegation"] = "agent_delegation"
    action_id: str = Field(
        default_factory=lambda: f"act_{uuid4().hex[:16]}", min_length=1
    )
    agent_id: str = Field(min_length=1)
    bounded_sub_goal: str = Field(min_length=1, max_length=4_000)
    context_projection_refs: tuple[str, ...] = ()
    expected_artifact_types: tuple[str, ...] = ()
    token_budget: int = Field(default=4_000, ge=1)
    cost_budget: float = Field(default=1.0, ge=0)
    time_budget_seconds: int = Field(default=180, ge=1, le=180)
    plan_step_id: str | None = Field(default=None, min_length=1, max_length=100)


class KnowledgeSaveSelection(_StrictModel):
    source_message_index: int = Field(ge=0)
    text_span: str = Field(min_length=1)


class KnowledgeSaveArguments(_StrictModel):
    selections: tuple[KnowledgeSaveSelection, ...] = Field(min_length=1)


class ReadActionOutputArguments(_StrictModel):
    """What the model may choose when re-reading an offloaded action output.

    Identity is deliberately absent. The artifact belongs to the interaction that
    produced it, so the principal and scope come from the already-resolved request
    context; a model-asserted user_id would be an unauthenticated claim.
    """

    resource_ref: ResourceRef = Field(
        description="The retrieval.resource_ref carried by the excerpted observation."
    )
    keyword: str = Field(
        default="",
        description=(
            "Locate lines containing this text anywhere in the full output. "
            "Leave empty to read sequentially from start_line."
        ),
    )
    start_line: int = Field(
        default=1,
        ge=1,
        description="First line of this window; use the previous next_start_line to continue.",
    )


class ListPersonalKnowledgeArguments(_StrictModel):
    limit: int = Field(default=20, ge=1, le=50)


class PersonalKnowledgeEvidenceCitation(_StrictModel):
    evidence_span_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator: str = ""
    claim_ids: tuple[str, ...] = ()


class PersonalKnowledgeEvidenceSnapshot(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1)
    citations: tuple[PersonalKnowledgeEvidenceCitation, ...]
    claim_summaries: tuple[str, ...]
    conflicted_claim_ids: tuple[str, ...]
    potential_conflicted_claim_ids: tuple[str, ...]
    reason: str = ""


class PrepareKnowledgeDeleteArguments(_StrictModel):
    target_knowledge_item_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1_000)


class InvestigationRequirementInput(_StrictModel):
    statement: str = Field(min_length=1, max_length=4_000)
    acceptance_contract: str = Field(min_length=1, max_length=4_000)


class StartDurableInvestigationArguments(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=8_000)
    requirements: tuple[InvestigationRequirementInput, ...] = Field(
        min_length=1,
        max_length=12,
    )


class SteerInvestigationProjectArguments(_StrictModel):
    statement: str = Field(min_length=1, max_length=4_000)
    waived_requirement_ids: tuple[str, ...] = ()
    added_requirements: tuple[InvestigationRequirementInput, ...] = Field(
        default=(),
        max_length=12,
    )


class InvestigationSubgoalProgress(_StrictModel):
    logical_subgoal_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    status: Literal["pending", "completed"]


class InvestigationRequirementProgress(_StrictModel):
    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    acceptance_contract: str = Field(min_length=1)
    status: str = Field(min_length=1)


class ConversationProjectSnapshot(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    plan_version: int | None = Field(default=None, ge=1)
    requirements: tuple[InvestigationRequirementProgress, ...]
    subgoals: tuple[InvestigationSubgoalProgress, ...]
    waiting_reasons: tuple[str, ...]


ActionProposal = ToolCallProposal | AgentDelegationProposal


class FinalMessage(_StrictModel):
    """Close the interaction only after required user-visible results are resolved.

    If available capabilities can continue an unresolved obligation now or in a
    later interaction, use ContinueTurnProposal with a working plan instead.
    """

    kind: Literal["final_message"] = "final_message"
    disposition: Literal["answer", "clarification_required", "limitation", "failed"]
    message: str = Field(min_length=1)
    resolved_plan_step_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Pending plan steps whose user-visible result is delivered directly by "
            "this answer. The runtime binds successful execution observations as "
            "evidence; this field makes the semantic completion claim."
        ),
    )


class ContinueTurnProposal(_StrictModel):
    """Continue required work through actions, a coordination boundary, or both.

    A new formal working plan waits for user review in default interaction mode.
    It may use ``wait_for_user=false`` only in caller-selected auto mode.
    """

    kind: Literal["continue_turn"] = "continue_turn"
    actions: tuple[ActionProposal, ...] = ()
    working_plan: WorkingPlanProposal | None = None
    wait_for_user: bool = False
    message: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def _action_ids_are_unique(self) -> "ContinueTurnProposal":
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("actions in one turn require unique action_id values")
        return self


class AgentTurnDecision(_StrictModel):
    """Object-root output for a turn that has no admitted working plan yet."""

    decision: ContinueTurnProposal | FinalMessage


class AgentTurnDecisionWithPlan(_StrictModel):
    """Object-root output while an admitted plan can now be closed or continued.

    ``FinalMessage`` comes first only in this lifecycle projection so structured
    output does not keep selecting an unchanged continuation after evidence is
    sufficient. Admission and the completion gate still reject premature closure.
    """

    decision: FinalMessage | ContinueTurnProposal


class EffectiveToolCapability(_StrictModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    safely_retryable: bool
    emits_verified_artifact: bool = False


class EffectiveAgentCapability(_StrictModel):
    agent_id: str
    description: str
    task_types: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()


class EffectiveCapabilities(_StrictModel):
    """Transient projection from registries and current availability."""

    tools: tuple[EffectiveToolCapability, ...] = ()
    agents: tuple[EffectiveAgentCapability, ...] = ()


class ReviewCriteria(_StrictModel):
    """The frozen standard one interaction's answer is verified against.

    Derived by the runtime once per interaction and committed, so neither a later
    model turn nor a restart can move the standard the answer is measured by.
    ``ungrounded_spans`` keeps the dropped derivations visible: a turn that could
    not trace any criterion to the user is distinguishable from one that was
    never a review request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    criteria: tuple[str, ...] = ()
    ungrounded_spans: tuple[str, ...] = ()

    @property
    def requires_review(self) -> bool:
        return bool(self.criteria)


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
    kind: Literal[
        "context_evidence",
        "tool_result",
        "agent_status",
        "agent_artifact",
    ]
    action_id: str
    capability_id: str
    status: Literal["succeeded", "failed", "running", "cancelled"]
    payload: dict[str, Any] = Field(default_factory=dict)
    plan_step_id: str | None = Field(default=None, min_length=1, max_length=100)


InteractionInput = DecisionFeedback | ActionObservation


class LoopBudgetPolicy(_StrictModel):
    policy_revision: str = "interaction-loop-v1"
    max_model_turns: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=12, ge=0)
    max_agent_calls: int = Field(default=4, ge=0)
    max_total_tokens: int = Field(default=32_000, ge=1)
    max_concurrency: int = Field(default=4, ge=1)


class CommittedUsage(_StrictModel):
    provider_usage_complete: bool = False
    model_calls: int | None = None
    model_turns: int = 0
    tool_calls: int = 0
    agent_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int = 0


class ConversationKnowledgeSaveCommand(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str
    action_id: str
    interaction_run_ref: str
    tenant_id: str
    owner_id: str
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


class PersonalKnowledgeCandidate(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_item_id: str = Field(min_length=1)
    title: str
    summary: str = ""
    state: Literal["active", "conflicted", "deprecated"]


class KnowledgeDeleteConfirmation(_StrictModel):
    """Response-only wrapper around the canonical lifecycle operation."""

    kind: Literal["knowledge_delete"] = "knowledge_delete"
    operation: KnowledgeDeleteOperationView


class ProjectReference(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class TurnContextComposition(_StrictModel):
    """What one decision turn's model input was actually made of.

    ``usage.total_tokens`` is one scalar, so it cannot say whether a turn's input
    was mostly capability definitions or mostly accumulated observations. Those
    are different problems with different remedies, and neither can be measured
    against a baseline without this breakdown.

    The four character counts are disjoint and sum to the assembled input, so a
    segment's share is a ratio rather than an estimate. Characters rather than
    tokens: the count is derived from the exact string sent, whereas a tokenizer
    would introduce a second, Provider-dependent measure of the same input.
    ``input_tokens`` is the Provider's own report for this turn, which is what
    makes the characters-to-tokens ratio observable instead of assumed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_index: int = Field(ge=0)
    capability_projection_chars: int = Field(ge=0)
    system_prompt_other_chars: int = Field(ge=0)
    conversation_messages_chars: int = Field(ge=0)
    typed_inputs_chars: int = Field(ge=0)
    input_tokens: int | None = None

    @property
    def total_chars(self) -> int:
        return (
            self.capability_projection_chars
            + self.system_prompt_other_chars
            + self.conversation_messages_chars
            + self.typed_inputs_chars
        )


class InteractionTrace(_StrictModel):
    revision: int = Field(default=1, ge=1)
    interaction_run_ref: str
    conversation_id: str = Field(min_length=1)
    principal: AuthenticatedPrincipal
    messages: tuple[ConversationMessage, ...]
    inputs: tuple[InteractionInput, ...] = ()
    usage: CommittedUsage = Field(default_factory=CommittedUsage)
    execution_order: tuple[str, ...] = ()
    concurrent_batches: tuple[tuple[str, ...], ...] = ()
    context_composition: tuple[TurnContextComposition, ...] = ()
    review_criteria: ReviewCriteria | None = None
    final_message: FinalMessage | None = None
    knowledge_save_operation: ConversationKnowledgeSaveOperation | None = None
    knowledge_delete_command_ref: str | None = None
    project_reference: ProjectReference | None = None
    working_plan: ConversationWorkingPlan | None = None


class ConversationTurnView(_StrictModel):
    interaction_run_ref: str = ""
    conversation_id: str
    disposition: Literal[
        "answer",
        "clarification_required",
        "confirmation_required",
        "background_started",
        "plan_ready",
        "limitation",
        "failed",
    ]
    message: ConversationMessage
    pending_confirmation: (
        ConversationKnowledgeSaveOperation | KnowledgeDeleteConfirmation | None
    ) = None
    project_reference: ProjectReference | None = None
    working_plan: ConversationWorkingPlan | None = None


__all__ = [
    "ActionObservation",
    "ActionProposal",
    "AgentDelegationProposal",
    "AgentTurnDecision",
    "CommittedUsage",
    "ContinueTurnProposal",
    "ConversationInteractionMode",
    "ConversationMessage",
    "ConversationWorkingPlan",
    "ConversationWorkingPlanStep",
    "ConversationTurnView",
    "ConversationKnowledgeSaveCommand",
    "ConversationKnowledgeSaveOperation",
    "ConversationKnowledgeSaveReceipt",
    "DecisionFeedback",
    "EffectiveAgentCapability",
    "EffectiveCapabilities",
    "EffectiveToolCapability",
    "FinalMessage",
    "InteractionTrace",
    "LoopBudgetPolicy",
    "InvestigationRequirementInput",
    "KnowledgeDeleteConfirmation",
    "KnowledgeSaveArguments",
    "KnowledgeSaveSelection",
    "ListPersonalKnowledgeArguments",
    "PersonalKnowledgeEvidenceCitation",
    "PersonalKnowledgeEvidenceSnapshot",
    "PrepareKnowledgeDeleteArguments",
    "ProjectReference",
    "SteerInvestigationProjectArguments",
    "ConversationProjectSnapshot",
    "InvestigationSubgoalProgress",
    "InvestigationRequirementProgress",
    "ReviewCriteria",
    "StartDurableInvestigationArguments",
    "ToolCallProposal",
    "TurnContextComposition",
    "WorkingPlanProposal",
    "WorkingPlanStepProposal",
    "PersonalKnowledgeCandidate",
]

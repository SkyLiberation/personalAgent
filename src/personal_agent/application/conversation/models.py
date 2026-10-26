from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, model_serializer
from personal_agent.capabilities.contracts.model import ModelActionInvocation, ModelAssistantMessage, ModelToolExchange, StructuredModelRequest, ModelActionDefinition, ModelOutputTransport, model_request_digest
from personal_agent.capabilities.contracts.research import (
    ResearchClaims,
    ResearchReview,
)
from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment,
    ConversationEvidenceReference,
)

from personal_agent.application.knowledge_lifecycle.models import (
    KnowledgeDeleteOperationView,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from personal_agent.application.conversation.observation_bounds import ReadWindowRequest
from personal_agent.application.artifacts.models import (
    ArtifactResourceItem,
    ArtifactWriteReceipt,
    ContentDigest,
)
from personal_agent.application.retrieval_experiment.models import (
    ExperimentToolArgs,
    ExperimentRecord,
)
from personal_agent.application.python_execution.models import (
    ExecutePythonArgs,
    PythonExecutionCommand,
    PythonExecutionFact,
    PythonExecutionReceipt,
)
from .tool_requests import WriteArtifactArgs
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey


ConversationInteractionMode = Literal["default", "auto"]
ConversationInteractionPhase = Literal[
    "ordinary", "review_plan", "deliver_final_result"
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationMessage(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class WorkingPlanStepProposal(_StrictModel):
    step_id: str | None = Field(default=None, min_length=1, max_length=100)
    description: str = Field(
        min_length=1,
        max_length=1_000,
        description=(
            "In the user's language, state the verifiable work result and its acceptance "
            "condition using the equivalent of 'Result: ...; Complete when: ...'; do not "
            "state only a search, read, tool call, or other activity."
        ),
    )
    status: Literal["pending", "in_progress", "completed"] = "pending"


class WorkingPlanProposal(_StrictModel):
    """A short-horizon user-visible contract for unresolved result obligations.

    Propose this without waiting for the user to name planning when it materially
    prevents omission, repeated work, or loss across a budget, context, process,
    or user-turn boundary. It is not required merely because several actions are
    possible.
    """

    goal: str = Field(min_length=1, max_length=4_000)
    grounding: str = Field(
        default="",
        max_length=4_000,
        description=(
            "Observed facts, constraints, trade-offs, and source references that "
            "justify this plan. State evidence already learned here; do not turn it "
            "into a future activity step. Leave empty when no grounding was needed."
        ),
    )
    steps: tuple[WorkingPlanStepProposal, ...] = Field(min_length=1, max_length=12)


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
    status: Literal["pending", "in_progress", "completed", "superseded"]
    completion_action_ids: tuple[str, ...] = ()


class ConversationWorkingPlan(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=4_000)
    grounding: str = Field(default="", max_length=4_000)
    steps: tuple[ConversationWorkingPlanStep, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _has_at_most_one_active_step(self) -> "ConversationWorkingPlan":
        if sum(step.status == "in_progress" for step in self.steps) > 1:
            raise ValueError("working plan can have at most one in_progress step")
        return self


class ToolCallProposal(_StrictModel):
    kind: Literal["tool_call"] = "tool_call"
    action_id: str = Field(
        default_factory=lambda: f"act_{uuid4().hex[:16]}", min_length=1
    )
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


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
    time_budget_seconds: int = Field(default=240, ge=1, le=240)


class KnowledgeSaveSelection(_StrictModel):
    source_message_index: int = Field(ge=0)
    text_span: str = Field(min_length=1)


class KnowledgeSaveArguments(_StrictModel):
    selections: tuple[KnowledgeSaveSelection, ...] = Field(min_length=1)


class ReadActionOutputArguments(ReadWindowRequest):
    """What the model may choose when re-reading an offloaded action output.

    Identity is deliberately absent. The artifact belongs to the interaction that
    produced it, so the principal and scope come from the already-resolved request
    context; a model-asserted user_id would be an unauthenticated claim.
    """

    resource_ref: ResourceRef = Field(
        description="The retrieval.resource_ref carried by the excerpted observation."
    )


class ListPersonalKnowledgeArguments(_StrictModel):
    limit: int = Field(default=20, ge=1, le=50)


class SearchPersonalKnowledgeArguments(_StrictModel):
    query: str = Field(
        min_length=1,
        max_length=4_000,
        description=(
            "The current user's positive request for which stored personal facts are needed."
        ),
    )
    limit: int = Field(default=8, ge=1, le=8)


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


ActionProposal = ToolCallProposal | AgentDelegationProposal


class FinalMessage(_StrictModel):
    """The writer owns ordered answer text and its evidence references."""

    kind: Literal["final_message"] = "final_message"
    disposition: Literal["answer", "clarification_required", "limitation", "failed"]
    segments: tuple[ConversationAnswerSegment, ...] = Field(min_length=1)

    @property
    def message(self) -> str:
        """Render the sole canonical body; never serialize a writable duplicate."""
        return "".join(segment.text for segment in self.segments)


class FinalSegmentEdit(_StrictModel):
    segment: int = Field(ge=1, description="基稿 segments 中从 1 开始的位置。")
    operation: Literal["add_references", "replace_references", "replace_segment"]
    references: tuple[ConversationEvidenceReference, ...] = ()
    text: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _edit_has_one_meaning(self):
        if (self.operation == "replace_segment") != (self.text is not None):
            raise ValueError("only replace_segment requires complete segment text")
        if self.operation == "add_references" and not self.references:
            raise ValueError("add_references requires at least one reference")
        return self


class FinalRevision(_StrictModel):
    kind: Literal["revise_final"] = "revise_final"
    base_ref: ResourceRef
    edits: tuple[FinalSegmentEdit, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _edits_do_not_overlap(self):
        if len({edit.segment for edit in self.edits}) != len(self.edits):
            raise ValueError("one submission may edit each base segment only once")
        return self


class SubmitFinalArguments(_StrictModel):
    message: str = Field(min_length=1)
    disposition: Literal["answer", "clarification_required", "limitation", "failed"]
    references: tuple[str, ...] = ()


class FinalSegmentEditArguments(_StrictModel):
    segment: int = Field(ge=1)
    operation: Literal["add_references", "replace_references", "replace_segment"]
    references: tuple[str, ...] = ()
    text: str | None = Field(default=None, min_length=1)


class ReviseFinalArguments(_StrictModel):
    base_resource_id: str = Field(min_length=1)
    edits: tuple[FinalSegmentEditArguments, ...] = Field(min_length=1)


class AnswerResultInvocation(_StrictModel):
    """A bound native operation; its module owns the business parameter decode."""
    call_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    arguments: dict[str, Any]


class SubmittedFinal(_StrictModel):
    """Journal-owned complete submission; never a successful verification fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["submitted_final"] = "submitted_final"
    action_id: str
    resource_ref: ResourceRef
    final: FinalMessage


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
    working_plan_call_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _action_ids_are_unique(self) -> "ContinueTurnProposal":
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("actions in one turn require unique action_id values")
        return self


class EffectiveToolCapability(_StrictModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    strict: bool = True
    read_only: bool
    planning_safe: bool
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
    interaction_phase: ConversationInteractionPhase = "ordinary"

    @property
    def requires_review(self) -> bool:
        return bool(self.criteria)

    @property
    def plan_review_required(self) -> bool:
        return self.interaction_phase == "review_plan"

    @property
    def final_result_required(self) -> bool:
        return self.interaction_phase == "deliver_final_result"


class ActionProtocolDiagnostic(_StrictModel):
    field_path: str
    error_type: str


class DecisionFeedback(_StrictModel):
    kind: Literal["decision_feedback"] = "decision_feedback"
    action_id: str
    action_name: str = ""
    reason_code: str
    action_diagnostics: tuple[ActionProtocolDiagnostic, ...] = ()
    rejected_action_invocations: tuple[ModelActionInvocation, ...] = ()
    working_plan_revision: int | None = Field(default=None, ge=1)
    decision_turn: int | None = Field(
        default=None,
        ge=1,
        description=(
            "ConversationService binds feedback to the model decision that produced it "
            "when committing inputs. None denotes feedback without a model decision."
        ),
    )
    message: str
    repairable_fields: tuple[str, ...] = ()
    immutable_fields: tuple[str, ...] = ()
    required_repair: str = ""
    disposition: Literal["revise", "clarify", "fail_closed"] = "revise"

    @model_validator(mode="after")
    def validate_repair_paths(self) -> "DecisionFeedback":
        overlap = set(self.repairable_fields).intersection(self.immutable_fields)
        if overlap:
            fields = ", ".join(sorted(overlap))
            raise ValueError(
                "repairable_fields and immutable_fields must be disjoint; "
                f"overlap: {fields}"
            )
        return self


class ActionObservation(_StrictModel):
    evidence_eligible: bool = True

    @model_serializer(mode="wrap")
    def serialize_evidence_boundary(self, handler):
        serialized = handler(self)
        if self.evidence_eligible:
            serialized.pop("evidence_eligible", None)
        return serialized
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
    execution_request_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        description=(
            "Canonical digest of the admitted tool name and arguments that produced "
            "this observation. It identifies an exact retry; it is not authorization."
        ),
    )


class ArtifactSourceInput(_StrictModel):
    """Readable metadata only; no source line has been returned by this input."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["artifact_source"] = "artifact_source"
    resource: ArtifactResourceItem


class _AcceptedToolRequest(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action_id: str = Field(min_length=1)
    execution_scope: ExecutionScope
    request_digest: ContentDigest
    plan_step_id: str | None = None


class AcceptedArtifactToolRequest(_AcceptedToolRequest):
    tool_name: Literal["write_artifact"] = "write_artifact"
    arguments: WriteArtifactArgs
    receipt: ArtifactWriteReceipt | None = None
    failure: ActionObservation | None = None


class AcceptedExperimentToolRequest(_AcceptedToolRequest):
    tool_name: Literal["retrieval_experiment"] = "retrieval_experiment"
    arguments: ExperimentToolArgs


class AcceptedPythonToolRequest(_AcceptedToolRequest):
    tool_name: Literal["execute_python"] = "execute_python"
    arguments: ExecutePythonArgs
    command: PythonExecutionCommand | None = None
    execution: PythonExecutionFact | None = None
    receipt: PythonExecutionReceipt | None = None


AcceptedToolRequest = Annotated[
    AcceptedArtifactToolRequest | AcceptedExperimentToolRequest | AcceptedPythonToolRequest,
    Field(discriminator="tool_name"),
]


class RunExecutionBudget(_StrictModel):
    """Read-only projection of the run's existing execution facts and reservations."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    consumed_seconds: float = Field(ge=0, allow_inf_nan=False)
    remaining_seconds: float = Field(ge=0, allow_inf_nan=False)
    unsettled_action_ids: tuple[str, ...] = ()


InteractionInput = (
    DecisionFeedback
    | ActionObservation
    | SubmittedFinal
    | ResearchClaims
    | ResearchReview
    | ArtifactSourceInput
)


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


class TurnContextComposition(_StrictModel):
    """What one decision turn's model input was actually made of.

    ``usage.total_tokens`` is one scalar, so it cannot say whether a turn's input
    was mostly capability definitions or mostly accumulated observations. Those
    are different problems with different remedies, and neither can be measured
    against a baseline without this breakdown.

    The five character counts are disjoint and sum to the provider-neutral
    assembled input, so a
    segment's share is a ratio rather than an estimate. Characters rather than
    tokens: message counts use the exact strings sent and action definitions use
    their canonical Port serialization; a tokenizer would introduce a second,
    Provider-dependent measure of the same input.
    ``input_tokens`` is the Provider's own report for this turn, which is what
    makes the characters-to-tokens ratio observable instead of assumed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_index: int = Field(ge=0)
    capability_projection_chars: int = Field(ge=0)
    model_action_definition_chars: int = Field(default=0, ge=0)
    system_prompt_other_chars: int = Field(ge=0)
    conversation_messages_chars: int = Field(ge=0)
    typed_inputs_chars: int = Field(ge=0)
    native_history_chars: int = Field(default=0, ge=0)
    prompt_version: str = ""
    input_tokens: int | None = None

    @property
    def total_chars(self) -> int:
        return (
            self.capability_projection_chars
            + self.model_action_definition_chars
            + self.system_prompt_other_chars
            + self.conversation_messages_chars
            + self.typed_inputs_chars
            + self.native_history_chars
        )


class ResearchExperimentDeliveryBinding(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    submission_ref: ResourceRef
    body_digest: ContentDigest
    frozen_ref: ResourceRef
    final_result_refs: tuple[ResourceRef, ...] = Field(min_length=1)
    candidate_development_refs: tuple[ResourceRef, ...] = ()
    manifest_digest: ContentDigest | None = None


class ResearchExperimentDelivery(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding: ResearchExperimentDeliveryBinding
    reproduction_ref: ResourceRef | None = None
    bundle_ref: ResourceRef | None = None
    report_ref: ResourceRef | None = None


class ModelCallDisposition(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    call_id: str = Field(min_length=1)
    operation: Literal["working_plan", "answer_result", "knowledge_save", "knowledge_delete"]
    status: Literal["accepted", "deferred", "prepared"]
    plan_id: str | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    operation_ref: str | None = None

    @model_validator(mode="after")
    def _bound_control_fact(self):
        if (self.plan_id is None) != (self.plan_revision is None):
            raise ValueError("plan disposition requires both identity and revision")
        if self.operation == "working_plan" and self.status == "accepted" and self.plan_id is None:
            raise ValueError("accepted plan disposition requires its canonical version")
        if self.status == "prepared":
            if self.operation not in ("knowledge_save", "knowledge_delete") or self.operation_ref is None:
                raise ValueError("prepared operation requires its canonical operation reference")
        elif self.operation_ref is not None:
            raise ValueError("operation reference is only valid for a prepared business operation")
        return self


class ResearchInformationNeed(_StrictModel):
    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")
    question: str = Field(min_length=1)
    status: Literal["answered", "ready", "needs_evidence", "delivery_check"]
    claim_ids: tuple[str, ...] = ()
    references: tuple[ConversationEvidenceReference, ...] = ()
    fit_reason: str = ""
    gap: str = ""

    @model_validator(mode="after")
    def account_for_answer_or_gap(self):
        if self.status == "answered" and not self.claim_ids:
            raise ValueError(
                "answered research requirement must identify current claims"
            )
        if self.status == "needs_evidence" and not self.gap.strip():
            raise ValueError(
                "research evidence gap must explain the necessary missing information"
            )
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("research requirement must not repeat claim identities")
        return self


class ResearchEvidenceSelection(_StrictModel):
    next_step: Literal["write", "acquire", "limit"]
    needs: tuple[ResearchInformationNeed, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def write_requires_selected_evidence(self):
        if self.next_step == "write" and not any(
            need.references for need in self.needs
        ):
            raise ValueError(
                "writing research claims requires selected returned evidence"
            )
        return self

    @property
    def references(self) -> tuple[ConversationEvidenceReference, ...]:
        return tuple(reference for need in self.needs for reference in need.references)


class InitialResearchInformationNeed(ResearchInformationNeed):
    """No current claim exists to identify as an answered research requirement."""

    status: Literal["ready", "needs_evidence", "delivery_check"]
    claim_ids: tuple[str, ...] = Field(default=(), max_length=0)


class InitialResearchEvidenceSelection(ResearchEvidenceSelection):
    needs: tuple[InitialResearchInformationNeed, ...] = Field(min_length=1)


class StoredModelRequest(_StrictModel):
    """Serializable original Port request; code type is restored only on schema match."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: str
    version: str
    messages: tuple[dict[str, Any], ...]
    output_type_name: str | None
    output_schema: dict[str, Any] | None
    context_projection_ref: str
    consumer_key: str | None = None
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    temperature: int | float
    max_tokens: int | None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    kind: Literal["structured", "tool_calling", "text"]
    action_definitions: tuple[ModelActionDefinition, ...]
    action_choice: Literal["none", "auto", "required"] | None
    response_format: dict[str, Any] | None
    output_transport: ModelOutputTransport | None
    extra_body: dict[str, Any] | None
    metadata: dict[str, Any]
    max_output_repairs: int
    model_history: tuple[ModelToolExchange, ...]
    request_digest: str

    @classmethod
    def from_request(cls, request):
        from dataclasses import fields
        values = {field.name: getattr(request, field.name) for field in fields(request)
                  if field.name != "output_type"}
        return cls(**values,
            output_type_name=f"{request.output_type.__module__}.{request.output_type.__qualname__}" if request.kind == "structured" else None,
            output_schema=request.output_type.model_json_schema() if request.kind == "structured" else None,
            request_digest=model_request_digest(request))

    def restore(self, output_type):
        if self.kind == "structured" and (self.output_type_name != f"{output_type.__module__}.{output_type.__qualname__}"
                or self.output_schema != output_type.model_json_schema()):
            raise ValueError("未完成模型调用的原输出契约已变化，不能嫁接新请求。")
        values = {name: getattr(self, name) for name in StructuredModelRequest.__dataclass_fields__
                  if name != "output_type"}
        values["messages"] = list(self.messages)
        request = StructuredModelRequest(**values, output_type=output_type)
        if model_request_digest(request) != self.request_digest:
            raise ValueError("已存模型调用原请求摘要不匹配。")
        return request


class ModelRequestReference(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: str
    request_digest: ContentDigest
    content_digest: ContentDigest
    context_projection_ref: str
    consumer_key: str | None = None
    output_type_name: str | None
    output_schema_digest: ContentDigest | None
    max_output_repairs: int = Field(ge=0)
    kind: Literal["structured", "tool_calling", "text"]


class ModelResponseReference(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=0)
    content_digest: ContentDigest


class ModelDecisionRecord(_StrictModel):
    """Journal-owned invocation and actual responses, including invalid output."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    request: ModelRequestReference
    turn_index: int | None = Field(default=None, ge=1)
    input_start: int = Field(ge=0)
    response_refs: tuple[ModelResponseReference, ...] = ()
    assistant: ModelAssistantMessage | None = None
    protocol_exchanges: tuple[ModelToolExchange, ...] = ()
    dispositions: tuple[ModelCallDisposition, ...] = ()
    blocked_by: HistoryItemKey | None = None
    status: Literal["pending", "decoded", "invalid", "failed"] = "pending"
    diagnostics: str | None = None
    consumed: bool = False
    research_selection: ResearchEvidenceSelection | None = None
    research_claim_ref: ResourceRef | None = None
    research_evidence_digest: ContentDigest | None = None
    research_criteria_digest: ContentDigest | None = None

    @model_validator(mode="after")
    def _original_references_are_bound(self):
        if self.request.invocation_id != self.invocation_id or self.request.operation != self.operation:
            raise ValueError("model request reference is bound to another invocation")
        if len({ref.attempt_id for ref in self.response_refs}) != len(self.response_refs):
            raise ValueError("model response references repeat an attempt identity")
        if any(ref.invocation_id != self.invocation_id or ref.sequence != index
               for index, ref in enumerate(self.response_refs)):
            raise ValueError("model response references are not in committed sequence")
        return self


class InteractionTrace(_StrictModel):
    answer_result_binding: AnswerResultConfig | None = None
    history_compaction: HistoryCompactionCheckpoint | None = None
    revision: int = Field(default=1, ge=1)
    interaction_run_ref: str
    conversation_id: str = Field(min_length=1)
    principal: AuthenticatedPrincipal
    messages: tuple[ConversationMessage, ...]
    input_artifact_refs: tuple[ResourceRef, ...] = ()
    accepted_tool_requests: tuple[AcceptedToolRequest, ...] = ()
    experiment_records: tuple[ExperimentRecord, ...] = ()
    research_experiment_delivery: ResearchExperimentDelivery | None = None
    deployment_digest: ContentDigest | None = None
    python_authorization_digest: ContentDigest | None = None
    run_deadline_at: AwareDatetime | None = None
    max_execution_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    inputs: tuple[InteractionInput, ...] = ()
    usage: CommittedUsage = Field(default_factory=CommittedUsage)
    execution_order: tuple[str, ...] = ()
    concurrent_batches: tuple[tuple[str, ...], ...] = ()
    context_composition: tuple[TurnContextComposition, ...] = ()
    model_decisions: tuple[ModelDecisionRecord, ...] = ()
    review_criteria: ReviewCriteria | None = None
    final_message: FinalMessage | None = None
    knowledge_save_operation: ConversationKnowledgeSaveOperation | None = None
    knowledge_delete_command_ref: str | None = None
    working_plan: ConversationWorkingPlan | None = None

    @property
    def python_profile_digest(self) -> ContentDigest | None:
        return self.python_authorization_digest or self.deployment_digest

    @model_validator(mode="after")
    def execution_authorization_is_bound(self) -> InteractionTrace:
        turns = [record.turn_index for record in self.model_decisions if record.turn_index is not None]
        if turns != sorted(set(turns)) or any(
            record.input_start > len(self.inputs) or (record.turn_index is not None and record.turn_index > self.usage.model_turns + 1)
            for record in self.model_decisions
        ):
            raise ValueError("native decision history is out of order or outside committed run facts")
        if self.python_authorization_digest is not None:
            if self.deployment_digest is not None:
                raise ValueError("同一运行不能同时绑定通用分析和检索部署")
            if self.run_deadline_at is None or self.max_execution_seconds is None:
                raise ValueError("Python授权必须绑定截止及执行总额度")
        return self


class ConversationTurnView(_StrictModel):
    resources: tuple[ArtifactResourceItem, ...] = ()
    interaction_run_ref: str = ""
    conversation_id: str
    disposition: Literal[
        "answer",
        "clarification_required",
        "confirmation_required",
        "plan_ready",
        "limitation",
        "failed",
    ]
    message: ConversationMessage
    pending_confirmation: (
        ConversationKnowledgeSaveOperation | KnowledgeDeleteConfirmation | None
    ) = None
    working_plan: ConversationWorkingPlan | None = None


__all__ = [
    "ActionObservation",
    "ActionProposal",
    "AgentDelegationProposal",
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
    "KnowledgeDeleteConfirmation",
    "KnowledgeSaveArguments",
    "KnowledgeSaveSelection",
    "ListPersonalKnowledgeArguments",
    "SearchPersonalKnowledgeArguments",
    "PersonalKnowledgeEvidenceCitation",
    "PersonalKnowledgeEvidenceSnapshot",
    "PrepareKnowledgeDeleteArguments",
    "ReviewCriteria",
    "ToolCallProposal",
    "TurnContextComposition",
    "WorkingPlanProposal",
    "WorkingPlanStepProposal",
    "PersonalKnowledgeCandidate",
]

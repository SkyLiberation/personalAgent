"""Derive the current Application lifecycle and frozen review contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    sealed_context_projection_ref,
)

from .models import (
    ConversationExecutionLifecycle,
    ConversationMessage,
    DecisionFeedback,
    ReviewCriteria,
)

_FEEDBACK_ACTION_ID = "interaction_turn"

_DERIVATION_INSTRUCTION = (
    "First classify execution_lifecycle. Use durable_investigation only when the latest "
    "user message requires work to continue independently after this response and later "
    "be queried, paused, resumed, or steered. Otherwise use conversation. For "
    "durable_investigation, lifecycle_source_span must be an exact substring of the latest "
    "user message proving that after-response lifecycle. For conversation use an empty "
    "lifecycle_source_span. If execution_lifecycle is durable_investigation, "
    "interaction_phase MUST be ordinary and phase_source_span MUST be empty: later querying "
    "or receiving a background result is not review_plan or deliver_final_result. The "
    "interaction phase rules below apply only to the conversation lifecycle. Do not choose "
    "tools, agents, plans, or implementation steps. "
    "Derive one mutually exclusive interaction phase from the latest user message. Use "
    "review_plan only when the latest message asks the Agent to return an intermediate plan, "
    "checklist, proposal, draft, or staged analysis and then wait for the user to review, "
    "confirm scope, supplement facts, or provide acceptance criteria. Use "
    "deliver_final_result when the latest message asks to finish, complete, deliver, or close "
    "out work that was previously staged for review. Otherwise use ordinary. Return "
    "phase_source_span as the exact substring of the latest user message that establishes "
    "review_plan or deliver_final_result; use an empty string for ordinary. Never use a span "
    "from an earlier message. "
    "Separately, return one requirement per acceptance condition the user states. For each "
    "requirement, criterion is a single testable condition phrased as what the sent text must "
    "or must not do, and source_span is the exact substring of a user message that states it. "
    "Copy source_span character for character from that message: do not translate, "
    "paraphrase, trim inner words, or merge two sentences. Every criterion must be "
    "self-contained and judgeable without conversation history. Before returning, inspect "
    "each criterion as if the reader cannot see any message. A criterion such as 'keep the "
    "original scope', 'use the same sources', or 'cover the items above' is still an "
    "acceptance condition and must not be omitted merely because the latest message does not "
    "repeat its objects. Rewrite it by explicitly listing every referenced subject, source "
    "type, and qualifier from the user's messages. Never return original scope, the above, "
    "unchanged, the same, as before, a pronoun, or an unstated set as the only identity of a "
    "required object. Preserve every proper noun and qualified product, project, organization, "
    "and repository name exactly as written by the user; never shorten or broaden a name, such "
    "as dropping a CLI, SDK, repository, or Agent qualifier. Return no requirement for a "
    "condition the user did not state; never invent one. A request to answer, explain, look "
    "something up, summarize, or save without explicit acceptance conditions has no "
    "requirements."
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewRequirement(_StrictModel):
    """One acceptance condition and its verbatim user-owned source."""

    criterion: str = Field(min_length=1, max_length=500)
    source_span: str = Field(min_length=1, max_length=2_000)


class InteractionIntentProposal(_StrictModel):
    """Model proposal for Application lifecycle, interaction phase, and review criteria."""

    requirements: tuple[ReviewRequirement, ...] = ()
    interaction_phase: Literal[
        "ordinary", "review_plan", "deliver_final_result"
    ] = "ordinary"
    phase_source_span: str = Field(default="", max_length=2_000)
    execution_lifecycle: ConversationExecutionLifecycle = "conversation"
    lifecycle_source_span: str = Field(default="", max_length=2_000)


class AdmittedInteractionIntent(_StrictModel):
    """Grounded lifecycle decision and independently admitted review contract."""

    review_criteria: ReviewCriteria = Field(default_factory=ReviewCriteria)
    execution_lifecycle: ConversationExecutionLifecycle = "conversation"
    lifecycle_grounded: bool = True
    lifecycle_source_span: str = ""


def admit_interaction_intent(
    proposal: InteractionIntentProposal,
    *,
    messages: Sequence[ConversationMessage],
) -> AdmittedInteractionIntent:
    """Ground semantic decisions only in verbatim user-authored text."""
    user_text = tuple(
        message.content for message in messages if message.role == "user"
    )
    latest_user_text = user_text[-1:] if user_text else ()
    lifecycle_span = proposal.lifecycle_source_span.strip()
    lifecycle_grounded = (
        proposal.execution_lifecycle == "conversation"
        and not lifecycle_span
    ) or (
        proposal.execution_lifecycle == "durable_investigation"
        and proposal.interaction_phase == "ordinary"
        and not proposal.phase_source_span.strip()
        and bool(lifecycle_span)
        and _appears_in(lifecycle_span, latest_user_text)
    )
    execution_lifecycle: ConversationExecutionLifecycle = (
        proposal.execution_lifecycle if lifecycle_grounded else "conversation"
    )

    criteria: list[str] = []
    ungrounded: list[str] = []
    phase_span = proposal.phase_source_span.strip()
    phase_grounded = bool(
        proposal.interaction_phase == "ordinary"
        or (
            execution_lifecycle == "conversation"
            and phase_span
            and latest_user_text
            and _appears_in(phase_span, latest_user_text)
        )
    )
    interaction_phase = (
        proposal.interaction_phase if phase_grounded else "ordinary"
    )
    if proposal.interaction_phase != "ordinary" and not phase_grounded:
        ungrounded.append(phase_span or "<missing phase source>")
    for requirement in proposal.requirements:
        span = requirement.source_span.strip()
        criterion = requirement.criterion.strip()
        if not criterion or not span or not _appears_in(span, user_text):
            ungrounded.append(span or requirement.source_span)
            continue
        if criterion not in criteria:
            criteria.append(criterion)
    return AdmittedInteractionIntent(
        review_criteria=ReviewCriteria(
            criteria=tuple(criteria),
            ungrounded_spans=tuple(ungrounded),
            interaction_phase=interaction_phase,
        ),
        execution_lifecycle=execution_lifecycle,
        lifecycle_grounded=lifecycle_grounded,
        lifecycle_source_span=lifecycle_span,
    )


def derive_interaction_intent(
    model_client: StructuredModelClient,
    *,
    messages: Sequence[ConversationMessage],
) -> tuple[
    AdmittedInteractionIntent,
    tuple[StructuredModelResponse[InteractionIntentProposal], ...],
    tuple[DecisionFeedback, ...],
]:
    """Derive one intent, revising a rejected lifecycle proposal at most once."""
    prompt_messages = [
        {"role": "system", "content": _DERIVATION_INSTRUCTION},
        *(message.model_dump(mode="json") for message in messages),
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="interaction_intent",
        version="v2",
        messages=prompt_messages,
        output_type=InteractionIntentProposal,
        context_projection_ref=sealed_context_projection_ref(
            purpose="interaction_intent", messages=prompt_messages,
        ),
        temperature=0,
        max_tokens=800,
        metadata={"component": "conversation_intent_admission"},
    ))
    admitted = admit_interaction_intent(response.value, messages=messages)
    if admitted.lifecycle_grounded:
        return admitted, (response,), ()

    feedback = lifecycle_revision_feedback()
    revision_messages = [
        {
            "role": "system",
            "content": (
                f"{_DERIVATION_INSTRUCTION}\n\n"
                "The previous lifecycle proposal was rejected by deterministic "
                "Admission. Revise only execution_lifecycle, lifecycle_source_span, "
                "interaction_phase, and phase_source_span. Requirements remain frozen "
                "and any changed requirements will be ignored. If the latest user "
                "message does require independent work after this response, copy the "
                "smallest exact proving substring. Otherwise return conversation with "
                "an empty lifecycle_source_span. Previous proposal: "
                f"{response.value.model_dump_json()}. Typed feedback: "
                f"{feedback.model_dump_json()}."
            ),
        },
        *(message.model_dump(mode="json") for message in messages),
    ]
    try:
        revision = model_client.generate(StructuredModelRequest(
            operation="interaction_intent",
            version="v2",
            messages=revision_messages,
            output_type=InteractionIntentProposal,
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_intent_revision",
                messages=revision_messages,
            ),
            temperature=0,
            max_tokens=800,
            metadata={
                "component": "conversation_intent_admission",
                "revision_attempt": 1,
            },
        ))
    except Exception:
        return admitted, (response,), (feedback,)

    revised_proposal = response.value.model_copy(update={
        "execution_lifecycle": revision.value.execution_lifecycle,
        "lifecycle_source_span": revision.value.lifecycle_source_span,
        "interaction_phase": revision.value.interaction_phase,
        "phase_source_span": revision.value.phase_source_span,
    })
    return (
        admit_interaction_intent(revised_proposal, messages=messages),
        (response, revision),
        (feedback,),
    )


def lifecycle_revision_feedback() -> DecisionFeedback:
    """Describe the only fields a rejected lifecycle proposal may revise."""
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="interaction_lifecycle_revision_required",
        message=(
            "The proposed execution lifecycle was not supported by an exact source "
            "span from the latest user message."
        ),
        repairable_fields=(
            "execution_lifecycle",
            "lifecycle_source_span",
            "interaction_phase",
            "phase_source_span",
        ),
        immutable_fields=("messages", "requirements"),
        required_repair=(
            "Return durable_investigation with an exact proving source span, or return "
            "conversation with an empty lifecycle_source_span."
        ),
    )


def ungrounded_criteria_feedback(criteria: ReviewCriteria) -> DecisionFeedback:
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="review_criteria_not_grounded",
        message=(
            "No success criterion for this request could be traced verbatim to a "
            "user message, so this answer is not held to a reviewed standard."
        ),
        repairable_fields=("message",),
        immutable_fields=("messages",),
        required_repair=(
            "If the request is to review specific text against stated requirements, "
            "ask the user to restate the requirement in one sentence. Otherwise "
            "answer the request directly and claim nothing about review or verification."
        ),
    )


def ungrounded_lifecycle_feedback() -> DecisionFeedback:
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="interaction_lifecycle_not_grounded",
        message=(
            "The proposed durable lifecycle could not be traced to the latest user "
            "message, so no background work was started."
        ),
        repairable_fields=("message",),
        immutable_fields=("messages",),
        required_repair=(
            "Continue in the Conversation lifecycle or ask whether the user needs work "
            "to continue independently after this response."
        ),
    )


def _appears_in(span: str, sources: Sequence[str]) -> bool:
    return any(span in source for source in sources)


__all__ = [
    "AdmittedInteractionIntent",
    "InteractionIntentProposal",
    "ReviewRequirement",
    "admit_interaction_intent",
    "derive_interaction_intent",
    "lifecycle_revision_feedback",
    "ungrounded_criteria_feedback",
    "ungrounded_lifecycle_feedback",
]

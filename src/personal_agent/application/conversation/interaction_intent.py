"""Derive unsupported delivery requirements and the frozen review contract."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.model import (
    ModelCapacityRefused,
    ModelInvocationUnavailable,
    StructuredOutputFailure,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    sealed_context_projection_ref,
)

from personal_agent.kernel.prompts import get_prompt

from .models import (
    ConversationMessage,
    DecisionFeedback,
    ReviewCriteria,
)
from .errors import ConversationUnavailable

_FEEDBACK_ACTION_ID = "interaction_turn"
# Thinking and the typed intent share the provider's completion budget.
_INTENT_OUTPUT_TOKEN_LIMIT = 32_768


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewRequirement(_StrictModel):
    """One acceptance condition and its verbatim user-owned source."""

    criterion: str = Field(min_length=1, max_length=500)
    source_span: str = Field(min_length=1, max_length=2_000)


class InteractionIntentProposal(_StrictModel):
    """Model proposal for delivery requirements, interaction phase, and review criteria."""

    requirements: tuple[ReviewRequirement, ...] = ()
    interaction_phase: Literal["ordinary", "review_plan", "deliver_final_result"] = (
        "ordinary"
    )
    phase_source_span: str = Field(default="", max_length=2_000)
    background_continuation_requested: bool = False
    background_source_span: str = Field(default="", max_length=2_000)


class AdmittedInteractionIntent(_StrictModel):
    """Grounded delivery requirement and independently admitted review contract."""

    review_criteria: ReviewCriteria = Field(default_factory=ReviewCriteria)
    background_continuation_requested: bool = False
    background_requirement_grounded: bool = True
    background_source_span: str = ""


def admit_interaction_intent(
    proposal: InteractionIntentProposal,
    *,
    messages: Sequence[ConversationMessage],
) -> AdmittedInteractionIntent:
    """Ground semantic decisions only in verbatim user-authored text."""
    user_text = tuple(message.content for message in messages if message.role == "user")
    latest_user_text = user_text[-1:] if user_text else ()
    background_span = proposal.background_source_span.strip()
    background_requirement_grounded = (
        not proposal.background_continuation_requested and not background_span
    ) or (
        proposal.background_continuation_requested
        and proposal.interaction_phase == "ordinary"
        and not proposal.phase_source_span.strip()
        and bool(background_span)
        and _appears_in(background_span, latest_user_text)
    )
    background_continuation_requested = bool(
        proposal.background_continuation_requested and background_requirement_grounded
    )

    criteria: list[str] = []
    ungrounded: list[str] = []
    phase_span = proposal.phase_source_span.strip()
    phase_grounded = bool(
        proposal.interaction_phase == "ordinary"
        or (
            not background_continuation_requested
            and phase_span
            and latest_user_text
            and _appears_in(phase_span, latest_user_text)
        )
    )
    interaction_phase = proposal.interaction_phase if phase_grounded else "ordinary"
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
        background_continuation_requested=background_continuation_requested,
        background_requirement_grounded=background_requirement_grounded,
        background_source_span=background_span,
    )


def derive_interaction_intent(
    model_client: StructuredModelClient,
    *,
    messages: Sequence[ConversationMessage],
    require_complete_usage: bool = False,
    deadline_at: datetime | None = None,
    remaining_tokens: int | None = None,
) -> tuple[
    AdmittedInteractionIntent,
    tuple[StructuredModelResponse[InteractionIntentProposal], ...],
    tuple[DecisionFeedback, ...],
]:
    """Derive one intent, revising an ungrounded background requirement at most once."""
    intent_prompt = get_prompt("conversation.interaction_intent")
    prompt_messages = [
        {"role": "system", "content": intent_prompt.template},
        *(message.model_dump(mode="json") for message in messages),
    ]
    response = model_client.generate(
        StructuredModelRequest(
            operation="interaction_intent",
            version=intent_prompt.version,
            messages=prompt_messages,
            output_type=InteractionIntentProposal,
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_intent",
                messages=prompt_messages,
            ),
            temperature=0,
            max_tokens=_INTENT_OUTPUT_TOKEN_LIMIT,
            metadata={"component": "conversation_intent_admission"},
        )
    )
    admitted = admit_interaction_intent(response.value, messages=messages)
    if admitted.background_requirement_grounded:
        return admitted, (response,), ()

    feedback = background_requirement_revision_feedback()
    if require_complete_usage and (
        response.input_tokens is None or response.output_tokens is None
    ):
        raise ConversationUnavailable(
            "模型消费尚有未知量，已停止新增付费调用；本次研究未完成。",
            reason_code="model_usage_unknown",
            failure_stage="application_budget",
            prior_responses=(response,),
        )
    if deadline_at is not None and datetime.now(UTC) >= deadline_at:
        raise ConversationUnavailable(
            "本次实验运行时限已到；已保留实际成果，本次研究未完成。",
            reason_code="run_deadline_exceeded",
            failure_stage="application_budget",
            prior_responses=(response,),
        )
    consumed = response.total_tokens
    if (
        consumed is None
        and response.input_tokens is not None
        and response.output_tokens is not None
    ):
        consumed = response.input_tokens + response.output_tokens
    if (
        remaining_tokens is not None
        and consumed is not None
        and consumed >= remaining_tokens
    ):
        raise ConversationUnavailable(
            "本次研究的已知模型消费达到额度，已停止新增付费调用。",
            reason_code="model_token_budget_exhausted",
            failure_stage="application_budget",
            prior_responses=(response,),
        )
    revision_messages = [
        {
            "role": "system",
            "content": (
                f"{intent_prompt.template}\n\n"
                "The previous background requirement proposal was rejected by deterministic "
                "Admission. Revise only background_continuation_requested, background_source_span, "
                "interaction_phase, and phase_source_span. Requirements remain frozen "
                "and any changed requirements will be ignored. If the latest user "
                "message does require independent work after this response, copy the "
                "smallest exact proving substring. Otherwise return false with "
                "an empty background_source_span. Previous proposal: "
                f"{response.value.model_dump_json()}. Typed feedback: "
                f"{feedback.model_dump_json()}."
            ),
        },
        *(message.model_dump(mode="json") for message in messages),
    ]
    try:
        revision = model_client.generate(
            StructuredModelRequest(
                operation="interaction_intent",
                version=intent_prompt.version,
                messages=revision_messages,
                output_type=InteractionIntentProposal,
                context_projection_ref=sealed_context_projection_ref(
                    purpose="interaction_intent_revision",
                    messages=revision_messages,
                ),
                temperature=0,
                max_tokens=_INTENT_OUTPUT_TOKEN_LIMIT,
                metadata={
                    "component": "conversation_intent_admission",
                    "revision_attempt": 1,
                },
            )
        )
    except ModelCapacityRefused as exc:
        exc.prior_responses = (response, *exc.prior_responses)
        raise
    except (ModelInvocationUnavailable, StructuredOutputFailure) as exc:
        if require_complete_usage:
            exc.prior_responses = (response, *exc.prior_responses)
            raise
        return admitted, (response,), (feedback,)
    except Exception:
        return admitted, (response,), (feedback,)

    revised_proposal = response.value.model_copy(
        update={
            "background_continuation_requested": (
                revision.value.background_continuation_requested
            ),
            "background_source_span": revision.value.background_source_span,
            "interaction_phase": revision.value.interaction_phase,
            "phase_source_span": revision.value.phase_source_span,
        }
    )
    return (
        admit_interaction_intent(revised_proposal, messages=messages),
        (response, revision),
        (feedback,),
    )


def background_requirement_revision_feedback() -> DecisionFeedback:
    """Describe the only fields an ungrounded background proposal may revise."""
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="background_requirement_revision_required",
        message=(
            "The proposed background continuation requirement was not supported by an exact source "
            "span from the latest user message."
        ),
        repairable_fields=(
            "background_continuation_requested",
            "background_source_span",
            "interaction_phase",
            "phase_source_span",
        ),
        immutable_fields=("messages", "requirements"),
        required_repair=(
            "Return true with an exact proving source span, or return false with an "
            "empty background_source_span."
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


def ungrounded_background_requirement_feedback() -> DecisionFeedback:
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="background_requirement_not_grounded",
        message=(
            "The proposed background continuation requirement could not be traced to the latest user "
            "message, so no background work was started."
        ),
        repairable_fields=("message",),
        immutable_fields=("messages",),
        required_repair=(
            "Continue in the current Conversation or ask whether the user needs work "
            "to continue after this response."
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
    "background_requirement_revision_feedback",
    "ungrounded_criteria_feedback",
    "ungrounded_background_requirement_feedback",
]

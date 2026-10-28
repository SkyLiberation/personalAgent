"""Derive unsupported delivery requirements and the frozen review contract."""

from __future__ import annotations

from collections.abc import Callable, Sequence
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

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .models import (
    ConversationMessage,
    DecisionFeedback,
    ReviewCriteria,
)
from .errors import ConversationFailure

_FEEDBACK_ACTION_ID = "interaction_turn"
# Thinking and the typed intent share the provider's completion budget.
_INTENT_OUTPUT_TOKEN_LIMIT = 32_768


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserTextReference(_StrictModel):
    """Coordinates in the original conversation, never model-authored text."""

    message_index: int = Field(ge=0, strict=True)
    line_start: int = Field(ge=1, strict=True)
    line_end: int = Field(ge=1, strict=True)


class ReviewRequirement(_StrictModel):
    """One acceptance condition and its verbatim user-owned source."""

    criterion: str = Field(min_length=1)
    source: UserTextReference


class InteractionIntentProposal(_StrictModel):
    """Model proposal for delivery requirements, interaction phase, and review criteria."""

    requirements: tuple[ReviewRequirement, ...] = ()
    interaction_phase: Literal["ordinary", "review_plan", "deliver_final_result"] = (
        "ordinary"
    )
    phase_source: UserTextReference | None = None
    background_continuation_requested: bool = False
    background_source: UserTextReference | None = None


class AdmittedInteractionIntent(_StrictModel):
    """Grounded delivery requirement and independently admitted review contract."""

    review_criteria: ReviewCriteria = Field(default_factory=ReviewCriteria)
    background_continuation_requested: bool = False
    background_requirement_grounded: bool = True
    background_source: UserTextReference | None = None


def _user_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True) or [""]


def resolve_user_text(
    source: UserTextReference | None,
    messages: Sequence[ConversationMessage],
    *,
    latest_only: bool = False,
) -> str | None:
    """Restore exact source bytes at the admitted message/line boundary."""
    if source is None or source.message_index >= len(messages):
        return None
    message = messages[source.message_index]
    if message.role != "user":
        return None
    if latest_only:
        latest = next(
            (index for index in range(len(messages) - 1, -1, -1)
             if messages[index].role == "user"),
            None,
        )
        if source.message_index != latest:
            return None
    lines = _user_lines(message.content)
    if source.line_end < source.line_start or source.line_end > len(lines):
        return None
    restored = "".join(lines[source.line_start - 1:source.line_end])
    return restored if restored.strip() else None


def materialize_intent_messages(
    messages: Sequence[ConversationMessage],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> list[dict[str, object]]:
    """Show one numbered copy; coordinates still resolve against the originals."""
    projected = []
    for index, message in enumerate(messages):
        item = message.model_dump(mode="json")
        if message.role == "user":
            lines = _user_lines(message.content)
            item["content"] = (
                prompts.render("conversation.intent.user_source_header", index=index, line_count=len(lines))
                + "".join(f"L{number}|{line}" for number, line in enumerate(lines, 1))
            )
        projected.append(item)
    return projected


def admit_interaction_intent(
    proposal: InteractionIntentProposal,
    *,
    messages: Sequence[ConversationMessage],
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> AdmittedInteractionIntent:
    """Ground semantic decisions only in verbatim user-authored text."""
    background_span = resolve_user_text(proposal.background_source, messages, latest_only=True)
    background_requirement_grounded = (
        not proposal.background_continuation_requested and proposal.background_source is None
    ) or (
        proposal.background_continuation_requested
        and proposal.interaction_phase == "ordinary"
        and proposal.phase_source is None
        and bool(background_span)
    )
    background_continuation_requested = bool(
        proposal.background_continuation_requested and background_requirement_grounded
    )

    criteria: list[str] = []
    ungrounded: list[str] = []
    phase_span = resolve_user_text(proposal.phase_source, messages, latest_only=True)
    phase_grounded = bool(
        (proposal.interaction_phase == "ordinary" and proposal.phase_source is None)
        or (
            not background_continuation_requested
            and proposal.interaction_phase != "ordinary"
            and phase_span
        )
    )
    interaction_phase = proposal.interaction_phase if phase_grounded else "ordinary"
    if not phase_grounded:
        ungrounded.append(_source_description(proposal.phase_source, prompts=prompts))
    for requirement in proposal.requirements:
        span = resolve_user_text(requirement.source, messages)
        criterion = requirement.criterion.strip()
        if not criterion or not span:
            ungrounded.append(_source_description(requirement.source, prompts=prompts))
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
        background_source=(proposal.background_source if background_continuation_requested else None),
    )


def derive_interaction_intent(
    model_client: StructuredModelClient,
    *,
    messages: Sequence[ConversationMessage],
    propagate_revision_failures: bool = False,
    deadline_at: datetime | None = None,
    remaining_tokens: int | None = None,
    generate: Callable[
        [StructuredModelRequest[InteractionIntentProposal]],
        StructuredModelResponse[InteractionIntentProposal],
    ] | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> tuple[
    AdmittedInteractionIntent,
    tuple[StructuredModelResponse[InteractionIntentProposal], ...],
    tuple[DecisionFeedback, ...],
]:
    """Derive one intent, revising an ungrounded background requirement at most once."""
    intent_prompt = prompts.get("conversation.interaction_intent")
    generate_model = generate or model_client.generate
    source_messages = materialize_intent_messages(messages, prompts=prompts)
    prompt_messages = [
        {"role": "system", "content": intent_prompt.template},
        *source_messages,
    ]
    response = generate_model(
        StructuredModelRequest(
            operation="interaction_intent",
            version=intent_prompt.version,
            messages=prompt_messages,
            output_type=InteractionIntentProposal,
            output_transport="prompted_json",
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_intent",
                messages=prompt_messages,
            ),
            temperature=0,
            max_tokens=_INTENT_OUTPUT_TOKEN_LIMIT,
            metadata={"component": "conversation_intent_admission"},
        )
    )
    admitted = admit_interaction_intent(response.value, messages=messages, prompts=prompts)
    if admitted.background_requirement_grounded:
        return admitted, (response,), ()

    feedback = background_requirement_revision_feedback(prompts=prompts)
    if deadline_at is not None and datetime.now(UTC) >= deadline_at:
        raise ConversationFailure(
            prompts.render("conversation.intent.deadline_exceeded"),
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
        raise ConversationFailure(
            prompts.render("conversation.intent.tokens_exhausted"),
            reason_code="model_token_budget_exhausted",
            failure_stage="application_budget",
            prior_responses=(response,),
        )
    revision_messages = [
        {
            "role": "system",
            "content": prompts.render(
                "conversation.intent.revision", intent_prompt=intent_prompt.template,
                proposal=response.value.model_dump_json(), feedback=feedback.model_dump_json(),
            ),
        },
        *source_messages,
    ]
    try:
        revision = generate_model(
            StructuredModelRequest(
                operation="interaction_intent_revision",
                version=intent_prompt.version,
                messages=revision_messages,
                output_type=InteractionIntentProposal,
                output_transport="prompted_json",
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
    except (ModelInvocationUnavailable, StructuredOutputFailure, ConversationFailure) as exc:
        if isinstance(exc, ConversationFailure) and exc.failure_stage not in {
            "provider_request", "provider_structured_decode",
        }:
            raise
        if propagate_revision_failures:
            exc.prior_responses = (response, *exc.prior_responses)
            raise
        return admitted, (response,), (feedback,)

    revised_proposal = response.value.model_copy(
        update={
            "background_continuation_requested": (
                revision.value.background_continuation_requested
            ),
            "background_source": revision.value.background_source,
            "interaction_phase": revision.value.interaction_phase,
            "phase_source": revision.value.phase_source,
        }
    )
    return (
        admit_interaction_intent(revised_proposal, messages=messages, prompts=prompts),
        (response, revision),
        (feedback,),
    )


def background_requirement_revision_feedback(
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> DecisionFeedback:
    """Describe the only fields an ungrounded background proposal may revise."""
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="background_requirement_revision_required",
        message=prompts.get("conversation.intent.background_revision.message").template,
        repairable_fields=(
            "background_continuation_requested",
            "background_source",
            "interaction_phase",
            "phase_source",
        ),
        immutable_fields=("messages", "requirements"),
        required_repair=prompts.get("conversation.intent.background_revision.repair").template,
    )


def ungrounded_criteria_feedback(
    criteria: ReviewCriteria, *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> DecisionFeedback:
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="review_criteria_not_grounded",
        message=prompts.get("conversation.intent.ungrounded_criteria.message").template,
        repairable_fields=("message",),
        immutable_fields=("messages",),
        required_repair=prompts.get("conversation.intent.ungrounded_criteria.repair").template,
    )


def ungrounded_background_requirement_feedback(
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> DecisionFeedback:
    return DecisionFeedback(
        action_id=_FEEDBACK_ACTION_ID,
        reason_code="background_requirement_not_grounded",
        message=prompts.get("conversation.intent.ungrounded_background.message").template,
        repairable_fields=("message",),
        immutable_fields=("messages",),
        required_repair=prompts.get("conversation.intent.ungrounded_background.repair").template,
    )


def _source_description(source: UserTextReference | None, *, prompts: PromptCatalog) -> str:
    return source.model_dump_json() if source is not None else prompts.render("conversation.intent.source_missing")


__all__ = [
    "AdmittedInteractionIntent",
    "InteractionIntentProposal",
    "ReviewRequirement",
    "UserTextReference",
    "admit_interaction_intent",
    "derive_interaction_intent",
    "background_requirement_revision_feedback",
    "ungrounded_criteria_feedback",
    "ungrounded_background_requirement_feedback",
]

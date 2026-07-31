"""Runtime-owned derivation of the success criteria a draft is verified against.

The interaction runtime, not the model, decides whether a turn is a review
request and what standard the answer is held to. Two things follow from that
split and are the reason this module exists:

* the model never authors the criteria it will be judged by, so it cannot
  weaken them -- deliberately or by paraphrase -- between turns;
* every criterion has to be traceable to the user's own words, which is checked
  mechanically here rather than requested in a prompt.

Only :func:`derive_review_criteria` touches the model port; everything else is
pure so each rejection branch is reachable from a unit test.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)

from .models import ConversationMessage, DecisionFeedback, ReviewCriteria

_FEEDBACK_ACTION_ID = "interaction_turn"

_DERIVATION_INSTRUCTION = (
    "Decide whether the latest user message asks for a draft, message, or text to be "
    "reviewed, validated, or revised against requirements the user states. "
    "Set requires_review true only for that case; a request to answer, explain, look "
    "something up, summarize, or save is not a review request. "
    "When it is a review request, return one requirement per acceptance condition the "
    "user states. For each requirement, criterion is a single testable condition phrased "
    "as what the sent text must or must not do, and source_span is the exact substring of a "
    "user message that states it. Copy source_span character for character from that "
    "message: do not translate, paraphrase, trim inner words, or merge two sentences. "
    "Return no requirement for a condition the user did not state; never invent one. "
    "When it is not a review request, return requires_review false with no requirements."
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewRequirement(_StrictModel):
    """One acceptance condition, plus the user text it is derived from.

    ``source_span`` is what makes the criterion auditable: it is checked verbatim
    against the conversation, so "the user asked for this" is an execution fact
    rather than a claim about the derivation.
    """

    criterion: str = Field(min_length=1, max_length=500)
    source_span: str = Field(min_length=1, max_length=2_000)


class ReviewIntent(_StrictModel):
    """Typed derivation output: is this a review request, and against what.

    There is deliberately no field for the text under review. The runtime
    verifies the answer the turn is about to send, so a separately carried
    "original draft" would only be a second, unverified candidate for it.
    """

    requires_review: bool
    requirements: tuple[ReviewRequirement, ...] = ()


def admit_review_intent(
    intent: ReviewIntent,
    *,
    messages: Sequence[ConversationMessage],
) -> ReviewCriteria:
    """Keep only criteria whose stated source appears verbatim in the conversation.

    A criterion whose ``source_span`` cannot be found is dropped rather than
    repaired: the runtime has no authority to decide what the user meant, and
    inventing a criterion here would recreate, on the runtime side, exactly the
    self-authored standard this module removes from the model.
    """
    if not intent.requires_review:
        return ReviewCriteria()
    user_text = tuple(
        message.content for message in messages if message.role == "user"
    )
    criteria: list[str] = []
    ungrounded: list[str] = []
    for requirement in intent.requirements:
        span = requirement.source_span.strip()
        criterion = requirement.criterion.strip()
        if not criterion or not span or not _appears_in(span, user_text):
            ungrounded.append(span or requirement.source_span)
            continue
        if criterion not in criteria:
            criteria.append(criterion)
    return ReviewCriteria(
        criteria=tuple(criteria),
        ungrounded_spans=tuple(ungrounded),
    )


def derive_review_criteria(
    model_client: StructuredModelClient,
    *,
    messages: Sequence[ConversationMessage],
) -> tuple[ReviewCriteria, int]:
    """Derive this turn's frozen criteria, with the tokens the derivation cost.

    The token count is returned so the derivation is charged to the same
    interaction budget as every other model call; a runtime-owned step is not a
    free one.
    """
    prompt_messages = [
        {"role": "system", "content": _DERIVATION_INSTRUCTION},
        *(message.model_dump(mode="json") for message in messages),
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="interaction_review_criteria",
        version="v1",
        messages=prompt_messages,
        output_type=ReviewIntent,
        context_projection_ref=sealed_context_projection_ref(
            purpose="interaction_review_criteria", messages=prompt_messages,
        ),
        temperature=0,
        max_tokens=800,
        metadata={"component": "conversation_review_admission"},
    ))
    token_count = response.total_tokens or (
        (response.input_tokens or 0) + (response.output_tokens or 0)
    )
    return admit_review_intent(response.value, messages=messages), token_count


def ungrounded_criteria_feedback(criteria: ReviewCriteria) -> DecisionFeedback:
    """Typed record that a review standard could not be traced to the user.

    Recorded in the journal so a turn that ran without verification is
    distinguishable from one that was never a review request. The turn then
    proceeds as an ordinary answer: fabricating a generic criterion would make
    the verifier's verdict meaningless.
    """
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
            "answer the request directly and claim nothing about review or "
            "verification."
        ),
    )


def _appears_in(span: str, sources: Sequence[str]) -> bool:
    return any(span in source for source in sources)


__all__ = [
    "ReviewIntent",
    "ReviewRequirement",
    "admit_review_intent",
    "derive_review_criteria",
    "ungrounded_criteria_feedback",
]

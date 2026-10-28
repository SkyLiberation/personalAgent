"""Atomically materialize writer-requested edits against the current complete submission."""
from collections.abc import Iterable

from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .citations import CitationBindingError, materialize_cited_draft
from .models import FinalMessage, FinalRevision, InteractionInput, SubmittedFinal


class FinalRevisionError(ValueError):
    pass


def materialize_final_revision(
    revision: FinalRevision,
    inputs: Iterable[InteractionInput],
    *,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> FinalMessage:
    inputs = tuple(inputs)
    base = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
    if base is None or base.resource_ref != revision.base_ref or base.final.disposition != "answer":
        raise FinalRevisionError(
            prompts.render("conversation.final_revision.base_unavailable")
        )
    segments = list(base.final.segments)
    for edit in revision.edits:
        if edit.segment > len(segments):
            raise FinalRevisionError(
                prompts.render("conversation.final_revision.segment_out_of_bounds")
            )
        old = segments[edit.segment - 1]
        references = edit.references
        if edit.operation == "add_references":
            references = tuple(dict.fromkeys((*old.references, *references)))
        segments[edit.segment - 1] = ConversationAnswerSegment(
            text=edit.text if edit.operation == "replace_segment" else old.text,
            references=references,
        )
    final = FinalMessage(disposition="answer", segments=tuple(segments))
    try:
        materialize_cited_draft(final.segments, inputs, prompts=prompts)
    except CitationBindingError as error:
        raise FinalRevisionError(
            prompts.render("conversation.final_revision.citation_rejected", error=error)
        ) from error
    return final

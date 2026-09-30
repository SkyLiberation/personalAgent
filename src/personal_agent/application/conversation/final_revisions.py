"""Atomically materialize writer-requested edits against the current complete submission."""
from collections.abc import Iterable

from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment

from .citations import CitationBindingError, materialize_cited_draft
from .models import FinalMessage, FinalRevision, InteractionInput, SubmittedFinal


class FinalRevisionError(ValueError):
    pass


def materialize_final_revision(revision: FinalRevision, inputs: Iterable[InteractionInput]) -> FinalMessage:
    inputs = tuple(inputs)
    base = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
    if base is None or base.resource_ref != revision.base_ref or base.final.disposition != "answer":
        raise FinalRevisionError("只能修订本次交互中最新可见的完整回答；请复制其 resource_ref，或提交完整新稿。")
    segments = list(base.final.segments)
    for edit in revision.edits:
        if edit.segment > len(segments):
            raise FinalRevisionError("修改位置不在当前基稿 segments 中；整批修改未应用。")
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
        materialize_cited_draft(final.segments, inputs)
    except CitationBindingError as error:
        raise FinalRevisionError(f"整批修改未应用：{error}") from error
    return final

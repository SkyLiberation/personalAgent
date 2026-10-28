"""English reading explanations and repairable binding feedback."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "conversation.read.explanation": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="line is the body line number; only the returned text is visible. next_read provides arguments to continue with read_artifact directly; reaching the end does not mean all preceding lines have been read.",
    ),
    "conversation.read.snapshot_mismatch": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The read snapshot does not match the requested resource reference.",
    ),
    "conversation.read.start_line_out_of_bounds": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="start_line is outside the body; the body has {total_lines} lines.",
    ),
    "conversation.read.start_column_out_of_bounds": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="start_column exceeds the body line length.",
    ),
    "conversation.read.capacity_insufficient": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The output capacity cannot fit body text and continuation arguments.",
    ),
    "conversation.search.explanation": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Only matching body lines are returned; very long lines include partial text with start_column and line_length. line can be used as read_artifact's start_line. Exhausted search results or no matches do not mean the full text has been read or the relevant meaning is absent.",
    ),
    "conversation.search.snapshot_mismatch": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The search snapshot does not match the requested resource reference.",
    ),
    "conversation.search.match_out_of_bounds": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The search match position is outside this body.",
    ),
    "conversation.search.offset_out_of_bounds": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The search result offset exceeds the number of matching records.",
    ),
    "conversation.search.record_capacity_exceeded": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="One matching record exceeds the output capacity. Truncated text has not been counted as complete evidence; use read_artifact to read the original resource.",
    ),
    "conversation.observation.omission_marker": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="\n... [{omitted} characters omitted from the middle] ...\n",
    ),
    "conversation.observation.window_explanation": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Only this sequential window is returned; an empty continuation means only that this suffix has ended, not that the full text has cumulatively been read.",
    ),
    "conversation.citations.range_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Reference {evidence_id} is not a visible continuous multiline range; the end line must be greater than the start line, and every line must have been returned in full.",
    ),
    "conversation.citations.coordinate_unavailable": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Coordinate {missing} in reference {evidence_id} was not returned in full or does not exist. Select lines actually visible in citations; continuous ranges cannot skip missing lines, and partial lines must retain their exact character ranges. Continue reading if other content is needed.",
    ),
    "conversation.final_revision.base_unavailable": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Only the latest visible complete answer in this interaction can be revised; copy its resource_ref or submit a complete new draft.",
    ),
    "conversation.final_revision.segment_out_of_bounds": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The edit position is outside the current base draft's segments; the entire batch of edits was not applied.",
    ),
    "conversation.final_revision.citation_rejected": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The entire batch of edits was not applied: {error}",
    ),
}

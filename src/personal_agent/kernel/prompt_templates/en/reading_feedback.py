"""English reading explanations and repairable binding feedback."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "conversation.read.explanation": PromptTranslation(
        source_version="2026-10-27.v2-file-path",
        version="2026-10-27.en.v2-file-path",
        template="line is the body line number; only the returned text is visible. next_read provides arguments to continue with read_file directly; reaching the end does not mean all preceding lines have been read.",
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
        source_version="v2-draft-ranges",
        version="v2-draft-ranges-en.1",
        template="Returns matching lines, with partial text and start_column and line_length for very long lines. Use line as read_file's start_line. For editable drafts, match_ranges gives patch coordinates; when match_ranges_truncated is true, narrow the search with a more specific term. Exhausted search results or no matches do not mean the full text has been read or the relevant meaning is absent.",
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
        source_version="2026-10-27.v2-file-path",
        version="2026-10-27.en.v2-file-path",
        template="One matching record exceeds the output capacity. Truncated text has not been counted as complete evidence; use read_file to read the original resource.",
    ),
}

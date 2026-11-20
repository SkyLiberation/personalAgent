"""English reading explanations and repairable binding feedback."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "conversation.read.explanation": PromptTranslation(
        source_version="2026-10-27.v3-read-tool",
        version="2026-10-27.en.v3-read-tool",
        template="line is the body line number; only the returned text is visible. next_read provides arguments to continue with the declared tool_read_file; reaching the end does not mean all preceding lines have been read.",
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
        source_version="v4-matching-line-path",
        version="v4-matching-line-path-en.1",
        template="Returns matching lines, with partial text and start_column and line_length for very long lines. Use line as start_line with the declared tool_read_file. Copy the exact source text when editing. Exhausted search results or no matches do not mean the full text has been read or the relevant meaning is absent.",
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
        source_version="2026-10-27.v3-read-tool",
        version="2026-10-27.en.v3-read-tool",
        template="One matching record exceeds the output capacity. Truncated text has not been counted as complete evidence; read the original text with the declared tool_read_file.",
    ),
}

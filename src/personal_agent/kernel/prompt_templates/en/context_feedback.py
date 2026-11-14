from personal_agent.kernel.prompt_registry import PromptTranslation

TRANSLATIONS = {
    "conversation.history.source_invalid": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The original source or principal for the history summary is no longer valid."),
    "conversation.history.snapshot_digest_invalid": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The history snapshot content digest does not match."),
    "conversation.history.coverage_invalid": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The history summary covers invalid or duplicate items."),
    "conversation.history.decision_missing": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The history summary references a model decision that does not exist."),
    "conversation.history.no_closed_progress": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="There is no newly closed history to compact; repeated compaction without progress has stopped."),
    "conversation.history.export_incomplete": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The original history export is incomplete; the original history must remain in the input."),
    "conversation.history.summary_incomplete": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The history summary is empty or truncated and was not activated."),
    "conversation.history.source_changed": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The history or checkpoint changed during summarization; usage is retained and the new state is not overwritten."),
    "conversation.history.activation_conflict": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The Journal revision conflicted while activating the history summary."),
    "conversation.history.no_safe_range": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="There is no safe coverage range for history summarization."),
    "conversation.knowledge_save.awaiting_confirmation": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="Please confirm whether to save the selected content. No long-term knowledge will be written before confirmation."),
    "conversation.knowledge_save.rejected": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="Saving was cancelled; no long-term knowledge was written."),
    "conversation.knowledge_save.executed": PromptTranslation(source_version="2026-10-27.v1", version="2026-10-27.en.v1", template="The selected content has been saved."),
}

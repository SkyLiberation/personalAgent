"""English instructions for writing model-produced artifacts."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "artifact.write.description": PromptTranslation(
        "v6-canonical-write", "v6-canonical-write-en.1",
        "Save a Python program, JSON configuration, or Markdown draft for this task. Creating or editing returns a new snapshot.",
    ),
    "artifact.create_action.description": PromptTranslation(
        "v1", "v1-en.1",
        "Create a Python, JSON, or Markdown draft. Submit the filename, media type, and complete content directly. "
        "Success returns a new draft reference. Use the patch tool to edit an existing draft.",
    ),
    "artifact.patch_action.description": PromptTranslation(
        "v1", "v1-en.1",
        "Edit a readable draft and return a new snapshot. Use the draft ID and coordinates established by reading or search. "
        "Every edit refers to the same base draft. Equal start and end positions insert text there. "
        "Prefer positive integer coordinates. Decimal digit strings without leading zeros are also accepted.\n\n"
        "Insertion example. Replace the draft ID and coordinates with the actual values when calling.\n\n"
        "```json\n"
        '{"base_resource_id":"draft_id","edits":'
        '[{"start_line":1,"start_column":1,"end_line":1,"end_column":1,"new_text":"Text to insert"}]}\n'
        "```",
    ),
}

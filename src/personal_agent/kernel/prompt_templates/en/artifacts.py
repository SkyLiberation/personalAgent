"""English instructions for writing model-produced artifacts."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "artifact.write.description": PromptTranslation(
        "v6-canonical-write", "v6-canonical-write-en.1",
        "Save a Python program, JSON configuration, or Markdown draft for this task. Creating or editing returns a new snapshot.",
    ),
    "artifact.create_action.description": PromptTranslation(
        "v2-literal-edit", "v2-literal-edit-en.1",
        "Create a Python, JSON, or Markdown draft. Submit the filename, media type, and complete content directly. "
        "Success returns a new draft reference. Use tool_edit to edit an existing draft.",
    ),
    "artifact.edit_action.description": PromptTranslation(
        "v3-literal-edit-newlines", "v3-literal-edit-newlines-en.1",
        "Edit an existing UTF-8 file by exact text replacement. Use its actual file_path. Allowed prefixes: {paths}. "
        "Use text from a read result or a recent write in this session. Matching preserves space and indentation "
        "and treats CRLF and LF as equivalent. The default requires exactly one match. "
        "Set replace_all to true to replace every match. "
        "Artifact edits return a new snapshot path. Task workspace files are updated in place.",
    ),
    "artifact.edit_action.workspace_guard": PromptTranslation(
        "v1", "v1-en.1",
        "Before editing a /tmp file, read that path with tool_read_file. A successful edit records the new "
        "version for the next edit. After Bash creates or changes a file, use tool_read_file to obtain its current version.",
    ),
    "artifact.edit_action.workspace_read": PromptTranslation(
        "v1", "v1-en.1",
        "You can also read task workspace files under /tmp. This read records the file version used by tool_edit.",
    ),
    **{
        f"artifact.edit_action.field.{name}": PromptTranslation("v1", "v1-en.1", description)
        for name, description in {
            "file_path": "Actual path identified by the read result or the Artifact write result.",
            "old_string": "Nonempty literal source text to replace, including its space and indentation.",
            "new_string": "Literal replacement text. An empty string deletes the match.",
            "replace_all": "Replace every match. Defaults to false, which requires exactly one match.",
        }.items()
    },
}

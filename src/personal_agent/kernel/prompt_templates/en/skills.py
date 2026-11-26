"""English Conversation skill discovery and loading metadata."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "skills.load_description": PromptTranslation(
        "v3", "v3-en.1",
        "Load a skill's full instructions by its exact name in the current step's catalog. If the user "
        "names a skill or the task clearly matches its summary, call this tool on its own before "
        "related task actions, then follow the loaded instructions.",
    ),
    "skills.catalog": PromptTranslation(
        "v1", "v1-en.1", "## Skills available in this session\n<available_skills>\n{catalog}\n</available_skills>",
    ),
    "skills.loaded": PromptTranslation(
        "v1", "v1-en.1",
        "Loaded skill `{skill_name}`. Follow the full instructions below. When a rule has a default "
        "and an exception, check the user's actual words against the stated conditions. Use the default "
        "unless the request supplies evidence for the exception."
        "\n\n<skill_instructions>\n{instructions}\n</skill_instructions>",
    ),
    "skills.repeat_notice": PromptTranslation(
        "skill-repeat-v1", "skill-repeat-v1-en.1",
        "[Runtime repeat-call reminder] You have loaded skill `{skill_name}` {count} times in a row "
        "with identical arguments. Review the latest result first. If work remains, choose a next "
        "action that advances the task. If you have enough information, deliver the result.",
    ),
    "skills.unknown": PromptTranslation(
        "v2", "v2-en.1", "This skill is unavailable. Check its exact name in the current session skill catalog.",
    ),
    "skills.resource_base": PromptTranslation(
        "skill-resources-v1", "skill-resources-v1-en.1",
        "<skill_resources>\nThe read-only skill resource directory in Bash is `{path}`. "
        "Resolve relative `scripts/` paths from the instructions against this directory. Call `tool_bash` when the task requires it.\n"
        "</skill_resources>",
    ),
    "skills.scripts_unavailable": PromptTranslation(
        "v1", "v1-en.1",
        "The skill's packaged scripts could not be prepared for Bash. Check its installed scripts/ paths, file types, and input size.",
    ),
    "skills.scope_changed": PromptTranslation(
        "v1", "v1-en.1", "The session skill scope changed. Start a new session.",
    ),
}

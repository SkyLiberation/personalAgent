"""English instructions for writing model-produced artifacts."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "artifact.write.description": PromptTranslation(
        "v2-artifact-id-selection", "v2-artifact-id-selection-en.1",
        "Save a new Python program or JSON configuration for this task; create makes a new artifact, "
        "while patch uses base_resource_id to select a currently readable draft and creates a new snapshot "
        "using that exact snapshot's line and column ranges. A successful save does not mean execution or research is complete.",
    ),
}

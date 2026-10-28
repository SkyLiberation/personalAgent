"""Complete, independently versioned English production prompt resources."""

from personal_agent.kernel.prompt_registry import PromptTranslation

from . import (
    artifacts,
    ask,
    conversation,
    graph,
    interaction_verification,
    python_execution,
    research,
    retrieval_experiment,
    runtime,
    web_search,
    supplemental,
    reading_feedback,
    owned_feedback,
    result_feedback,
    service_feedback,
    context_feedback,
)
from .metadata import METADATA_TRANSLATIONS


TRANSLATIONS: dict[str, PromptTranslation] = {}
for _module in (ask, artifacts, conversation, graph, interaction_verification,
                runtime, research, retrieval_experiment, python_execution, web_search,
                supplemental, reading_feedback, owned_feedback, result_feedback,
                service_feedback, context_feedback):
    if set(TRANSLATIONS) & set(_module.TRANSLATIONS):
        raise ValueError("Duplicate English prompt names")
    TRANSLATIONS.update(_module.TRANSLATIONS)

__all__ = ["TRANSLATIONS", "METADATA_TRANSLATIONS"]

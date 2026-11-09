from __future__ import annotations

import re
from dataclasses import replace
from importlib import import_module
from types import MappingProxyType

from personal_agent.kernel.prompt_registry import PromptCatalog, PromptSpec
from personal_agent.kernel.prompt_templates.ask import PROMPTS as ASK_PROMPTS
from personal_agent.kernel.prompt_templates.artifacts import PROMPTS as ARTIFACT_PROMPTS
from personal_agent.kernel.prompt_templates.conversation import PROMPTS as CONVERSATION_PROMPTS
from personal_agent.kernel.prompt_templates.graph import PROMPTS as GRAPH_PROMPTS
from personal_agent.kernel.prompt_templates.interaction_verification import (
    PROMPTS as INTERACTION_VERIFICATION_PROMPTS,
)
from personal_agent.kernel.prompt_templates.runtime import PROMPTS as RUNTIME_PROMPTS
from personal_agent.kernel.prompt_templates.research import PROMPTS as RESEARCH_PROMPTS
from personal_agent.kernel.prompt_templates.retrieval_experiment import (
    PROMPTS as RETRIEVAL_EXPERIMENT_PROMPTS,
)
from personal_agent.kernel.prompt_templates.python_execution import (
    PROMPTS as PYTHON_EXECUTION_PROMPTS,
)
from personal_agent.kernel.prompt_templates.web_search import PROMPTS as WEB_SEARCH_PROMPTS
from personal_agent.kernel.prompt_templates.supplemental import PROMPTS as SUPPLEMENTAL_PROMPTS
from personal_agent.kernel.prompt_templates.reading_feedback import PROMPTS as READING_FEEDBACK_PROMPTS
from personal_agent.kernel.prompt_templates.owned_feedback import PROMPTS as OWNED_FEEDBACK_PROMPTS
from personal_agent.kernel.prompt_templates.result_feedback import PROMPTS as RESULT_FEEDBACK_PROMPTS
from personal_agent.kernel.prompt_templates.service_feedback import PROMPTS as SERVICE_FEEDBACK_PROMPTS
from personal_agent.kernel.prompt_templates.context_feedback import PROMPTS as CONTEXT_FEEDBACK_PROMPTS


_PROMPTS: dict[str, PromptSpec] = {}
for _group in (ASK_PROMPTS, ARTIFACT_PROMPTS, CONVERSATION_PROMPTS, GRAPH_PROMPTS,
               INTERACTION_VERIFICATION_PROMPTS, RUNTIME_PROMPTS, RESEARCH_PROMPTS,
               RETRIEVAL_EXPERIMENT_PROMPTS, PYTHON_EXECUTION_PROMPTS,
               WEB_SEARCH_PROMPTS, SUPPLEMENTAL_PROMPTS, READING_FEEDBACK_PROMPTS,
               OWNED_FEEDBACK_PROMPTS, RESULT_FEEDBACK_PROMPTS, SERVICE_FEEDBACK_PROMPTS,
               CONTEXT_FEEDBACK_PROMPTS):
    if set(_group) & set(_PROMPTS):
        raise ValueError(f"Duplicate prompt names: {set(_group) & set(_PROMPTS)}")
    _PROMPTS.update(_group)


def _variables(template: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{([A-Za-z_]\w*)\}", template))


_LANGUAGE_RESOURCES = MappingProxyType({"en": "personal_agent.kernel.prompt_templates.en"})


def create_prompt_catalog(language: str = "zh") -> PromptCatalog:
    if language == "zh":
        return DEFAULT_PROMPTS
    try:
        resource = import_module(_LANGUAGE_RESOURCES[language])
    except KeyError as exc:
        raise ValueError(f"Unknown prompt language: {language}") from exc
    translations = resource.TRANSLATIONS
    if set(translations) != set(_PROMPTS):
        raise ValueError(f"Incomplete {language} prompt catalog: {set(_PROMPTS) ^ set(translations)}")
    translated = {}
    for name, source in _PROMPTS.items():
        target = translations[name]
        if source.version != target.source_version:
            raise ValueError(f"Stale {language} prompt translation: {name}")
        if not target.template.strip() or _variables(source.template) != _variables(target.template):
            raise ValueError(f"Invalid {language} prompt translation: {name}")
        translated[name] = replace(source, version=target.version, template=target.template)
    return PromptCatalog(language, translated, resource.METADATA_TRANSLATIONS)


DEFAULT_PROMPTS = PromptCatalog("zh", _PROMPTS, {})

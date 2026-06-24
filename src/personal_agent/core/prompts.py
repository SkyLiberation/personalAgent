from __future__ import annotations

from typing import Any

from personal_agent.core.prompt_registry import PromptSpec
from personal_agent.core.prompt_templates.ask import PROMPTS as ASK_PROMPTS
from personal_agent.core.prompt_templates.graph import PROMPTS as GRAPH_PROMPTS
from personal_agent.core.prompt_templates.router import PROMPTS as ROUTER_PROMPTS
from personal_agent.core.prompt_templates.thread import PROMPTS as THREAD_PROMPTS


_PROMPTS: dict[str, PromptSpec] = {
    **ASK_PROMPTS,
    **GRAPH_PROMPTS,
    **ROUTER_PROMPTS,
    **THREAD_PROMPTS,
}


def get_prompt(name: str) -> PromptSpec:
    try:
        return _PROMPTS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown prompt: {name}") from exc


def render_prompt(name: str, **variables: Any) -> str:
    return get_prompt(name).render(**variables)

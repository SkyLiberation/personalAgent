"""Pure materialization of the model-visible Conversation decision contract."""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .models import EffectiveCapabilities
from .model_actions import model_visible_capability_policy
from .answer_results import DirectAnswerResult
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig


def build_interaction_system_prompt(
    capabilities: EffectiveCapabilities,
    *,
    capability_projection: str | None = None,
    explicit_research_entry: bool = False,
    answer_result: DirectAnswerResult | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Materialize the system instructions and run capabilities."""
    answer_result = answer_result or DirectAnswerResult(AnswerResultConfig(), prompts=prompts)
    verification_note = prompts.get(
        "conversation.answer.verification.required" if answer_result.verification_enabled
        else "conversation.answer.verification.none"
    ).template
    projection = capability_projection or model_visible_capability_policy(
        capabilities, prompts=prompts
    )
    return prompts.get("conversation.action").render(
        research_entry=(prompts.get("conversation.research_entry.explicit").template
                        if explicit_research_entry else ""),
        verification_note="" if explicit_research_entry else verification_note,
        projection=projection,
    )


__all__ = ["build_interaction_system_prompt"]

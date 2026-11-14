"""Pure materialization of the model-visible Conversation decision contract."""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .budget import RemainingInteractionBudget
from .models import (
    ConversationWorkingPlan,
    EffectiveCapabilities,
)
from .model_actions import model_visible_capability_policy
from .answer_results import DirectAnswerResult, ClaimAnswerResult
from .working_plan import render_working_plan
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig


def build_interaction_system_prompt(
    capabilities: EffectiveCapabilities,
    remaining: RemainingInteractionBudget,
    *,
    capability_projection: str | None = None,
    working_plan: ConversationWorkingPlan | None = None,
    working_plan_active_only: bool = False,
    explicit_research_entry: bool = False,
    answer_result: DirectAnswerResult | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Materialize exactly the prompt and budget projection sent to the model."""
    answer_result = answer_result or ClaimAnswerResult(AnswerResultConfig(), prompts=prompts)
    verification_note = prompts.get(
        "conversation.answer.verification.required" if answer_result.verification_enabled
        else "conversation.answer.verification.none"
    ).template
    projection = capability_projection or model_visible_capability_policy(
        capabilities, prompts=prompts
    )
    time_budget_note = (
        prompts.render("conversation.time_budget_snapshot", seconds=remaining.wall_seconds_at_input)
        if remaining.wall_seconds_at_input is not None else ""
    )
    plan_context = (
        render_working_plan(working_plan, prompts=prompts, active_only=working_plan_active_only)
        if working_plan is not None else ""
    )
    return prompts.get("conversation.action").render(
        research_entry=(prompts.get("conversation.research_entry.explicit").template
                        if explicit_research_entry else ""),
        research_delivery_policy=(
            "" if explicit_research_entry
            else prompts.get(answer_result.delivery_prompt_name).template
        ),
        verification_note="" if explicit_research_entry else verification_note,
        remaining=prompts.render(
            "conversation.context.budget", model_turns=remaining.model_turns,
            tool_calls=remaining.tool_calls, agent_calls=remaining.agent_calls, tokens=remaining.tokens,
        ),
        time_budget_note=time_budget_note,
        plan_context=plan_context,
        projection=projection,
    )


__all__ = ["build_interaction_system_prompt"]

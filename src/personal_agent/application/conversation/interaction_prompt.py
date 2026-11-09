"""Pure materialization of the model-visible Conversation decision contract."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .models import (
    CommittedUsage,
    ConversationInteractionMode,
    ConversationWorkingPlan,
    EffectiveCapabilities,
    LoopBudgetPolicy,
)
from .models import ReviewCriteria
from .model_actions import model_visible_capability_policy_json
from .answer_results import DirectAnswerResult, ClaimAnswerResult
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig


class RemainingInteractionBudget(BaseModel):
    """Read-only budget facts at decision input construction, never a new limit."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_turns: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    agent_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    wall_seconds_at_input: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def model_visible_working_plan_json(
    working_plan: ConversationWorkingPlan,
) -> str:
    """Expose semantic plan content without runtime identity or evidence bindings."""
    return json.dumps(
        {
            "goal": working_plan.goal,
            "grounding": working_plan.grounding,
            "steps": [
                {
                    "step_id": step.step_id,
                    "description": step.description,
                    "status": step.status,
                }
                for step in working_plan.steps
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_interaction_system_prompt(
    capabilities: EffectiveCapabilities,
    usage: CommittedUsage,
    *,
    budget_policy: LoopBudgetPolicy | None = None,
    capability_projection: str | None = None,
    working_plan: ConversationWorkingPlan | None = None,
    interaction_mode: ConversationInteractionMode = "default",
    explicit_research_entry: bool = False,
    wall_seconds_at_input: float | None = None,
    answer_result: DirectAnswerResult | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Materialize exactly the prompt and budget projection sent to the model."""
    policy = budget_policy or LoopBudgetPolicy()
    answer_result = answer_result or ClaimAnswerResult(AnswerResultConfig(), prompts=prompts)
    verification_note = prompts.get(
        "conversation.answer.verification.required" if answer_result.verification_enabled
        else "conversation.answer.verification.none"
    ).template
    projection = capability_projection or model_visible_capability_policy_json(
        capabilities, prompts=prompts
    )
    remaining = RemainingInteractionBudget(
        model_turns=max(0, policy.max_model_turns - usage.model_turns),
        tool_calls=max(0, policy.max_tool_calls - usage.tool_calls),
        agent_calls=max(0, policy.max_agent_calls - usage.agent_calls),
        tokens=max(0, policy.max_total_tokens - usage.total_tokens),
        wall_seconds_at_input=wall_seconds_at_input,
    )
    time_budget_note = (
        prompts.get("conversation.time_budget_snapshot").template
        if wall_seconds_at_input is not None
        else ""
    )
    plan_context = (
        prompts.get("conversation.plan_context").render(
            total=str(len(working_plan.steps)),
            completed=str(
                sum(step.status == "completed" for step in working_plan.steps)
            ),
            pending=str(sum(step.status == "pending" for step in working_plan.steps)),
            active=str(
                sum(step.status == "in_progress" for step in working_plan.steps)
            ),
            superseded=str(
                sum(step.status == "superseded" for step in working_plan.steps)
            ),
            plan_json=model_visible_working_plan_json(working_plan),
        )
        if working_plan is not None
        else ""
    )
    plan_control = prompts.render("conversation.interaction_mode", interaction_mode=interaction_mode)
    return prompts.get("conversation.action").render(
        research_entry=(prompts.get("conversation.research_entry.explicit").template
                        if explicit_research_entry else ""),
        research_delivery_policy=(
            "" if explicit_research_entry
            else prompts.get(answer_result.delivery_prompt_name).template
        ),
        verification_note="" if explicit_research_entry else verification_note,
        remaining=json.dumps(remaining.model_dump(exclude_none=True)),
        time_budget_note=time_budget_note,
        plan_context=plan_context,
        projection=projection,
        plan_control=plan_control,
    )


def build_requirements_context(
    review_criteria: ReviewCriteria | None, *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Render the frozen interpretation once, keeping each original sentence."""
    if review_criteria is None or not review_criteria.requires_review:
        return ""
    entries = []
    for index, criterion in enumerate(review_criteria.criteria, start=1):
        prefix = f"{index}. "
        entries.append(prefix + criterion.replace("\n", "\n" + " " * len(prefix)))
    return prompts.get("conversation.requirements").render(
        criteria_text="\n".join(entries),
    )


__all__ = ["build_interaction_system_prompt", "build_requirements_context", "model_visible_working_plan_json"]

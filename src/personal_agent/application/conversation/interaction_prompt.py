"""Pure materialization of the model-visible Conversation decision contract."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.prompts import get_prompt

from .models import (
    CommittedUsage,
    ConversationInteractionMode,
    ConversationWorkingPlan,
    EffectiveCapabilities,
    LoopBudgetPolicy,
)
from .models import ReviewCriteria
from .model_actions import model_visible_capability_policy_json


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
    review_criteria: ReviewCriteria | None = None,
    *,
    budget_policy: LoopBudgetPolicy | None = None,
    capability_projection: str | None = None,
    working_plan: ConversationWorkingPlan | None = None,
    interaction_mode: ConversationInteractionMode = "default",
    finalization_mode: bool = False,
    explicit_research_entry: bool = False,
    wall_seconds_at_input: float | None = None,
) -> str:
    """Materialize exactly the prompt and budget projection sent to the model."""
    policy = budget_policy or LoopBudgetPolicy()
    projection = capability_projection or model_visible_capability_policy_json(
        capabilities
    )
    remaining = RemainingInteractionBudget(
        model_turns=max(0, policy.max_model_turns - usage.model_turns),
        tool_calls=max(0, policy.max_tool_calls - usage.tool_calls),
        agent_calls=max(0, policy.max_agent_calls - usage.agent_calls),
        tokens=max(0, policy.max_total_tokens - usage.total_tokens),
        wall_seconds_at_input=wall_seconds_at_input,
    )
    time_budget_note = (
        get_prompt("conversation.time_budget_snapshot").template
        if wall_seconds_at_input is not None
        else ""
    )
    plan_context = (
        get_prompt("conversation.plan_context").render(
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
    plan_control = "调用方交互模式（权威数据）：" + interaction_mode
    if finalization_mode:
        return get_prompt("conversation.final").render(
            requirements=_requirements_instruction(review_criteria),
            remaining=json.dumps(remaining.model_dump(exclude_none=True)),
            time_budget_note=time_budget_note,
            plan_context=plan_context,
            projection=projection,
            plan_control=plan_control,
        )
    return get_prompt("conversation.action").render(
        research_entry=get_prompt(
            "conversation.research_entry.explicit"
            if explicit_research_entry
            else "conversation.research_entry.automatic"
        ).template,
        research_delivery_policy=(
            "" if explicit_research_entry
            else get_prompt("conversation.research_delivery_policy").template
        ),
        finalization_progress=get_prompt(
            "conversation.finalization_progress.experiment"
            if explicit_research_entry else "conversation.finalization_progress.ordinary"
        ).template,
        requirements=_requirements_instruction(review_criteria),
        remaining=json.dumps(remaining.model_dump(exclude_none=True)),
        time_budget_note=time_budget_note,
        plan_context=plan_context,
        projection=projection,
        plan_control=plan_control,
    )


def _requirements_instruction(review_criteria: ReviewCriteria | None) -> str:
    if review_criteria is None or not review_criteria.requires_review:
        return ""
    return get_prompt("conversation.requirements").render(
        criteria_json=json.dumps(list(review_criteria.criteria), ensure_ascii=False),
    )


__all__ = ["build_interaction_system_prompt", "model_visible_working_plan_json"]

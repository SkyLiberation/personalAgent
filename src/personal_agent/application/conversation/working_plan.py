"""Admission rules for the optional Conversation working plan."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .models import (
    ActionObservation,
    ContinueTurnProposal,
    ConversationWorkingPlan,
    ConversationWorkingPlanStep,
    DecisionFeedback,
    WorkingPlanProposal,
    WorkingPlanStepProposal,
    WORKING_PLAN_MAX_STEPS,
)


def render_working_plan(plan: ConversationWorkingPlan, *, prompts: PromptCatalog, active_only: bool = False) -> str:
    steps = "\n".join(prompts.render(
        "conversation.context.plan_step", step_id=step.step_id,
        status=prompts.get(f"conversation.context.state.{step.status}").template,
        description=step.description,
    ) for step in plan.steps if not active_only or step.status in {"pending", "in_progress"})
    grounding = (prompts.render("conversation.context.plan_basis", grounding=plan.grounding)
                 if plan.grounding else "")
    empty = "conversation.plan.no_active_steps" if active_only else "conversation.plan.empty"
    return prompts.render("conversation.plan_context", goal=plan.goal, grounding=grounding,
                          steps=steps or prompts.get(empty).template)


def supersede_pending_working_plan(
    working_plan: ConversationWorkingPlan,
    affected: Callable[[ConversationWorkingPlanStep], bool] | None = None,
) -> ConversationWorkingPlan:
    """End provisional obligations without fabricating execution evidence."""
    changed_ids = {
        step.step_id
        for step in working_plan.steps
        if step.status in {"pending", "in_progress"} and (affected is None or affected(step))
    }
    if not changed_ids:
        return working_plan
    return working_plan.model_copy(update={
        "revision": working_plan.revision + 1,
        "steps": tuple(
            step.model_copy(update={"status": "superseded"})
            if step.step_id in changed_ids else step
            for step in working_plan.steps
        ),
    })


def _same_plan_content(
    proposal: WorkingPlanProposal,
    current: ConversationWorkingPlan,
) -> bool:
    return (
        proposal.goal == current.goal
        and proposal.grounding == current.grounding
        and tuple(
            (step.step_id, step.description, step.status, step.goal_item_ids)
            for step in proposal.steps
        )
        == tuple(
            (step.step_id, step.description, step.status, step.goal_item_ids)
            for step in current.steps
        )
    )


def _starts_new_plan(
    current: ConversationWorkingPlan | None,
    *,
    result_delivered: bool,
) -> bool:
    """Progress is revisable; only a committed answer closes its plan lifecycle."""
    return current is None or result_delivered


def admit_plan_wait_boundary(
    decision: ContinueTurnProposal,
) -> DecisionFeedback | None:
    if not decision.wait_for_user:
        return None
    if decision.working_plan is None or not decision.working_plan.steps:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_required_for_wait",
            message="Waiting for user review requires a formal working plan.",
            repairable_fields=("working_plan", "wait_for_user"),
            required_repair=(
                "Provide the plan to review, or set wait_for_user false if no plan "
                "review is required."
            ),
        )
    if decision.actions:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="waiting_plan_has_actions",
            message="A turn waiting for plan review cannot execute actions.",
            repairable_fields=("actions",),
            immutable_fields=("working_plan", "wait_for_user"),
            required_repair="Return the same reviewable plan with an empty actions list.",
        )
    return None


def required_plan_review_feedback() -> DecisionFeedback:
    return DecisionFeedback(
        action_id="working_plan",
        reason_code="plan_review_boundary_required",
        message=(
            "The user explicitly requested a reviewable plan before execution, but "
            "the proposed final message has no admitted working plan."
        ),
        repairable_fields=("working_plan", "wait_for_user"),
        immutable_fields=("messages", "inputs"),
        required_repair=(
            "If required evidence is not yet present, use only planning_safe actions. "
            "Then call the working-plan action with the grounded plan, "
            "wait_for_user true, and no actions; do not place a prose plan in FinalMessage."
        ),
    )


def admit_plan_review(
    decision: ContinueTurnProposal,
    *,
    current: ConversationWorkingPlan | None,
    review_required: bool,
    unsafe_execution_started: bool = False,
    result_delivered: bool = False,
) -> DecisionFeedback | None:
    proposal = decision.working_plan
    if proposal is None or proposal.steps is None or not (review_required or decision.wait_for_user):
        return None
    starts_new_plan = _starts_new_plan(current, result_delivered=result_delivered)
    if starts_new_plan and unsafe_execution_started:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_review_too_late",
            message=(
                "A new plan cannot be sent for review "
                "after execution outside the planning-safe exploration boundary "
                "has started."
            ),
            repairable_fields=("working_plan",),
            immutable_fields=("inputs",),
            required_repair=(
                "Continue the already-started work without introducing a formal plan, "
                "or return a truthful final limitation. On a new turn, create the plan "
                "before executing any non-planning-safe action."
            ),
        )
    if decision.wait_for_user:
        return None
    return DecisionFeedback(
        action_id="working_plan",
        reason_code="working_plan_review_required",
        message=(
            "The user requested to review the working plan before execution."
        ),
        repairable_fields=("wait_for_user", "actions"),
        immutable_fields=("working_plan",),
        required_repair=(
            "Return the working plan with wait_for_user true and no business actions."
        ),
    )


def admit_working_plan(
    proposal: WorkingPlanProposal,
    *,
    current: ConversationWorkingPlan | None,
    inputs: tuple,
    wait_for_user: bool = False,
    result_delivered: bool = False,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
    active_goal_item_ids: frozenset[str] | None = None,
) -> tuple[DecisionFeedback | None, ConversationWorkingPlan | None]:
    if proposal.steps is None:
        return None, current
    starts_new_plan = _starts_new_plan(current, result_delivered=result_delivered)
    previous = None if starts_new_plan else current
    goal = proposal.goal if proposal.goal is not None else previous.goal if previous else None
    if goal is None or (starts_new_plan and not proposal.steps):
        return DecisionFeedback(
            action_id="working_plan", reason_code="working_plan_create_incomplete",
            message=prompts.get("conversation.plan.create_incomplete").template,
            repairable_fields=("goal", "steps"),
            required_repair=prompts.get("conversation.plan.create_repair").template,
        ), None

    current_by_id = {step.step_id: step for step in previous.steps if step.status != "superseded"} if previous else {}
    steps = proposal.steps
    step_ids = tuple(step.step_id for step in steps if step.step_id is not None)
    if len(step_ids) != len(set(step_ids)):
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="duplicate_plan_step_id",
            message="Working-plan step IDs must be unique.",
            repairable_fields=("steps",),
            required_repair="Return one unique step_id per user-visible obligation.",
        ), None
    unknown = sorted(set(step_ids) - current_by_id.keys())
    changed_bound = [
        step.step_id for step in steps if step.step_id in current_by_id
        and current_by_id[step.step_id].completion_action_ids
        and (step.description != current_by_id[step.step_id].description
             or (step.goal_item_ids is not None and step.goal_item_ids != current_by_id[step.step_id].goal_item_ids))
    ]
    if unknown or changed_bound:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_step_binding_invalid",
            message=prompts.render(
                "conversation.plan.step_binding_invalid", unknown=unknown, changed_bound=changed_bound,
            ),
            repairable_fields=("steps",), required_repair=prompts.render("conversation.plan.step_binding_repair"),
        ), None

    if proposal.merge and previous is not None:
        updates = {step.step_id: step for step in steps if step.step_id is not None}
        merged = []
        for step_id, current_step in current_by_id.items():
            update = updates.get(step_id)
            if update is None:
                update = WorkingPlanStepProposal(
                    step_id=step_id, description=current_step.description, status=current_step.status,
                )
            elif "status" not in update.model_fields_set:
                update = update.model_copy(update={"status": current_step.status})
            merged.append(update)
        steps = (*merged, *(step for step in steps if step.step_id is None))

    if len(steps) > WORKING_PLAN_MAX_STEPS:
        return DecisionFeedback(
            action_id="working_plan", reason_code="working_plan_step_limit",
            message=prompts.render("conversation.plan.step_limit", limit=WORKING_PLAN_MAX_STEPS),
            repairable_fields=("steps", "merge"),
            required_repair=prompts.render("conversation.plan.step_limit_repair", limit=WORKING_PLAN_MAX_STEPS),
        ), None
    steps = tuple(step.model_copy(update={
        "goal_item_ids": step.goal_item_ids if step.goal_item_ids is not None else
        current_by_id[step.step_id].goal_item_ids if step.step_id in current_by_id else (),
    }) for step in steps)
    if active_goal_item_ids is not None and any(
        step.status in {"pending", "in_progress"}
        and (not step.goal_item_ids or not set(step.goal_item_ids) <= active_goal_item_ids)
        for step in steps
    ):
        return DecisionFeedback(action_id="working_plan", reason_code="working_plan_goal_binding_invalid",
            message=prompts.get("conversation.plan.goal_binding_invalid").template,
            repairable_fields=("steps",),
            required_repair=prompts.get("conversation.plan.goal_binding_invalid").template), None
    active_count = sum(step.status == "in_progress" for step in steps)
    if wait_for_user and active_count:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="waiting_plan_has_active_step",
            message="A working plan awaiting user review cannot have an active step.",
            repairable_fields=("steps",),
            immutable_fields=("wait_for_user",),
            required_repair="Keep every unfinished step pending until the user authorizes execution.",
        ), None
    if active_count > 1:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_active_step_required",
            message=prompts.render("conversation.plan.active_step_limit"),
            repairable_fields=("steps",),
            immutable_fields=("goal", "grounding"),
            required_repair=prompts.render("conversation.plan.active_step_repair"),
        ), None
    grounding = proposal.grounding if proposal.grounding is not None else previous.grounding if previous else ""
    resolved = proposal.model_copy(update={"goal": goal, "grounding": grounding, "steps": steps})
    if previous is not None and _same_plan_content(resolved, previous):
        return None, current

    def materialize_step(step):
        step_id = step.step_id or f"wstep_{uuid4().hex[:16]}"
        existing = current_by_id.get(step_id)
        execution_ids = tuple(item.action_id for item in inputs if isinstance(item, ActionObservation)
                              and item.status == "succeeded" and item.plan_step_id == step_id)
        historical = existing.completion_action_ids if existing else ()
        return ConversationWorkingPlanStep(step_id=step_id, description=step.description, status=step.status,
            completion_action_ids=tuple(dict.fromkeys((*historical, *execution_ids))), goal_item_ids=step.goal_item_ids)
    plan = ConversationWorkingPlan(
        plan_id=(
            current.plan_id
            if current is not None and not starts_new_plan
            else f"wplan_{uuid4().hex[:16]}"
        ),
        revision=(current.revision + 1 if current is not None else 1),
        goal=goal,
        grounding=grounding,
        steps=tuple(materialize_step(step) for step in steps),
    )
    return None, plan


def active_working_plan_step_id(
    working_plan: ConversationWorkingPlan | None,
) -> str | None:
    """Return the canonical active step without inferring one from action content."""
    if working_plan is None:
        return None
    active = tuple(
        step.step_id for step in working_plan.steps if step.status == "in_progress"
    )
    return active[0] if len(active) == 1 else None


def admit_continue_turn_progress(
    decision: ContinueTurnProposal,
    *,
    previous_plan: ConversationWorkingPlan | None,
    admitted_plan: ConversationWorkingPlan | None,
) -> DecisionFeedback | None:
    """Reject only a ContinueTurn that cannot change any runtime-owned fact.

    ``admit_working_plan`` returns the existing object for an identical Plan.
    Concrete actions, a genuinely changed Plan, or an explicit user wait are
    observable progress.  Everything else would consume another model turn
    while presenting the next decision with the same execution state.
    """
    if decision.actions or decision.wait_for_user:
        return None
    if (decision.working_plan_call_id is not None and decision.working_plan is not None
            and decision.working_plan.steps is None):
        return None
    if decision.working_plan is not None and admitted_plan is not previous_plan:
        return None
    return DecisionFeedback(
        action_id="continue_turn",
        reason_code="continue_turn_no_progress",
        working_plan_revision=(
            admitted_plan.revision if admitted_plan is not None else None
        ),
        message=(
            "ContinueTurn did not change the working plan, execute an action, "
            "or wait for the user."
        ),
        repairable_fields=(
            "actions",
            "working_plan",
            "wait_for_user",
        ),
        immutable_fields=("messages", "inputs"),
        required_repair=(
            "Keep an unchanged plan unchanged and submit the next necessary concrete "
            "action, a genuinely revised plan, wait for the user, or call control_submit_final with the complete answer."
        ),
    )


def complete_working_plan(
    working_plan: ConversationWorkingPlan,
    *,
    inputs: tuple,
) -> ConversationWorkingPlan:
    """Materialize a result already accepted by semantic and completion gates."""
    unresolved_ids = tuple(
        step.step_id
        for step in working_plan.steps
        if step.status in {"pending", "in_progress"}
    )
    if not unresolved_ids:
        return working_plan
    successful_action_ids_by_step = {
        step_id: tuple(
            item.action_id
            for item in inputs
            if isinstance(item, ActionObservation)
            and item.status == "succeeded"
            and item.plan_step_id == step_id
        )
        for step_id in unresolved_ids
    }
    unresolved = set(unresolved_ids)
    return working_plan.model_copy(update={
        "revision": working_plan.revision + 1,
        "steps": tuple(
            step.model_copy(update={
                "status": "completed",
                "completion_action_ids": successful_action_ids_by_step[step.step_id],
            })
            if step.step_id in unresolved
            else step
            for step in working_plan.steps
        ),
    })
__all__ = [
    "active_working_plan_step_id",
    "admit_continue_turn_progress",
    "admit_plan_review",
    "admit_plan_wait_boundary",
    "admit_working_plan",
    "complete_working_plan",
    "required_plan_review_feedback",
    "supersede_pending_working_plan",
]

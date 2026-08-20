"""Admission rules for the optional Conversation working plan."""

from __future__ import annotations

from uuid import uuid4

from .models import (
    ActionObservation,
    ContinueTurnProposal,
    ConversationInteractionMode,
    ConversationWorkingPlan,
    ConversationWorkingPlanStep,
    DecisionFeedback,
    WorkingPlanProposal,
)


def _same_plan_content(
    proposal: WorkingPlanProposal,
    current: ConversationWorkingPlan,
) -> bool:
    return (
        proposal.goal == current.goal
        and proposal.grounding == current.grounding
        and tuple(
            (step.step_id, step.description, step.status)
            for step in proposal.steps
        )
        == tuple(
            (step.step_id, step.description, step.status)
            for step in current.steps
        )
    )


def _starts_new_plan(
    proposal: WorkingPlanProposal,
    current: ConversationWorkingPlan | None,
) -> bool:
    if current is None:
        return True
    return (
        all(step.status == "completed" for step in current.steps)
        and not _same_plan_content(proposal, current)
    )


def admit_plan_wait_boundary(
    decision: ContinueTurnProposal,
) -> DecisionFeedback | None:
    if not decision.wait_for_user:
        return None
    if decision.working_plan is None:
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
        immutable_fields=("messages", "interaction_mode", "inputs"),
        required_repair=(
            "If required evidence is not yet present, use only planning_safe actions. "
            "Then return ContinueTurnProposal with the grounded working_plan, "
            "wait_for_user true, and no actions; do not place a prose plan in FinalMessage."
        ),
    )


def admit_new_plan_interaction_mode(
    decision: ContinueTurnProposal,
    *,
    current: ConversationWorkingPlan | None,
    interaction_mode: ConversationInteractionMode,
    unsafe_execution_started: bool = False,
) -> DecisionFeedback | None:
    proposal = decision.working_plan
    if proposal is None or interaction_mode == "auto":
        return None
    starts_new_plan = _starts_new_plan(proposal, current)
    if not starts_new_plan:
        return None
    if unsafe_execution_started:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_review_too_late",
            message=(
                "Default interaction mode cannot introduce a formal working plan "
                "after execution outside the planning-safe exploration boundary "
                "has started."
            ),
            repairable_fields=("working_plan",),
            immutable_fields=("interaction_mode", "inputs"),
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
            "Default interaction mode requires user review before a new formal "
            "working plan can execute."
        ),
        repairable_fields=("wait_for_user", "actions"),
        immutable_fields=("interaction_mode", "working_plan"),
        required_repair=(
            "Return the new working plan with wait_for_user true and no actions. "
            "Only the caller can choose auto interaction mode."
        ),
    )


def admit_working_plan(
    proposal: WorkingPlanProposal,
    *,
    current: ConversationWorkingPlan | None,
    inputs: tuple,
) -> tuple[DecisionFeedback | None, ConversationWorkingPlan | None]:
    step_ids = tuple(step.step_id for step in proposal.steps)
    if len(step_ids) != len(set(step_ids)):
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="duplicate_plan_step_id",
            message="Working-plan step IDs must be unique.",
            repairable_fields=("steps",),
            required_repair="Return one unique step_id per user-visible obligation.",
        ), None
    starts_new_plan = _starts_new_plan(proposal, current)
    if current is not None and not starts_new_plan and _same_plan_content(
        proposal,
        current,
    ):
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_no_change",
            message="The proposed working plan is identical to the current plan.",
            repairable_fields=(
                "working_plan",
                "actions",
                "resolved_plan_step_ids",
            ),
            immutable_fields=("messages", "inputs"),
            required_repair=(
                "Do not resubmit the plan. If the user-visible answer delivers every "
                "pending obligation, return FinalMessage with exactly those IDs in "
                "resolved_plan_step_ids; otherwise perform or revise only the remaining "
                "obligation."
            ),
        ), None
    successful_action_ids_by_step = {
        step_id: tuple(
            item.action_id
            for item in inputs
            if isinstance(item, ActionObservation)
            and item.status == "succeeded"
            and item.plan_step_id == step_id
        )
        for step_id in step_ids
    }
    current_by_id = (
        {step.step_id: step for step in current.steps}
        if current is not None and not starts_new_plan
        else {}
    )
    proposed_by_id = {step.step_id: step for step in proposal.steps}
    for step_id, existing in current_by_id.items():
        if existing.status != "completed":
            continue
        candidate = proposed_by_id.get(step_id)
        if candidate is None or (
            candidate.description != existing.description
            or candidate.status != existing.status
        ):
            return DecisionFeedback(
                action_id="working_plan",
                reason_code="completed_plan_step_immutable",
                message=f"Completed step {step_id!r} cannot be removed or rewritten.",
                immutable_fields=("steps",),
                required_repair="Preserve every completed step byte-for-byte.",
            ), None
    def materialize_step(step):
        existing = current_by_id.get(step.step_id)
        if existing is not None and existing.status == "completed":
            return existing
        return ConversationWorkingPlanStep(
            **step.model_dump(),
            completion_action_ids=(
                successful_action_ids_by_step[step.step_id]
                if step.status == "completed"
                else ()
            ),
        )
    plan = ConversationWorkingPlan(
        plan_id=(
            current.plan_id
            if current is not None and not starts_new_plan
            else f"wplan_{uuid4().hex[:16]}"
        ),
        revision=(current.revision + 1 if current is not None else 1),
        goal=proposal.goal,
        grounding=proposal.grounding,
        steps=tuple(materialize_step(step) for step in proposal.steps),
    )
    return None, plan


def admit_action_plan_bindings(
    actions,
    *,
    working_plan: ConversationWorkingPlan | None,
) -> DecisionFeedback | None:
    if working_plan is None:
        return next(
            (
                DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="working_plan_missing",
                    message="An action cannot bind to a plan step when no working plan exists.",
                    repairable_fields=("plan_step_id",),
                    immutable_fields=("action_id",),
                    required_repair="Clear plan_step_id or create a working plan first.",
                )
                for action in actions
                if action.plan_step_id is not None
            ),
            None,
        )
    pending_ids = {
        step.step_id for step in working_plan.steps if step.status == "pending"
    }
    for action in actions:
        if action.plan_step_id is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="plan_step_binding_required",
                message="Every action must bind to one pending step while a working plan exists.",
                repairable_fields=("plan_step_id",),
                immutable_fields=("action_id",),
                required_repair="Set plan_step_id to one current pending step.",
            )
        if action.plan_step_id not in pending_ids:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="plan_step_not_pending",
                message=f"Plan step {action.plan_step_id!r} is not pending.",
                repairable_fields=("plan_step_id",),
                immutable_fields=("action_id",),
                required_repair="Bind the action to one current pending step.",
            )
    return None


def incomplete_working_plan_feedback(
    working_plan: ConversationWorkingPlan,
) -> DecisionFeedback | None:
    """Keep FinalMessage from silently erasing unresolved result obligations."""
    pending = tuple(
        step.step_id for step in working_plan.steps if step.status == "pending"
    )
    if not pending:
        return None
    return DecisionFeedback(
        action_id="working_plan",
        reason_code="working_plan_incomplete",
        message="The current working plan still has unresolved result obligations.",
        repairable_fields=("working_plan", "actions", "resolved_plan_step_ids"),
        immutable_fields=("messages", "inputs"),
        required_repair=(
            "Complete, revise, or truthfully defer the pending steps before returning "
            "an answer. If the answer itself delivers them, list exactly these IDs in "
            "resolved_plan_step_ids: " + ", ".join(pending) + "."
        ),
    )


def admit_final_plan_resolution(
    resolved_step_ids: tuple[str, ...],
    *,
    working_plan: ConversationWorkingPlan,
    inputs: tuple,
) -> tuple[DecisionFeedback | None, ConversationWorkingPlan | None]:
    """Apply only result steps delivered by the answer itself.

    FinalMessage is the semantic assessment. The runtime only binds successful
    observations as execution evidence, avoiding a second semantic write through a
    preceding WorkingPlanProposal.
    """
    pending_ids = tuple(
        step.step_id for step in working_plan.steps if step.status == "pending"
    )
    if not pending_ids:
        return None, working_plan
    if len(resolved_step_ids) != len(set(resolved_step_ids)) or set(
        resolved_step_ids
    ) != set(pending_ids):
        return incomplete_working_plan_feedback(working_plan), None
    successful_action_ids_by_step = {
        step_id: tuple(
            item.action_id
            for item in inputs
            if isinstance(item, ActionObservation)
            and item.status == "succeeded"
            and item.plan_step_id == step_id
        )
        for step_id in pending_ids
    }
    resolved = set(resolved_step_ids)
    return None, working_plan.model_copy(update={
        "revision": working_plan.revision + 1,
        "steps": tuple(
            step.model_copy(update={
                "status": "completed",
                "completion_action_ids": successful_action_ids_by_step[step.step_id],
            })
            if step.step_id in resolved
            else step
            for step in working_plan.steps
        ),
    })
__all__ = [
    "admit_action_plan_bindings",
    "admit_final_plan_resolution",
    "admit_new_plan_interaction_mode",
    "admit_plan_wait_boundary",
    "admit_working_plan",
    "incomplete_working_plan_feedback",
    "required_plan_review_feedback",
]

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


_TERMINAL_STEP_STATUSES = frozenset({"completed", "superseded"})


def is_terminal_working_plan(plan: ConversationWorkingPlan | None) -> bool:
    """Return whether every admitted step has a terminal execution fact."""
    return bool(plan is not None and all(
        step.status in _TERMINAL_STEP_STATUSES for step in plan.steps
    ))


def supersede_pending_working_plan(
    working_plan: ConversationWorkingPlan,
) -> ConversationWorkingPlan:
    """End provisional obligations without fabricating execution evidence."""
    if not any(
        step.status in {"pending", "in_progress"}
        for step in working_plan.steps
    ):
        return working_plan
    return working_plan.model_copy(update={
        "revision": working_plan.revision + 1,
        "steps": tuple(
            step.model_copy(update={"status": "superseded"})
            if step.status in {"pending", "in_progress"} else step
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
    wait_for_user: bool = False,
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
    active_count = sum(step.status == "in_progress" for step in proposal.steps)
    nonterminal = any(
        step.status in {"pending", "in_progress"} for step in proposal.steps
    )
    if wait_for_user and active_count:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="waiting_plan_has_active_step",
            message="A working plan awaiting user review cannot have an active step.",
            repairable_fields=("steps",),
            immutable_fields=("wait_for_user",),
            required_repair=(
                "Keep every unfinished step pending until the user authorizes execution."
            ),
        ), None
    if not wait_for_user and nonterminal and active_count != 1:
        return DecisionFeedback(
            action_id="working_plan",
            reason_code="working_plan_active_step_required",
            message="An executable working plan requires exactly one in_progress step.",
            repairable_fields=("steps",),
            immutable_fields=("goal", "grounding"),
            required_repair=(
                "Mark exactly one unfinished step in_progress and keep every other "
                "unfinished step pending."
            ),
        ), None
    starts_new_plan = _starts_new_plan(proposal, current)
    if current is not None and not starts_new_plan and _same_plan_content(
        proposal,
        current,
    ):
        return None, current
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
    if decision.actions or decision.wait_for_user or decision.finalization_requested:
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
            "finalization_requested",
        ),
        immutable_fields=("messages", "inputs"),
        required_repair=(
            "Keep an unchanged plan unchanged and submit the next necessary concrete "
            "action, a genuinely revised plan, wait for the user, or return FinalMessage."
        ),
    )


def admit_action_plan_state(
    actions,
    *,
    working_plan: ConversationWorkingPlan | None,
) -> DecisionFeedback | None:
    if not actions or working_plan is None:
        return None
    if is_terminal_working_plan(working_plan):
        return DecisionFeedback(
            action_id=actions[0].action_id,
            reason_code="working_plan_terminal",
            message="A terminal working plan has no executable work item.",
            repairable_fields=("actions",),
            immutable_fields=("working_plan",),
            required_repair="Return the final result or create a genuinely new plan.",
        )
    if active_working_plan_step_id(working_plan) is None:
        return DecisionFeedback(
            action_id=actions[0].action_id,
            reason_code="working_plan_active_step_required",
            message="The current working plan has no unique in_progress step.",
            repairable_fields=("working_plan",),
            immutable_fields=("actions",),
            required_repair=(
                "Use the working-plan control action to mark exactly one unfinished "
                "step in_progress; do not add a step ID to the concrete action."
            ),
        )
    return None


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
    "admit_action_plan_state",
    "admit_continue_turn_progress",
    "admit_new_plan_interaction_mode",
    "admit_plan_wait_boundary",
    "admit_working_plan",
    "complete_working_plan",
    "is_terminal_working_plan",
    "required_plan_review_feedback",
    "supersede_pending_working_plan",
]

"""Validate and apply a model-proposed goal patch without mutating its base."""
from collections.abc import Sequence
from dataclasses import dataclass

from personal_agent.capabilities.contracts.verification import GoalClarificationReview

from .goal_models import (
    AddGoalItem, AnalysisGoal, CurrentAnalysisGoal, GoalExecutionControl, GoalItem, GoalPatch, RevokeGoalItem,
)
from .models import InteractionTrace


@dataclass(frozen=True)
class GoalPatchRejected(ValueError):
    reason: str
    item_id: str | None = None
    clarification_id: str | None = None


@dataclass(frozen=True)
class GoalPatchCandidate:
    goal: AnalysisGoal
    execution_control: GoalExecutionControl | None
    clarification_resolution: GoalClarificationReview | None = None


@dataclass(frozen=True)
class PendingGoalClarification:
    clarification_id: str
    question: str


def pending_goal_clarifications(sources: Sequence[InteractionTrace]) -> tuple[PendingGoalClarification, ...]:
    """Project delivered questions and accepted resolutions on the selected branch."""
    pending: dict[str, PendingGoalClarification] = {}
    for source in sources:
        for operation in source.goal_operations:
            if operation.patch is not None and (resolution := operation.patch.resolve_clarification):
                pending.pop(resolution.clarification_id, None)
        final = source.final_message
        if final is not None and final.disposition == "clarification_required":
            identifier = source.interaction_run_ref
            pending[identifier] = PendingGoalClarification(identifier, final.message)
    return tuple(pending.values())


def _clarification_review(
    patch: GoalPatch, user_message: str, sources: Sequence[InteractionTrace],
) -> GoalClarificationReview | None:
    resolution = patch.resolve_clarification
    if resolution is None:
        return None
    pending = next((item for item in pending_goal_clarifications(sources)
                    if item.clarification_id == resolution.clarification_id), None)
    if pending is None:
        raise GoalPatchRejected("clarification_not_pending", clarification_id=resolution.clarification_id)
    if not resolution.evidence.strip() or resolution.evidence not in user_message:
        raise GoalPatchRejected("clarification_evidence_not_in_current_user_message",
                                clarification_id=pending.clarification_id)
    return GoalClarificationReview(clarification_id=pending.clarification_id,
                                   question=pending.question, evidence=resolution.evidence)


def _item_key(item: GoalItem) -> tuple[str, str, str]:
    return item.kind, item.scope, " ".join(item.text.split()).casefold()


def apply_goal_patch(
    patch: GoalPatch, trace: InteractionTrace, current: CurrentAnalysisGoal | None,
    *, previous: Sequence[InteractionTrace] = (),
) -> GoalPatchCandidate:
    version = current.reference.revision if current else 0
    if patch.base_version != version:
        raise GoalPatchRejected("stale_version")
    if patch.clarifications:
        raise GoalPatchRejected("clarification_required")
    if current is not None and current.goal.goal_id is None:
        raise GoalPatchRejected("legacy_goal_requires_new_conversation")
    index, user_message = next(
        (index, trace.messages[index - 1].content)
        for index in range(len(trace.messages), 0, -1) if trace.messages[index - 1].role == "user"
    )
    source_id = f"{trace.interaction_run_ref}:user:{index}"
    if patch.delivery is not None:
        if trace.first_goal_operation is not None:
            raise GoalPatchRejected("delivery_already_bound")
        if not patch.delivery.evidence.strip() or patch.delivery.evidence not in user_message:
            raise GoalPatchRejected("evidence_not_in_current_user_message")
    clarification = _clarification_review(patch, user_message, (*previous, trace))
    goal = current.goal if current else None
    control = current.execution_control if current else None
    if change := patch.execution_control:
        if not change.evidence.strip() or change.evidence not in user_message:
            raise GoalPatchRejected("evidence_not_in_current_user_message")
        restriction = {"running": 0, "read_only": 1, "paused": 2}
        previous_mode = control.mode if control else "running"
        if (restriction[change.mode] < restriction[previous_mode]
                and not trace.feature_flags_binding.goal_verification):
            raise GoalPatchRejected("execution_resume_requires_verification")
        if change.mode != previous_mode:
            control = GoalExecutionControl(mode=change.mode, source_message_id=source_id)
    if not patch.changes:
        if goal is None and control is None and clarification is None:
            raise GoalPatchRejected("no_active_goal")
        return GoalPatchCandidate(goal or AnalysisGoal(goal_id=trace.interaction_run_ref, objective=""),
                                  control, clarification)

    items = {item.item_id: item for item in goal.items} if goal else {}
    applicable = {item.item_id for item in goal.active_items(trace.interaction_run_ref)} if goal else set()
    touched = set()
    for change in patch.changes:
        if not change.evidence.strip() or change.evidence not in user_message:
            raise GoalPatchRejected("evidence_not_in_current_user_message")
        if isinstance(change, AddGoalItem):
            item_id = f"i{len(items) + 1}"
            item = GoalItem(item_id=item_id, kind=change.kind, scope=change.scope, text=change.text,
                source_message_ids=(source_id,), acceptance_criteria=change.acceptance_criteria)
        else:
            item_id = change.item_id
            if item_id not in applicable or item_id in touched:
                raise GoalPatchRejected("item_unavailable_or_already_changed", item_id)
            touched.add(item_id)
            previous = items[item_id]
            if previous.kind == "constraint" and not trace.feature_flags_binding.goal_verification:
                raise GoalPatchRejected("constraint_change_requires_verification", item_id)
            sources = tuple(dict.fromkeys((*previous.source_message_ids, source_id)))
            if isinstance(change, RevokeGoalItem):
                items[item_id] = previous.model_copy(update={"status": "revoked", "source_message_ids": sources})
                continue
            item = previous.model_copy(update={
                "text": change.text,
                "acceptance_criteria": (previous.acceptance_criteria if change.acceptance_criteria is None
                                        else change.acceptance_criteria),
                "source_message_ids": sources,
            })
            if item.text == previous.text and item.acceptance_criteria == previous.acceptance_criteria:
                raise GoalPatchRejected("unchanged_item", item_id)
        items[item_id] = item

    keys = set()
    for item in items.values():
        if item.status != "active" or (item.scope == "turn" and item.source_message_ids[-1] != source_id):
            continue
        key = _item_key(item)
        if key in keys:
            raise GoalPatchRejected("duplicate_item", item.item_id)
        keys.add(key)
    objective = next((item.text for item in items.values()
                      if item.scope == "task" and item.kind == "requirement" and item.status == "active"),
                     "")
    return GoalPatchCandidate(
        AnalysisGoal(goal_id=goal.goal_id if goal else trace.interaction_run_ref,
                     objective=objective, items=tuple(items.values())),
        control, clarification,
    )

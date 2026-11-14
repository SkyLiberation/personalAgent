"""Resolve task ownership from accepted Goal operations on an exact branch."""

from collections.abc import Sequence
from dataclasses import dataclass

from personal_agent.kernel.prompt_registry import PromptCatalog

from .goal_changes import GoalPatchRejected, pending_goal_clarifications
from .goal_maintenance import current_analysis_goal
from .goal_models import CurrentAnalysisGoal, GoalOperationRecord, GoalPatch, GoalTaskAction, GoalTaskId
from .models import InteractionTrace


def _operation_task(operation: GoalOperationRecord | None) -> tuple[GoalTaskAction | None, GoalTaskId | None]:
    if operation is None:
        return None, None
    selection = operation.patch.task if operation.patch is not None else None
    return selection.action if selection is not None else None, operation.goal.goal_id


def task_switch_turn(trace: InteractionTrace) -> int:
    """The routing exchange can contain rejected or superseded task context."""
    operation = trace.first_goal_operation
    if operation is not None and _operation_task(operation)[0] in ("start", "side_question", "resume"):
        return operation.decision_turn
    return 0


def _routing_clarification(trace: InteractionTrace) -> bool:
    return (trace.final_message is not None and trace.final_message.disposition == "clarification_required"
            and trace.first_goal_operation is None)


@dataclass(frozen=True)
class AnalysisTaskHistory:
    """A derived index of visible turns. The Journal owns their only task binding."""

    current_id: GoalTaskId | None
    by_task: dict[GoalTaskId | None, tuple[InteractionTrace, ...]]

    @classmethod
    def from_turns(cls, turns: Sequence[InteractionTrace]) -> "AnalysisTaskHistory":
        current_id = None
        tasks: dict[GoalTaskId | None, list[InteractionTrace]] = {}
        for turn in turns:
            operation = turn.first_goal_operation
            action, task_id = _operation_task(operation)
            if action in ("start", "side_question", "resume"):
                previous = tasks.get(current_id, [])
                moved = _selected_routing_clarification(operation.patch if operation else None, previous)
                if moved is not None:
                    previous.remove(moved)
                    if action != "side_question":
                        tasks.setdefault(task_id, []).append(_clarification_context(moved))
                        tasks[task_id].sort(key=lambda item: len(item.messages))
            if action == "side_question":
                continue
            if task_id is not None:
                if current_id is None and action is None and task_id not in tasks:
                    tasks[task_id] = tasks.pop(None, [])
                current_id = task_id
            tasks.setdefault(current_id, []).append(turn)
        return cls(current_id, {key: tuple(sources) for key, sources in tasks.items()})

    def selected_turns(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        first = trace.first_goal_operation
        action, task_id = _operation_task(first)
        if first is not None and first.patch is not None and action in ("start", "side_question", "resume"):
            return self.for_selection(first.patch)
        return self.by_task.get(task_id if task_id is not None else self.current_id, ())

    def for_selection(self, patch: GoalPatch) -> tuple[InteractionTrace, ...]:
        selection = patch.task
        target = (self.by_task.get(selection.task_id, ())
                  if selection is not None and selection.action == "resume" else ())
        moved = _selected_routing_clarification(patch, self.by_task.get(self.current_id, ()))
        if moved is None:
            return target
        return tuple(sorted((*target, _clarification_context(moved)), key=lambda item: len(item.messages)))

    def describe(self, trace: InteractionTrace, *, prompts: PromptCatalog) -> str:
        entries = []
        for task_id, turns in reversed(tuple(self.by_task.items())):
            if task_id is None:
                continue
            goal = current_analysis_goal(turns[-1], turns[:-1])
            if goal is None:
                continue
            is_current = task_id == self.current_id
            questions = "" if is_current else "\n\n".join(prompts.render("conversation.goal.clarification_item",
                clarification_id=item.clarification_id, question=item.question) for item in pending_goal_clarifications(turns))
            origin = next((turn for turn in turns if turn.interaction_run_ref == task_id), turns[0])
            entries.append(prompts.render("conversation.goal.task_entry", task_id=task_id,
                state=prompts.get("conversation.goal.task_active" if is_current
                                  else "conversation.goal.task_inactive").template,
                version=goal.reference.revision, request=origin.messages[-1].content,
                snapshot="" if is_current else goal.verification_text(trace.interaction_run_ref),
                questions=questions))
        return "\n\n".join(entries)


def _selected_routing_clarification(
    patch: GoalPatch | None, previous: Sequence[InteractionTrace],
) -> InteractionTrace | None:
    resolution = patch.resolve_clarification if patch is not None else None
    if resolution is None or not any(item.clarification_id == resolution.clarification_id
                                     for item in pending_goal_clarifications(previous)):
        return None
    return next((source for source in previous if source.interaction_run_ref == resolution.clarification_id
                 and _routing_clarification(source)), None)


def _clarification_context(source: InteractionTrace) -> InteractionTrace:
    """Keep the original question and delivered clarification across the task boundary."""
    return source.model_copy(update={
        "goal_operations": (), "model_decisions": (), "inputs": (), "history_compaction": None,
        "verification_history_compactions": (), "working_plan": None,
    })


@dataclass(frozen=True)
class GoalTaskCandidate:
    action: GoalTaskAction
    previous: tuple[InteractionTrace, ...]
    current: CurrentAnalysisGoal | None
    history: AnalysisTaskHistory


def select_goal_task(
    patch: GoalPatch, trace: InteractionTrace, branch: Sequence[InteractionTrace],
) -> GoalTaskCandidate:
    history = AnalysisTaskHistory.from_turns(branch)
    selection = patch.task
    if patch.clarifications:
        raise GoalPatchRejected("clarification_required")
    if selection is None:
        previous = history.selected_turns(trace)
        current = current_analysis_goal(trace, previous)
        return GoalTaskCandidate("continue" if current is not None else "start", previous, current, history)
    if trace.first_goal_operation is not None:
        raise GoalPatchRejected("task_already_bound")
    user_message = next(message.content for message in reversed(trace.messages) if message.role == "user")
    if not selection.evidence.strip() or selection.evidence not in user_message:
        raise GoalPatchRejected("task_evidence_not_in_current_user_message")
    action = selection.action
    if (action == "resume") != (selection.task_id is not None):
        raise GoalPatchRejected("task_id_only_for_resume")
    if action == "resume":
        task_id = selection.task_id
        if task_id == history.current_id or task_id not in history.by_task:
            raise GoalPatchRejected("task_unavailable")
        previous = history.for_selection(patch)
    elif action == "continue":
        if history.current_id is None:
            raise GoalPatchRejected("no_current_task")
        previous = history.selected_turns(trace)
    else:
        previous = history.for_selection(patch)
    return GoalTaskCandidate(action, previous, current_analysis_goal(trace, previous), history)


def task_message_indices(trace: InteractionTrace, previous: Sequence[InteractionTrace]) -> tuple[int, ...]:
    return tuple(index for turn in previous for index in (len(turn.messages) - 1, len(turn.messages))) + (
        len(trace.messages) - 1,
    )

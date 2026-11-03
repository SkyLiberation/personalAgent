"""Execution-goal admission and read-only projections for one analysis branch."""
from collections.abc import Sequence
from hashlib import sha256
import json

from personal_agent.kernel.prompt_registry import PromptCatalog

from .errors import ConversationOperationConflict
from .goal_models import (
    AnalysisGoal, AnalysisGoalRef, CurrentAnalysisGoal, GoalMaintenanceInvocation,
    GoalOperationRecord,
    GoalModelView, GoalOperationReceipt,
)
from .models import ContinueTurnProposal, DecisionFeedback, FinalMessage, InteractionTrace
from .history_models import HistoryItemKey


def _digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def goal_input_digest(trace: InteractionTrace) -> str:
    return _digest([message.model_dump(mode="json") for message in trace.messages])


def _goal_digest(goal: AnalysisGoal) -> str:
    return _digest(goal.model_dump(mode="json"))


def current_analysis_goal(
    trace: InteractionTrace, previous: Sequence[InteractionTrace],
) -> CurrentAnalysisGoal | None:
    current = None
    for source in (*previous, trace):
        for record in source.goal_operations:
            base = current.reference if current is not None else None
            if record.run_ref != source.interaction_run_ref or record.input_digest != goal_input_digest(source):
                raise ConversationOperationConflict("goal operation input binding changed")
            if record.base_goal_ref != base:
                raise ConversationOperationConflict("goal operation is not on the selected branch")
            if record.operation in ("retain", "read"):
                if current is None or record.goal_ref != base or record.goal != current.goal:
                    raise ConversationOperationConflict("read or retained goal differs from its source")
            else:
                revision = 1 if current is None else current.reference.revision + 1
                expected = AnalysisGoalRef(run_ref=record.run_ref, call_id=record.call_id,
                    revision=revision, content_digest=_goal_digest(record.goal))
                if record.goal_ref != expected or (record.operation == "create") != (current is None):
                    raise ConversationOperationConflict("goal snapshot version or digest changed")
            current = CurrentAnalysisGoal(reference=record.goal_ref, goal=record.goal)
    return current


def goal_prepared(trace: InteractionTrace, current: CurrentAnalysisGoal | None) -> bool:
    return current is not None and any(
        record.operation != "read" and record.input_digest == goal_input_digest(trace) and record.goal_ref == current.reference
        for record in trace.goal_operations)


def goal_model_view(current: CurrentAnalysisGoal) -> GoalModelView:
    return GoalModelView(revision=current.reference.revision, goal=current.goal)


def goal_feedback(call_id: str, code: str, details: object, *, prompts: PromptCatalog) -> DecisionFeedback:
    return DecisionFeedback(action_id=call_id, action_name="maintain_goal", reason_code=code,
        message=prompts.render("conversation.goal.rejected", reason_code=code,
                               details_json=json.dumps(details, ensure_ascii=False)),
        required_repair=prompts.get("conversation.goal.repair").template)


def admit_goal_maintenance(
    invocation: GoalMaintenanceInvocation, *, trace: InteractionTrace,
    current: CurrentAnalysisGoal | None, prompts: PromptCatalog,
    verification_ref: HistoryItemKey,
) -> GoalOperationRecord | DecisionFeedback:
    args = invocation.arguments
    base = current.reference if current is not None else None
    if args is None:
        if current is None:
            return goal_feedback(invocation.call_id, "goal_required", {"current_goal": None}, prompts=prompts)
        operation = "retain"
        goal, reference = current.goal, current.reference
    else:
        operation = "create" if current is None else "revise"
        goal = args
        reference = AnalysisGoalRef(run_ref=trace.interaction_run_ref, call_id=invocation.call_id,
            revision=1 if base is None else base.revision + 1, content_digest=_goal_digest(goal))
    return GoalOperationRecord(run_ref=trace.interaction_run_ref, call_id=invocation.call_id,
        decision_turn=trace.usage.model_turns, input_digest=goal_input_digest(trace),
        operation=operation, base_goal_ref=base, goal_ref=reference, goal=goal,
        verification_ref=verification_ref)


def goal_tool_result(record: GoalOperationRecord, *, prompts: PromptCatalog) -> str:
    current = CurrentAnalysisGoal(reference=record.goal_ref, goal=record.goal)
    receipt = GoalOperationReceipt(operation=record.operation, current_goal=goal_model_view(current))
    return prompts.render("conversation.goal.read_result" if record.operation == "read" else "conversation.goal.accepted",
                          result_json=receipt.model_dump_json())


def goal_decision_outcome(decision, *, trace: InteractionTrace, previous: Sequence[InteractionTrace],
                          prompts: PromptCatalog):
    current = current_analysis_goal(trace, previous)
    invocation = decision.goal_maintenance if isinstance(decision, ContinueTurnProposal) else None
    if invocation is not None:
        if invocation.arguments is None and current is None:
            return goal_feedback(invocation.call_id, "goal_required", {"current_goal": None}, prompts=prompts)
        return invocation
    if isinstance(decision, FinalMessage) and decision.disposition != "answer":
        return None
    if not goal_prepared(trace, current):
        return goal_feedback("goal_precondition", "goal_required", {
            "current_goal": goal_model_view(current).model_dump(mode="json") if current is not None else None}, prompts=prompts)
    read = decision.goal_read if isinstance(decision, ContinueTurnProposal) else None
    if read is not None:
        return GoalOperationRecord(run_ref=trace.interaction_run_ref, call_id=read.call_id,
            decision_turn=trace.usage.model_turns, input_digest=goal_input_digest(trace),
            operation="read", base_goal_ref=current.reference, goal_ref=current.reference,
            goal=current.goal)
    return None


def goal_context(trace: InteractionTrace, previous: Sequence[InteractionTrace], *, prompts: PromptCatalog) -> str:
    current = current_analysis_goal(trace, previous)
    return prompts.render("conversation.goal.context",
        prepared_json=json.dumps(goal_prepared(trace, current)),
        goal_json=goal_model_view(current).model_dump_json() if current is not None else "null")

"""Execution-goal admission and read-only projections for one analysis branch."""
from collections.abc import Sequence
from hashlib import sha256
import json

from personal_agent.kernel.prompt_registry import PromptCatalog
from .errors import ConversationOperationConflict
from .goal_changes import GoalPatchCandidate, pending_goal_clarifications
from .goal_models import (
    AnalysisGoal, AnalysisGoalRef, CurrentAnalysisGoal, GoalMaintenanceInvocation,
    GoalOperationRecord,
)
from .models import ContinueTurnProposal, DecisionFeedback, FinalMessage, InteractionTrace, ToolCallProposal
from .history_models import HistoryItemKey


def _digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def goal_input_digest(trace: InteractionTrace) -> str:
    return _digest([message.model_dump(mode="json") for message in trace.messages])


def _goal_digest(goal: AnalysisGoal) -> str:
    if goal.goal_id is None:
        return _digest({"objective": goal.objective})
    return _digest(goal.model_dump(mode="json"))


def current_analysis_goal(
    trace: InteractionTrace, previous: Sequence[InteractionTrace],
) -> CurrentAnalysisGoal | None:
    current = None
    for source in (*previous, trace):
        switch = source.first_goal_operation
        switched = (switch is not None and switch.patch is not None and switch.patch.task is not None
                    and switch.patch.task.action != "continue")
        for record in source.goal_operations:
            if switched and record.decision_turn < switch.decision_turn:
                continue
            base = current.reference if current is not None else None
            if record.run_ref != source.interaction_run_ref or record.input_digest != goal_input_digest(source):
                raise ConversationOperationConflict("goal operation input binding changed")
            if record.base_goal_ref != base:
                raise ConversationOperationConflict("goal operation is not on the selected branch")
            if record.operation in ("retain", "read"):
                if current is None or record.goal_ref != base or record.goal != current.goal:
                    raise ConversationOperationConflict("read or retained goal differs from its source")
            else:
                revision = 0 if record.operation in ("control", "resolve") else (base.revision if base else 0) + 1
                expected = AnalysisGoalRef(run_ref=record.run_ref, call_id=record.call_id,
                    revision=revision, content_digest=_goal_digest(record.goal))
                expected_operation = ("control" if base is None and not record.goal.items
                                      and record.execution_control is not None else
                                      "resolve" if base is None and not record.goal.items
                                      and record.patch is not None and record.patch.resolve_clarification is not None else
                                      "create" if base is None or base.revision == 0 else "revise")
                if record.goal_ref != expected or record.operation != expected_operation:
                    raise ConversationOperationConflict("goal snapshot version or digest changed")
            current = CurrentAnalysisGoal(reference=record.goal_ref, goal=record.goal,
                                          execution_control=record.execution_control)
    return current


def goal_prepared(trace: InteractionTrace, current: CurrentAnalysisGoal | None) -> bool:
    return current is not None and any(
        record.operation != "read" and record.input_digest == goal_input_digest(trace) and record.goal_ref == current.reference
        for record in trace.goal_operations)


def goal_feedback(call_id: str, code: str, details: object, *, prompts: PromptCatalog,
                  action_name: str = "") -> DecisionFeedback:
    return DecisionFeedback(action_id=call_id, action_name=action_name, reason_code=code,
        message=prompts.render("conversation.goal.rejected", reason_code=code,
                               details_json=json.dumps(details, ensure_ascii=False)),
        required_repair=prompts.get("conversation.goal.repair").template)


def admit_goal_maintenance(
    invocation: GoalMaintenanceInvocation, *, trace: InteractionTrace,
    current: CurrentAnalysisGoal | None,
    verification_ref: HistoryItemKey | None,
    candidate: GoalPatchCandidate,
) -> GoalOperationRecord:
    base = current.reference if current is not None else None
    if not invocation.arguments.changes and current is not None:
        operation = "retain"
        goal, reference = current.goal, current.reference
    else:
        previous_version = base.revision if base else 0
        if invocation.arguments.changes:
            operation = "create" if previous_version == 0 else "revise"
        else:
            operation = "control" if candidate.execution_control is not None else "resolve"
        goal = candidate.goal
        reference = AnalysisGoalRef(run_ref=trace.interaction_run_ref, call_id=invocation.call_id,
            revision=0 if operation in ("control", "resolve") else previous_version + 1, content_digest=_goal_digest(goal))
    return GoalOperationRecord(run_ref=trace.interaction_run_ref, call_id=invocation.call_id,
        decision_turn=trace.usage.model_turns, input_digest=goal_input_digest(trace),
        operation=operation, base_goal_ref=base, goal_ref=reference, goal=goal,
        verification_ref=verification_ref, patch=invocation.arguments, execution_control=candidate.execution_control)


def goal_tool_result(record: GoalOperationRecord, *, prompts: PromptCatalog) -> str:
    prompt = ("conversation.goal.read_result" if record.operation == "read" else
              "conversation.goal.accepted" if record.verification_ref is not None else
              "conversation.goal.accepted_unverified")
    operation = prompts.get(f"conversation.context.goal.operation.{record.operation}").template
    objective = prompts.render("conversation.context.goal.version",
        revision=record.goal_ref.revision, objective=record.verification_text())
    return prompts.render(prompt, result_text=f"{operation}\n\n{objective}")


def goal_decision_outcome(decision, *, trace: InteractionTrace, previous: Sequence[InteractionTrace],
                          prompts: PromptCatalog, read_only_tools: frozenset[str]):
    current = current_analysis_goal(trace, previous)
    invocation = decision.goal_maintenance if isinstance(decision, ContinueTurnProposal) else None
    if invocation is not None:
        return invocation
    if isinstance(decision, FinalMessage) and decision.disposition != "answer":
        return None
    read = decision.goal_read if isinstance(decision, ContinueTurnProposal) else None
    if read is not None and current is not None:
        return GoalOperationRecord(run_ref=trace.interaction_run_ref, call_id=read.call_id,
            decision_turn=trace.usage.model_turns, input_digest=goal_input_digest(trace),
            operation="read", base_goal_ref=current.reference, goal_ref=current.reference,
            goal=current.goal, execution_control=current.execution_control)
    if goal_prepared(trace, current):
        control = current.execution_control
        if control is not None and control.mode != "running" and isinstance(decision, ContinueTurnProposal):
            for action in decision.actions:
                if (control.mode == "paused" or not isinstance(action, ToolCallProposal)
                        or action.tool_name not in read_only_tools):
                    return goal_feedback(action.action_id, "execution_restricted", {"mode": control.mode},
                                         prompts=prompts)
        return None
    return goal_feedback("goal_precondition", "goal_required", {
        "base_version": current.reference.revision if current else 0}, prompts=prompts)


def goal_context(trace: InteractionTrace, previous: Sequence[InteractionTrace], *, prompts: PromptCatalog) -> str:
    current = current_analysis_goal(trace, previous)
    verified = trace.feature_flags_binding.goal_verification
    state = ("verified" if verified else "unverified") if goal_prepared(trace, current) else "pending"
    objective = (prompts.render("conversation.context.goal.version", revision=current.reference.revision,
                               objective=current.verification_text(trace.interaction_run_ref))
                 if current is not None else prompts.get("conversation.context.goal.none").template)
    context = prompts.render("conversation.goal.context" if verified else "conversation.goal.context_unverified",
        prepared=prompts.get(f"conversation.context.goal.{state}").template, objective=objective)
    pending = pending_goal_clarifications((*previous, trace))
    if not pending:
        return context
    questions = "\n\n".join(prompts.render("conversation.goal.clarification_item",
        clarification_id=item.clarification_id, question=item.question) for item in pending)
    return context + "\n\n" + prompts.render("conversation.goal.pending_clarifications", questions=questions)

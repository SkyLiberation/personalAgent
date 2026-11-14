"""Responsibility-specific ordered projections of canonical verification facts."""
import json
from hashlib import sha256

from pydantic import ValidationError

from personal_agent.capabilities.contracts.verification import (
    GoalClarificationReview, VerificationTurn, VerificationContext, VerificationEvent, VerificationKind,
    SemanticVerificationReceipt, GoalTaskReview,
    UnverifiedGoalSnapshot,
)
from .errors import ConversationOperationConflict
from .analysis_tasks import task_switch_turn
from .goal_models import SUBMIT_GOAL_PATCH, AnalysisGoal, GoalOperationRecord, goal_verification_action_id
from .history_models import VerificationHistoryCheckpoint
from .models import ActionObservation, InteractionInput, InteractionTrace, SubmittedFinal
from .verification_admission import INTERACTION_VERIFICATION_CAPABILITY, observed_receipts


def current_question_inputs(trace: InteractionTrace) -> tuple[InteractionInput, ...]:
    decisions = tuple(record for record in trace.model_decisions if record.turn_index is not None)
    if not decisions:
        raise ConversationOperationConflict("verification requires the current decision")
    return trace.inputs[decisions[0].input_start:]


def goal_submission_id(trace: InteractionTrace, call_id: str, turn: int) -> str:
    return goal_verification_action_id(trace.interaction_run_ref, turn, call_id)


def verification_checkpoint(trace: InteractionTrace, previous: tuple[InteractionTrace, ...],
                            *, kind: VerificationKind, prompt_version: str,
                            task_id: str | None = None,
                            context: VerificationContext | None = None) -> VerificationHistoryCheckpoint | None:
    return next((checkpoint
        for source in reversed((*previous, trace))
        for checkpoint in source.verification_history_compactions
        if checkpoint.task_id == task_id and checkpoint.kind == kind
        and (kind == "goal" or checkpoint.prompt_version == prompt_version)
        and (context is None or all(
            item.user_turn <= len(context.turns)
            and item.covered_events <= len(context.turns[item.user_turn - 1].events)
            and sha256(verification_prefix(context.turns[item.user_turn - 1], item.covered_events, kind=kind).encode()
                       ).hexdigest() == item.source_digest for item in checkpoint.turns))), None)


def verification_prefix(turn: VerificationTurn, end: int, *, kind: VerificationKind) -> str:
    prefix = {"kind": kind, "events": [event.model_dump(mode="json") for event in turn.events[:end]]}
    if turn.question is not None:
        prefix["question"] = turn.question
    return json.dumps(prefix, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verification_events(trace: InteractionTrace) -> tuple[VerificationEvent, ...]:
    events: list[VerificationEvent] = []
    decisions = tuple(item for item in trace.model_decisions if item.turn_index is not None)
    active = None
    verified_goal = None
    unverified_goal = None
    switch_turn = task_switch_turn(trace)
    for index, record in enumerate(decisions):
        if record.turn_index < switch_turn:
            continue
        end = decisions[index + 1].input_start if index + 1 < len(decisions) else len(trace.inputs)
        items = trace.inputs[record.input_start:end]
        receipts = observed_receipts(items, capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
        if record.assistant is not None:
            for call in record.assistant.payload.get("tool_calls", ()) or ():
                function = call.get("function", {})
                name = function.get("name")
                if name not in (SUBMIT_GOAL_PATCH, "maintain_goal", "retain_goal"):
                    continue
                submission_id = goal_submission_id(trace, call["id"], record.turn_index)
                verdict = next((receipt for receipt in receipts if receipt.checked_kind == "goal"), None)
                accepted = next((op for op in trace.goal_operations
                    if op.call_id == call["id"] and op.decision_turn == record.turn_index), None)
                content = verdict.verified_draft if verdict else (
                    accepted.verification_text() if accepted else None)
                if content is None and name != SUBMIT_GOAL_PATCH:
                    try:
                        args = json.loads(function.get("arguments", "{}"))
                        content = AnalysisGoal.model_validate(args).objective if name == "maintain_goal" else active
                    except (ValidationError, ValueError, TypeError):
                        continue
                if content is not None:
                    events.append(VerificationEvent(kind="goal", submission_id=submission_id,
                        content=content, verdict=verdict))
                if accepted is not None:
                    active = accepted.verification_text()
                    if trace.feature_flags_binding.goal_verification:
                        verified_goal = _accepted_goal_receipt(accepted, items)
                    else:
                        unverified_goal = UnverifiedGoalSnapshot(
                            submission_id=submission_id, content=active)
        for item in items:
            if isinstance(item, SubmittedFinal):
                events.append(VerificationEvent(kind="answer", submission_id=f"{trace.interaction_run_ref}:{item.action_id}",
                    content=item.final.message, disposition=item.final.disposition,
                    verified_goal=verified_goal, unverified_goal=unverified_goal))
            elif isinstance(item, ActionObservation):
                for receipt in observed_receipts((item,), capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY})):
                    if receipt.checked_kind == "goal":
                        continue
                    if not events or events[-1].kind != "answer" or events[-1].content != receipt.verified_draft:
                        raise ConversationOperationConflict("answer verdict is not paired with its actual submission")
                    events[-1] = events[-1].model_copy(update={"verdict": receipt})
    if trace.final_message is not None and (not events or events[-1].content != trace.final_message.message):
        events.append(VerificationEvent(kind="answer", submission_id=f"{trace.interaction_run_ref}:delivered",
            content=trace.final_message.message, disposition=trace.final_message.disposition,
            verified_goal=verified_goal, unverified_goal=unverified_goal))
    return tuple(events)


def _accepted_goal_receipt(operation: GoalOperationRecord, inputs: tuple[InteractionInput, ...]) -> SemanticVerificationReceipt:
    """Resolve the exact accepted operation, never a later goal or an unaccepted proposal."""
    if operation.verification_ref is None:
        raise ConversationOperationConflict("accepted goal has no verification reference")
    observations = tuple(item for item in inputs if isinstance(item, ActionObservation)
                         and item.action_id == operation.verification_ref.action_id)
    receipts = observed_receipts(observations, capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
    if (len(receipts) != 1 or receipts[0].checked_kind != "goal" or receipts[0].verdict != "passed"
            or receipts[0].verified_draft != operation.verification_text()):
        raise ConversationOperationConflict("accepted goal differs from its verified snapshot")
    return receipts[0]


def build_verification_context(*, trace: InteractionTrace, history: tuple[InteractionTrace, ...],
                               draft: str, kind: VerificationKind,
                               goal_call_id: str | None = None,
                               clarification_resolution: GoalClarificationReview | None = None,
                               task_review: GoalTaskReview | None = None) -> VerificationContext:
    if (kind == "goal") != (goal_call_id is not None):
        raise ConversationOperationConflict("verification responsibility differs from the current submission")
    sources = (*history, trace)
    turns = []
    active_goal = None
    for source in sources:
        question = None
        if kind == "goal":
            question = next((message.content for message in reversed(source.messages) if message.role == "user"), None)
            if question is None:
                raise ConversationOperationConflict("goal verification requires the original user input")
        events = verification_events(source)
        if source is trace:
            if goal_call_id is not None:
                pending = VerificationEvent(kind="goal", submission_id=goal_submission_id(trace, goal_call_id,
                    trace.usage.model_turns), content=draft)
                events = tuple(item for item in events if item.submission_id != pending.submission_id) + (pending,)
                if task_review is not None and task_review.action != "continue":
                    events = (pending,)
            else:
                if not events or events[-1].kind != "answer" or events[-1].content != draft:
                    raise ConversationOperationConflict("verification requires the actual current answer")
                events = (*events[:-1], events[-1].model_copy(update={"verdict": None}))
        turns.append(VerificationTurn(user_turn=len(turns) + 1, question=question,
            events=tuple(event for event in events if event.kind == kind)))
        for operation in source.goal_operations:
            if operation.operation != "read":
                active_goal = operation.goal.verification_text(trace.interaction_run_ref, operation.execution_control)
    binding = sha256(json.dumps({"run": trace.interaction_run_ref, "kind": kind,
        "principal": trace.principal.model_dump(mode="json"),
        "messages": [message.model_dump(mode="json") for message in trace.messages],
        "task_review": task_review.model_dump(mode="json") if task_review else None,
        "goal_refs": [operation.goal_ref.model_dump(mode="json") for source in sources
                      for operation in source.goal_operations if operation.operation != "read"]},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return VerificationContext(kind=kind, turns=tuple(turns),
        active_goal=active_goal if kind == "goal" else None, binding=binding,
        goal_verification_enabled=trace.feature_flags_binding.goal_verification,
        clarification_resolution=clarification_resolution, task_review=task_review)

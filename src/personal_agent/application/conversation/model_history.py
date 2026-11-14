"""Native model exchanges projected from the run's canonical decision facts."""
from collections.abc import Sequence
import json

from personal_agent.capabilities.contracts.model import (
    ModelAssistantMessage, ModelHistoryEntry, ModelRuntimeFeedback, ModelToolExchange, ModelToolResult, StructuredModelResponse,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS, create_prompt_catalog

from .citations import CitableInput, render_citable_input, render_decision_feedback
from .analysis_tasks import AnalysisTaskHistory, task_message_indices, task_switch_turn
from .errors import ConversationOperationConflict
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey
from .goal_maintenance import goal_tool_result
from .goal_models import GOAL_PENDING_ACTION_REJECTED
from .verification_admission import INTERACTION_VERIFICATION_CAPABILITY
from .working_plan import render_working_plan
from .models import (
    ActionObservation, DecisionFeedback, InteractionTrace, ModelCallDisposition, ModelDecisionRecord,
)


def input_identity(item) -> HistoryItemKey | None:
    if isinstance(item, (ActionObservation, DecisionFeedback)):
        return HistoryItemKey(kind=item.kind, action_id=item.action_id,
                              decision_turn=getattr(item, "decision_turn", None))
    return None


def task_switch_input_indices(trace: InteractionTrace) -> frozenset[int]:
    switch_turn = task_switch_turn(trace)
    if not switch_turn:
        return frozenset()
    return frozenset(index for record in trace.model_decisions
        if record.turn_index is not None and record.turn_index <= switch_turn
        for index in decision_input_indices(trace, record))


def goal_pending_rejection(trace: InteractionTrace, record: ModelDecisionRecord) -> DecisionFeedback | None:
    if record.blocked_by is None:
        return None
    return next((item for item in trace.inputs
                 if isinstance(item, DecisionFeedback) and item.reason_code == GOAL_PENDING_ACTION_REJECTED
                 and input_identity(item) == record.blocked_by), None)


def decision_input_indices(trace: InteractionTrace, record: ModelDecisionRecord) -> tuple[int, ...]:
    if record.turn_index is None or record.assistant is None:
        return ()
    ids = set(record.assistant.call_ids)
    end = next((other.input_start for other in trace.model_decisions
                if other.turn_index is not None and other.turn_index > record.turn_index), len(trace.inputs))
    indices = []
    for index, item in enumerate(trace.inputs):
        if record.blocked_by is not None and input_identity(item) == record.blocked_by:
            indices.append(index)
        elif isinstance(item, DecisionFeedback):
            if item.decision_turn == record.turn_index:
                indices.append(index)
        elif (isinstance(item, ActionObservation)
              and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY
              and record.input_start <= index < end):
            # Automatic verification has its own action ID, not a model tool ID.
            indices.append(index)
        elif isinstance(item, ActionObservation) and item.action_id in ids:
            # A rejected ID may be reused in a later corrected proposal. A
            # completed ID may also be proposed again and explicitly rejected.
            # Late recovered execution facts still belong to the latest caller
            # that was not rejected, even if their append follows another turn.
            eligible = []
            for caller in trace.model_decisions:
                if caller.assistant is None or caller.input_start > index or item.action_id not in caller.assistant.call_ids:
                    continue
                rejected = any(isinstance(feedback, DecisionFeedback)
                    and feedback.decision_turn == caller.turn_index
                    and (feedback.action_id == item.action_id
                         or (input_identity(feedback) == caller.blocked_by
                             and feedback.action_id not in caller.assistant.call_ids))
                    for feedback in trace.inputs)
                if not rejected:
                    eligible.append(caller.turn_index)
            if eligible and eligible[-1] == record.turn_index:
                indices.append(index)
    return tuple(indices)


def update_decisions(
    trace: InteractionTrace | None, *, inputs, turn_index: int,
    response: StructuredModelResponse | None = None,
    dispositions: tuple[ModelCallDisposition, ...] = (),
) -> tuple[ModelDecisionRecord, ...]:
    records = list(trace.model_decisions if trace is not None else ())
    index = next((i for i in range(len(records) - 1, -1, -1)
                  if records[i].turn_index == turn_index), None)
    if index is None:
        if dispositions:
            raise ConversationOperationConflict("控制处置缺少同轮原生模型响应")
        return tuple(records)
    record = records[index]
    current = {item.call_id: item for item in record.dispositions}
    for item in dispositions:
        if record.assistant is None or item.call_id not in record.assistant.call_ids:
            raise ConversationOperationConflict("控制处置未绑定原调用")
        if item.call_id in current and current[item.call_id] != item:
            raise ConversationOperationConflict("已提交控制处置不能改写")
        current[item.call_id] = item
    blocked_by = record.blocked_by
    if blocked_by is None:
        feedback = next((item for item in inputs if isinstance(item, DecisionFeedback)
                         and item.decision_turn == turn_index), None)
        blocked_by = input_identity(feedback) if feedback is not None else None
    records[index] = record.model_copy(update={"dispositions": tuple(current.values()), "blocked_by": blocked_by})
    return tuple(records)


def validate_decision_extension(previous: InteractionTrace, current: InteractionTrace) -> None:
    if len(current.model_decisions) < len(previous.model_decisions):
        raise ConversationOperationConflict("原生模型历史不可删除")
    for old, new in zip(previous.model_decisions, current.model_decisions):
        if (old.invocation_id != new.invocation_id or old.operation != new.operation or old.request != new.request
                or (old.turn_index is not None and old.turn_index != new.turn_index) or old.input_start != new.input_start
                or new.response_refs[:len(old.response_refs)] != old.response_refs
                or new.protocol_exchanges[:len(old.protocol_exchanges)] != old.protocol_exchanges
                or new.dispositions[:len(old.dispositions)] != old.dispositions
                or (old.blocked_by is not None and old.blocked_by != new.blocked_by)
                or (old.research_selection is not None and (
                    old.research_selection != new.research_selection
                    or old.research_claim_ref != new.research_claim_ref
                    or old.research_evidence_digest != new.research_evidence_digest
                    or old.research_criteria_digest != new.research_criteria_digest))
                or (old.consumed and (not new.consumed or old.response_refs != new.response_refs
                    or old.assistant != new.assistant or old.status != new.status
                    or old.protocol_exchanges != new.protocol_exchanges or old.diagnostics != new.diagnostics))):
            raise ConversationOperationConflict("模型调用、响应及已提交处置不可改写")


def _disposition_content(disposition: ModelCallDisposition, prompts: PromptCatalog,
                         trace: InteractionTrace, decision_turn: int) -> str:
    if disposition.operation in ("maintain_goal", "read_current_goal"):
        record = next((item for item in trace.goal_operations
                       if item.call_id == disposition.call_id and item.decision_turn == decision_turn), None)
        if record is None:
            raise ConversationOperationConflict("accepted goal call has no committed operation")
        return goal_tool_result(record, prompts=prompts)
    return render_control_disposition(disposition, prompts=prompts)


def render_control_disposition(disposition: ModelCallDisposition, *, prompts: PromptCatalog) -> str:
    message = prompts.get("conversation.native_control." + disposition.status).template
    if disposition.plan_id is not None:
        message += "\n" + prompts.render("conversation.context.control.plan",
            plan_id=disposition.plan_id, revision=disposition.plan_revision)
        if disposition.working_plan_snapshot is not None:
            message += "\n" + render_working_plan(disposition.working_plan_snapshot, prompts=prompts)
        return message
    if disposition.operation == "read_working_plan" and disposition.status == "accepted":
        return prompts.get("conversation.plan.empty").template
    if disposition.operation_ref is not None:
        return message + "\n" + prompts.render("conversation.context.control.operation",
            operation_ref=disposition.operation_ref)
    return message


def _submitted_arguments(assistant: ModelAssistantMessage, call_id: str, action_name: str) -> dict | None:
    for call in assistant.payload.get("tool_calls") or ():
        if call["id"] != call_id:
            continue
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != action_name:
            return None
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                value = json.loads(arguments)
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


def _paired_rejection_content(
    rejection: DecisionFeedback, assistant: ModelAssistantMessage, call_id: str, prompts: PromptCatalog,
) -> str:
    unpaired = tuple(call for call in rejection.rejected_action_invocations if call.call_id not in assistant.call_ids)
    repair = rejection.required_repair
    if rejection.rejected_action_invocations and not unpaired and rejection.action_diagnostics and all(
        diagnostic.error_type == "schema_type" and f"`{diagnostic.field_path}`" in repair
        for diagnostic in rejection.action_diagnostics
    ):
        return repair
    return render_decision_feedback(rejection.model_copy(update={"rejected_action_invocations": unpaired}),
        prompts=prompts, submitted_arguments=_submitted_arguments(assistant, call_id, rejection.action_name))


def project_model_history(
    trace: InteractionTrace, visible: Sequence[CitableInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, covered_through: int = 0,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[CitableInput, ...]]:
    """Use only already materialized/visible facts, never raw tool payloads."""
    keyed = {input_identity(item.observation): item for item in visible
             if input_identity(item.observation) is not None}
    consumed: set[HistoryItemKey] = set()
    exchanges: list[ModelHistoryEntry] = []
    switch_turn = task_switch_turn(trace)
    for record in trace.model_decisions:
        if record.turn_index is None or not record.consumed:
            continue
        if record.turn_index <= switch_turn:
            consumed.update(input_identity(trace.inputs[index])
                            for index in decision_input_indices(trace, record))
            continue
        if record.turn_index <= covered_through:
            continue
        if record.assistant is None:
            # A failed envelope has no legal call IDs; do not invent a native exchange.
            continue
        indices = decision_input_indices(trace, record)
        keys = {input_identity(trace.inputs[index]) for index in indices}
        if not keys <= keyed.keys():
            # A visibility/selection boundary removes the whole exchange, never
            # recovers its hidden result from the raw Journal.
            continue
        if goal_pending_rejection(trace, record) is not None:
            rejected_key = record.blocked_by
            if rejected_key is not None and rejected_key in keyed:
                exchanges.append(ModelRuntimeFeedback(
                    feedback=render_citable_input(keyed[rejected_key], prompts=prompts)))
                consumed.add(rejected_key)
                continue
        dispositions = {item.call_id: item for item in record.dispositions}
        results = []
        for call_id in record.assistant.call_ids:
            own_keys = {input_identity(trace.inputs[index]) for index in indices
                        if trace.inputs[index].action_id == call_id}
            candidates = [item for item in visible if input_identity(item.observation) in own_keys]
            if candidates:
                item = candidates[-1]
                content = (_paired_rejection_content(item.observation, record.assistant, call_id, prompts)
                           if isinstance(item.observation, DecisionFeedback)
                           else render_citable_input(item, prompts=prompts, native_tool_result=True))
                results.append(ModelToolResult(call_id=call_id, content=content))
                consumed.add(input_identity(item.observation))
            elif call_id in dispositions:
                results.append(ModelToolResult(call_id=call_id,
                    content=_disposition_content(dispositions[call_id], prompts, trace, record.turn_index)))
            elif any(item.action_id == call_id for item in trace.accepted_tool_requests):
                raise ConversationOperationConflict("原生工具调用仍缺少已接受执行的恢复结果")
            elif record.blocked_by is not None and record.blocked_by in keyed:
                feedback = keyed[record.blocked_by].observation
                if not isinstance(feedback, DecisionFeedback):
                    raise ConversationOperationConflict("原生调用的拒绝记录类型不正确")
                results.append(ModelToolResult(call_id=call_id,
                    content=_paired_rejection_content(feedback, record.assistant, call_id, prompts)))
                consumed.add(record.blocked_by)
            else:
                raise ConversationOperationConflict("原生工具调用缺少真实结果或拒绝，不能续接")
        exchanges.extend(record.protocol_exchanges)
        # A real assistant-only answer/rejection is also a complete exchange.
        # Empty call IDs retain the original body and require no tool result.
        feedback = tuple(keyed[key] for index in indices
                         if (key := input_identity(trace.inputs[index])) not in consumed)
        exchanges.append(ModelToolExchange(assistant=record.assistant, results=tuple(results),
            runtime_feedback=tuple(render_citable_input(item, prompts=prompts) for item in feedback)))
        consumed.update(input_identity(item.observation) for item in feedback)
    return tuple(exchanges), tuple(item for item in visible if input_identity(item.observation) not in consumed)


_PLAN_REVIEW_DELIVERIES = tuple(create_prompt_catalog(language).render("conversation.service.plan_review_ready")
                                for language in ("zh", "en"))


def _matches_analysis_delivery(trace: InteractionTrace, content: str) -> bool:
    if trace.final_message is not None:
        return trace.final_message.message == content
    last = next((item for item in reversed(trace.model_decisions) if item.turn_index is not None), None)
    waiting = next((item for item in last.dispositions if item.plan_waiting), None) if last else None
    if waiting is None:
        return False
    # Older waiting plans used the localized fallback from the native action.
    if waiting.plan_review_message is None:
        return content in _PLAN_REVIEW_DELIVERIES
    return waiting.plan_review_message == content


def prior_analysis_turns(
    trace: InteractionTrace, candidates: Sequence[InteractionTrace],
) -> tuple[InteractionTrace, ...]:
    """Select completed runs on this exact conversation branch, without new authority."""
    matched: dict[int, InteractionTrace] = {}
    for source in candidates:
        end = len(source.messages)
        if (source.interaction_run_ref == trace.interaction_run_ref
                or source.principal != trace.principal or source.conversation_id != trace.conversation_id
                or source.python_authorization_digest != trace.python_authorization_digest
                or end >= len(trace.messages)
                or source.messages != trace.messages[:end]
                or trace.messages[end].role != "assistant"):
            continue
        if not _matches_analysis_delivery(source, trace.messages[end].content):
            continue
        if end in matched:
            raise ConversationOperationConflict("会话历史存在同一轮的多个已结束运行，不能选择原生历史")
        matched[end] = source
    return tuple(matched[end] for end in sorted(matched))


def selected_analysis_turns(
    trace: InteractionTrace, candidates: Sequence[InteractionTrace],
) -> tuple[InteractionTrace, ...]:
    return AnalysisTaskHistory.from_turns(prior_analysis_turns(trace, candidates)).selected_turns(trace)


def project_conversation_history(
    trace: InteractionTrace, previous: Sequence[InteractionTrace], visible: Sequence[CitableInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, candidate: HistoryCompactionCheckpoint | None = None,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[CitableInput, ...]]:
    """Place prior complete exchanges before their displayed final answer."""
    exchanges: list[ModelHistoryEntry] = []
    remaining = tuple(visible)
    checkpoint = candidate or active_history_checkpoint(trace, previous)
    coverage = {item.run_ref: item.through_turn for item in checkpoint.sources} if checkpoint else {}
    indices = task_message_indices(trace, previous)
    for source in previous:
        # These Runtime facts are from an already scoped, exact predecessor.
        # Keep them on their original exchange, never in current pending feedback.
        original_visible = remaining
        feedback = tuple(CitableInput(observation=item) for item in source.inputs
                         if isinstance(item, DecisionFeedback)
                         or (isinstance(item, ActionObservation)
                             and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY))
        source_visible = tuple(item for item in remaining
                               if not is_runtime_feedback(item.observation))
        history, projected = project_model_history(source, (*source_visible, *feedback), prompts=prompts,
            covered_through=coverage.get(source.interaction_run_ref, 0))
        history = _with_prefix_summary(history, source.interaction_run_ref, checkpoint, prompts)
        remaining = tuple(item for item in original_visible
                          if is_runtime_feedback(item.observation) or item in projected)
        # The request's stable system prefix occupies position zero.
        position = indices.index(len(source.messages)) + 1
        exchanges.extend(item.model_copy(update={"before_message_index": position}) for item in history)
    history, remaining = project_model_history(trace, remaining, prompts=prompts,
        covered_through=coverage.get(trace.interaction_run_ref, 0))
    history = _with_prefix_summary(history, trace.interaction_run_ref, checkpoint, prompts)
    return (*exchanges, *history), remaining


def history_summary_context(checkpoint: HistoryCompactionCheckpoint, prompts: PromptCatalog) -> str:
    coverage = "\n".join(prompts.render("conversation.context.history_coverage",
        run_ref=item.run_ref, turn=item.through_turn,
        delivery=prompts.get("conversation.context.history.delivered" if item.includes_final
                             else "conversation.context.history.partial").template)
        for item in checkpoint.sources)
    return prompts.render("conversation.history.summary_view", summary=checkpoint.working_summary, coverage=coverage)


def _with_prefix_summary(history, run_ref, checkpoint, prompts):
    if not history or checkpoint is None:
        return history
    last = checkpoint.sources[-1]
    if last.run_ref != run_ref or last.includes_final:
        return history
    first = history[0].model_copy(update={"context_before": (
        history_summary_context(checkpoint, prompts), *history[0].context_before)})
    return (first, *history[1:])


def is_runtime_feedback(item) -> bool:
    return isinstance(item, DecisionFeedback) or (
        isinstance(item, ActionObservation) and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY)


def active_history_checkpoint(
    trace: InteractionTrace, previous: Sequence[InteractionTrace],
) -> HistoryCompactionCheckpoint | None:
    """The most recent scoped projection covers all predecessor runs together."""
    by_run = {source.interaction_run_ref: source for source in (*previous, trace)}
    return next((checkpoint for source in (trace, *reversed(previous))
                 if (checkpoint := source.history_compaction) is not None
                 and checkpoint.run_ref in by_run
                 and all(item.run_ref in by_run and item.through_turn >= task_switch_turn(by_run[item.run_ref])
                         for item in checkpoint.sources)), None)


def deferred_controls(decision) -> tuple[ModelCallDisposition, ...]:
    return ((ModelCallDisposition(call_id=decision.working_plan_call_id,
                operation="working_plan", status="deferred"),)
            if decision.working_plan_call_id is not None else ())

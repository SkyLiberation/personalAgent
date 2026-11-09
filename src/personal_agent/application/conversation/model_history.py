"""Native model exchanges projected from the run's canonical decision facts."""
from collections.abc import Sequence
import json

from personal_agent.capabilities.contracts.model import (
    ModelHistoryEntry, ModelRuntimeFeedback, ModelToolExchange, ModelToolResult, StructuredModelResponse,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .citations import CitableInput, render_citable_input
from .errors import ConversationOperationConflict
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey
from .goal_maintenance import goal_tool_result
from .goal_models import GOAL_PENDING_ACTION_REJECTED
from .verification_admission import INTERACTION_VERIFICATION_CAPABILITY
from .models import (
    ActionObservation, DecisionFeedback, InteractionTrace, ModelCallDisposition, ModelDecisionRecord,
)


def input_identity(item) -> HistoryItemKey | None:
    if isinstance(item, (ActionObservation, DecisionFeedback)):
        return HistoryItemKey(kind=item.kind, action_id=item.action_id,
                              decision_turn=getattr(item, "decision_turn", None))
    return None


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
    prompt = prompts.get("conversation.native_control." + disposition.status)
    return json.dumps({"message": prompt.template, "disposition": disposition.model_dump(mode="json", exclude_none=True)},
                      ensure_ascii=False)


def _paired_rejection_content(
    feedback: CitableInput, call_ids: tuple[str, ...], prompts: PromptCatalog,
) -> str:
    rejection = feedback.observation
    if isinstance(rejection, DecisionFeedback) and rejection.rejected_action_invocations:
        unpaired = tuple(call for call in rejection.rejected_action_invocations if call.call_id not in call_ids)
        repair = rejection.required_repair
        # Older feedback can have field diagnostics and only a generic retry instruction.
        if not unpaired and rejection.action_diagnostics and all(
            diagnostic.error_type == "schema_type" and f"`{diagnostic.field_path}`" in repair
            for diagnostic in rejection.action_diagnostics
        ):
            return repair
        # The paired assistant message already contains the other original arguments.
        feedback = feedback.model_copy(update={"observation": rejection.model_copy(
            update={"rejected_action_invocations": unpaired})})
    return render_citable_input(feedback, prompts=prompts)


def project_model_history(
    trace: InteractionTrace, visible: Sequence[CitableInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, covered_through: int = 0,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[CitableInput, ...]]:
    """Use only already materialized/visible facts, never raw tool payloads."""
    keyed = {input_identity(item.observation): item for item in visible
             if input_identity(item.observation) is not None}
    consumed: set[HistoryItemKey] = set()
    exchanges: list[ModelHistoryEntry] = []
    for record in trace.model_decisions:
        if record.turn_index is None or not record.consumed or record.turn_index <= covered_through:
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
                results.append(ModelToolResult(call_id=call_id,
                    content=render_citable_input(item, prompts=prompts)))
                consumed.add(input_identity(item.observation))
            elif call_id in dispositions:
                results.append(ModelToolResult(call_id=call_id,
                    content=_disposition_content(dispositions[call_id], prompts, trace, record.turn_index)))
            elif any(item.action_id == call_id for item in trace.accepted_tool_requests):
                raise ConversationOperationConflict("原生工具调用仍缺少已接受执行的恢复结果")
            elif record.blocked_by is not None and record.blocked_by in keyed:
                feedback = keyed[record.blocked_by]
                results.append(ModelToolResult(call_id=call_id,
                    content=_paired_rejection_content(feedback, record.assistant.call_ids, prompts)))
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
                or source.final_message is None or end >= len(trace.messages)
                or source.messages != trace.messages[:end]
                or trace.messages[end].role != "assistant"
                or trace.messages[end].content != source.final_message.message):
            continue
        if end in matched:
            raise ConversationOperationConflict("会话历史存在同一轮的多个已结束运行，不能选择原生历史")
        matched[end] = source
    return tuple(matched[end] for end in sorted(matched))


def project_conversation_history(
    trace: InteractionTrace, previous: Sequence[InteractionTrace], visible: Sequence[CitableInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, candidate: HistoryCompactionCheckpoint | None = None,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[CitableInput, ...]]:
    """Place prior complete exchanges before their displayed final answer."""
    exchanges: list[ModelHistoryEntry] = []
    remaining = tuple(visible)
    checkpoint = candidate or active_history_checkpoint(trace, previous)
    coverage = {item.run_ref: item.through_turn for item in checkpoint.sources} if checkpoint else {}
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
        position = len(source.messages) + 1
        exchanges.extend(item.model_copy(update={"before_message_index": position}) for item in history)
    history, remaining = project_model_history(trace, remaining, prompts=prompts,
        covered_through=coverage.get(trace.interaction_run_ref, 0))
    history = _with_prefix_summary(history, trace.interaction_run_ref, checkpoint, prompts)
    return (*exchanges, *history), remaining


def history_summary_context(checkpoint: HistoryCompactionCheckpoint, prompts: PromptCatalog) -> str:
    return prompts.render("conversation.history.summary_view", summary=checkpoint.working_summary,
        resource_id=checkpoint.snapshot_ref.resource_id,
        coverage=json.dumps([item.model_dump(mode="json") for item in checkpoint.sources], ensure_ascii=False))


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
    return next((source.history_compaction for source in (trace, *reversed(previous))
                 if source.history_compaction is not None), None)


def deferred_controls(decision) -> tuple[ModelCallDisposition, ...]:
    return ((ModelCallDisposition(call_id=decision.working_plan_call_id,
                operation="working_plan", status="deferred"),)
            if decision.working_plan_call_id is not None else ())

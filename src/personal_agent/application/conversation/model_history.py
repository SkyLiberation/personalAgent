"""Native model exchanges projected from the run's canonical decision facts."""
from collections.abc import Sequence
import json

from personal_agent.capabilities.contracts.model import ModelToolExchange, ModelToolResult, StructuredModelResponse
from personal_agent.kernel.prompts import get_prompt

from .citations import CitableInput
from .errors import ConversationOperationConflict
from .history_models import HistoryItemKey
from .models import (
    ActionObservation, DecisionFeedback, InteractionTrace, ModelCallDisposition, ModelDecisionRecord,
)


def input_identity(item) -> HistoryItemKey | None:
    if isinstance(item, (ActionObservation, DecisionFeedback)):
        return HistoryItemKey(kind=item.kind, action_id=item.action_id,
                              decision_turn=getattr(item, "decision_turn", None))
    return None


def decision_input_indices(trace: InteractionTrace, record: ModelDecisionRecord) -> tuple[int, ...]:
    if record.turn_index is None or record.assistant is None:
        return ()
    ids = set(record.assistant.call_ids)
    indices = []
    for index, item in enumerate(trace.inputs):
        if record.blocked_by is not None and input_identity(item) == record.blocked_by:
            indices.append(index)
        elif isinstance(item, DecisionFeedback):
            if item.action_id in ids and item.decision_turn == record.turn_index:
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


def _disposition_content(disposition: ModelCallDisposition) -> str:
    prompt = get_prompt("conversation.native_control." + disposition.status)
    return json.dumps({"message": prompt.template, "disposition": disposition.model_dump(mode="json", exclude_none=True)},
                      ensure_ascii=False)


def project_model_history(
    trace: InteractionTrace, visible: Sequence[CitableInput],
) -> tuple[tuple[ModelToolExchange, ...], tuple[CitableInput, ...]]:
    """Use only already materialized/visible facts, never raw tool payloads."""
    covered = set(trace.history_compaction.covered_decision_turns) if trace.history_compaction else set()
    keyed = {input_identity(item.observation): item for item in visible
             if input_identity(item.observation) is not None}
    consumed: set[HistoryItemKey] = set()
    exchanges = []
    for record in trace.model_decisions:
        if record.turn_index is None or not record.consumed:
            continue
        if record.assistant is None:
            # A failed envelope has no legal call IDs; do not invent a native exchange.
            continue
        indices = decision_input_indices(trace, record)
        keys = {input_identity(trace.inputs[index]) for index in indices}
        if record.turn_index in covered and (not keys or not keys <= keyed.keys()):
            continue
        if not keys <= keyed.keys():
            # A visibility/selection boundary removes the whole exchange, never
            # recovers its hidden result from the raw Journal.
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
                    content=json.dumps(item.model_dump(mode="json"), ensure_ascii=False)))
                consumed.add(input_identity(item.observation))
            elif call_id in dispositions:
                results.append(ModelToolResult(call_id=call_id, content=_disposition_content(dispositions[call_id])))
            elif any(item.action_id == call_id for item in trace.accepted_tool_requests):
                raise ConversationOperationConflict("原生工具调用仍缺少已接受执行的恢复结果")
            elif record.blocked_by is not None and record.blocked_by in keyed:
                feedback = keyed[record.blocked_by]
                results.append(ModelToolResult(call_id=call_id,
                    content=json.dumps(feedback.model_dump(mode="json"), ensure_ascii=False)))
                consumed.add(record.blocked_by)
            else:
                raise ConversationOperationConflict("原生工具调用缺少真实结果或拒绝，不能续接")
        exchanges.extend(record.protocol_exchanges)
        # A real assistant-only answer/rejection is also a complete exchange.
        # Empty call IDs retain the original body and require no tool result.
        exchanges.append(ModelToolExchange(assistant=record.assistant, results=tuple(results)))
    return tuple(exchanges), tuple(item for item in visible if input_identity(item.observation) not in consumed)


def deferred_controls(decision) -> tuple[ModelCallDisposition, ...]:
    return ((ModelCallDisposition(call_id=decision.working_plan_call_id,
                operation="working_plan", status="deferred"),)
            if decision.working_plan_call_id is not None else ())

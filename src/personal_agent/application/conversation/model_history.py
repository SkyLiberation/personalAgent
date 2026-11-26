"""Native model exchanges projected from the run's canonical decision facts."""
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
import json
from typing import Any

from personal_agent.capabilities.contracts.model import (
    ModelAssistantMessage, ModelHistoryEntry, ModelRuntimeFeedback, ModelToolExchange, ModelToolResult,
    ModelUserHistoryMessage, StructuredModelResponse,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.contracts.goal import ConversationGoalMode
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .artifact_sources import tool_result_artifact_refs
from .interaction_projection import ProjectedInteractionInput, render_interaction_input, render_decision_feedback
from .analysis_tasks import AnalysisTaskHistory, task_message_indices, task_switch_turn
from .errors import ConversationOperationConflict
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey
from .history_tool_pruning import prune_history_tool_result
from .skills import LOAD_SKILL_CAPABILITY, LoadedSkill
from .goal_maintenance import goal_tool_result
from .goal_models import GOAL_PENDING_ACTION_REJECTED
from .verification_admission import INTERACTION_VERIFICATION_CAPABILITY
from .working_plan import render_working_plan
from .models import (
    ActionObservation, ArtifactSourceInput, ConversationWorkingPlan, DecisionFeedback, InteractionTrace, ModelCallDisposition,
    ModelDecisionRecord, SubmittedFinal,
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
        if record.step_no is not None and record.step_no <= switch_turn
        for index in decision_input_indices(trace, record))


def goal_pending_rejection(trace: InteractionTrace, record: ModelDecisionRecord) -> DecisionFeedback | None:
    if record.blocked_by is None:
        return None
    return next((item for item in trace.inputs
                 if isinstance(item, DecisionFeedback) and item.reason_code == GOAL_PENDING_ACTION_REJECTED
                 and input_identity(item) == record.blocked_by), None)


def decision_input_indices(trace: InteractionTrace, record: ModelDecisionRecord) -> tuple[int, ...]:
    if record.step_no is None or record.assistant is None:
        return ()
    ids = set(record.assistant.call_ids)
    end = next((other.input_start for other in trace.responded_steps
                if other.step_no is not None and other.step_no > record.step_no), len(trace.inputs))
    indices = []
    for index, item in enumerate(trace.inputs):
        if record.blocked_by is not None and input_identity(item) == record.blocked_by:
            indices.append(index)
        elif isinstance(item, DecisionFeedback):
            if item.decision_turn == record.step_no:
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
                    and feedback.decision_turn == caller.step_no
                    and (feedback.action_id == item.action_id
                         or (input_identity(feedback) == caller.blocked_by
                             and feedback.action_id not in caller.assistant.call_ids))
                    for feedback in trace.inputs)
                if not rejected:
                    eligible.append(caller.step_no)
            if eligible and eligible[-1] == record.step_no:
                indices.append(index)
    return tuple(indices)


def update_decisions(
    trace: InteractionTrace | None, *, inputs, step_no: int,
    response: StructuredModelResponse | None = None,
    dispositions: tuple[ModelCallDisposition, ...] = (),
) -> tuple[ModelDecisionRecord, ...]:
    records = list(trace.model_decisions if trace is not None else ())
    index = next((i for i in range(len(records) - 1, -1, -1)
                  if records[i].step_no == step_no), None)
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
                         and item.decision_turn == step_no), None)
        blocked_by = input_identity(feedback) if feedback is not None else None
    records[index] = record.model_copy(update={"dispositions": tuple(current.values()), "blocked_by": blocked_by})
    return tuple(records)


def validate_decision_extension(previous: InteractionTrace, current: InteractionTrace) -> None:
    if len(current.model_decisions) < len(previous.model_decisions):
        raise ConversationOperationConflict("原生模型历史不可删除")
    for old, new in zip(previous.model_decisions, current.model_decisions):
        if (old.invocation_id != new.invocation_id or old.operation != new.operation or old.request != new.request
                or old.step_no != new.step_no or old.input_start != new.input_start
                or new.response_refs[:len(old.response_refs)] != old.response_refs
                or new.protocol_exchanges[:len(old.protocol_exchanges)] != old.protocol_exchanges
                or new.dispositions[:len(old.dispositions)] != old.dispositions
                or (old.blocked_by is not None and old.blocked_by != new.blocked_by)
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
        return f"{rejection.message}\n{repair}" if rejection.action_id == call_id else repair
    return render_decision_feedback(rejection.model_copy(update={"rejected_action_invocations": unpaired}),
        prompts=prompts, submitted_arguments=_submitted_arguments(assistant, call_id, rejection.action_name))


def _successful_skill_name(item: ProjectedInteractionInput | None) -> str | None:
    observation = item.observation if item is not None else None
    if (isinstance(observation, ActionObservation) and observation.capability_id == LOAD_SKILL_CAPABILITY
            and observation.status == "succeeded"):
        return LoadedSkill.model_validate(observation.payload.get("data")).name
    return None


def project_model_history(
    trace: InteractionTrace, visible: Sequence[ProjectedInteractionInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, covered_through: int = 0,
    working_plan: ConversationWorkingPlan | None = None,
    prune_through: int = 0,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[ProjectedInteractionInput, ...], bool]:
    """Use only already materialized/visible facts, never raw tool payloads."""
    keyed = {input_identity(item.observation): item for item in visible
             if input_identity(item.observation) is not None}
    artifacts = {item.observation.resource.resource_ref: item for item in visible
                 if isinstance(item.observation, ArtifactSourceInput)}
    published = tool_result_artifact_refs(trace)
    consumed: set[HistoryItemKey] = set()
    exchanges: list[ModelHistoryEntry] = []
    emitted_turns: set[int] = set()
    current_plan_visible = False
    switch_turn = task_switch_turn(trace)
    steering = iter(trace.steering)
    supplement = next(steering, None)
    last_skill_name: str | None = None
    consecutive_skill_loads = 0
    for record in trace.model_decisions:
        if record.step_no is None:
            continue
        while supplement is not None and supplement.after_step < record.step_no:
            exchanges.append(ModelUserHistoryMessage(user_text=supplement.text))
            supplement = next(steering, None)
            last_skill_name = None
            consecutive_skill_loads = 0
        if not record.consumed:
            continue
        if record.step_no <= switch_turn:
            consumed.update(input_identity(trace.inputs[index])
                            for index in decision_input_indices(trace, record))
            continue
        if record.step_no <= covered_through:
            continue
        if record.assistant is None:
            # A failed envelope has no legal call IDs; do not invent a native exchange.
            continue
        indices = decision_input_indices(trace, record)
        keys = {input_identity(trace.inputs[index]) for index in indices}
        if not keys <= keyed.keys():
            # A visibility/selection boundary removes the whole exchange, never
            # recovers its hidden result from the raw Journal.
            last_skill_name = None
            consecutive_skill_loads = 0
            continue
        if goal_pending_rejection(trace, record) is not None:
            rejected_key = record.blocked_by
            if rejected_key is not None and rejected_key in keyed:
                exchanges.append(ModelRuntimeFeedback(
                    feedback=render_interaction_input(keyed[rejected_key], prompts=prompts)))
                consumed.add(rejected_key)
                last_skill_name = None
                consecutive_skill_loads = 0
                continue
        dispositions = {item.call_id: item for item in record.dispositions}
        prune_results = record.step_no <= prune_through
        results = []
        skill_notices = []
        for call_id in record.assistant.call_ids:
            own_keys = {input_identity(trace.inputs[index]) for index in indices
                        if trace.inputs[index].action_id == call_id}
            candidates = [item for item in visible if input_identity(item.observation) in own_keys]
            item = candidates[-1] if candidates else None
            skill_name = _successful_skill_name(item)
            if skill_name != last_skill_name:
                last_skill_name = skill_name
                consecutive_skill_loads = 0
            if skill_name is not None:
                consecutive_skill_loads += 1
                if consecutive_skill_loads in (3, 5, 8):
                    skill_notices.append(prompts.render("skills.repeat_notice", skill_name=skill_name,
                                                       count=consecutive_skill_loads))
            if item is not None:
                content = (_paired_rejection_content(item.observation, record.assistant, call_id, prompts)
                           if isinstance(item.observation, DecisionFeedback)
                           else render_interaction_input(item, prompts=prompts, native_tool_result=True))
                if isinstance(item.observation, ActionObservation):
                    if prune_results and item.observation.status in {"succeeded", "failed", "cancelled"}:
                        content = prune_history_tool_result(content, prompts=prompts)
                    materials = (render_interaction_input(artifacts[ref], prompts=prompts)
                                 for ref in published.get(call_id, ()) if ref in artifacts)
                    content = "\n\n".join((content, *materials))
                results.append(ModelToolResult(call_id=call_id, content=content))
                consumed.add(input_identity(item.observation))
            elif call_id in dispositions:
                disposition = dispositions[call_id]
                content = _disposition_content(disposition, prompts, trace, record.step_no)
                shows_current_plan = working_plan is not None and disposition.working_plan_snapshot == working_plan
                if prune_results and disposition.status == "accepted" and not shows_current_plan:
                    content = prune_history_tool_result(content, prompts=prompts)
                results.append(ModelToolResult(call_id=call_id, content=content))
                current_plan_visible |= shows_current_plan
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
            runtime_feedback=(*(render_interaction_input(item, prompts=prompts) for item in feedback), *skill_notices)))
        emitted_turns.add(record.step_no)
        consumed.update(input_identity(item.observation) for item in feedback)
    if supplement is not None:
        exchanges.append(ModelUserHistoryMessage(user_text=supplement.text))
        exchanges.extend(ModelUserHistoryMessage(user_text=item.text) for item in steering)
    # A submission records the answer decoded from its original decision.
    # Omit its second rendering only when that Run's original exchange is visible.
    remaining = tuple(
        item for item in visible
        if input_identity(item.observation) not in consumed
        and not (isinstance(item.observation, SubmittedFinal)
                 and item.observation.resource_ref.revision in emitted_turns
                 and item.observation in trace.inputs)
    )
    return tuple(exchanges), remaining, current_plan_visible



def prior_analysis_turns(
    trace: InteractionTrace, candidates: Sequence[InteractionTrace],
) -> tuple[InteractionTrace, ...]:
    """Exclude the current turn from the Journal's scoped timeline."""
    return tuple(source for source in candidates if source.interaction_run_ref != trace.interaction_run_ref)


def selected_analysis_turns(
    trace: InteractionTrace, candidates: Sequence[InteractionTrace],
) -> tuple[InteractionTrace, ...]:
    previous = prior_analysis_turns(trace, candidates)
    if trace.goal_mode is ConversationGoalMode.DISABLED:
        return previous
    return AnalysisTaskHistory.from_turns(previous).selected_turns(trace)


def _observation_lookup_key(item: ProjectedInteractionInput) -> tuple[str, str]:
    observation = item.observation
    if isinstance(observation, ArtifactSourceInput):
        return observation.kind, observation.resource.resource_ref.resource_id
    return observation.kind, observation.action_id


def project_conversation_history(
    trace: InteractionTrace, previous: Sequence[InteractionTrace], visible: Sequence[ProjectedInteractionInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS, candidate: HistoryCompactionCheckpoint | None = None,
    working_plan: ConversationWorkingPlan | None = None,
    tool_pruning: Mapping[str, int] | None = None,
) -> tuple[tuple[ModelHistoryEntry, ...], tuple[ProjectedInteractionInput, ...], bool]:
    """Place prior complete exchanges before their displayed final answer."""
    exchanges: list[ModelHistoryEntry] = []
    remaining = tuple(visible)
    predecessor_plan_visible = False
    checkpoint = candidate or active_history_checkpoint(trace, previous)
    coverage = {item.run_ref: item.through_turn for item in checkpoint.sources} if checkpoint else {}
    pruning = tool_pruning or {}
    indices = task_message_indices(trace, previous)
    for source in previous:
        # These Runtime facts are from an already scoped, exact predecessor.
        # Keep them on their original exchange, never in current pending feedback.
        original_visible = remaining
        feedback = tuple(ProjectedInteractionInput(observation=item) for item in source.inputs
                         if isinstance(item, DecisionFeedback)
                         or (isinstance(item, ActionObservation)
                             and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY))
        source_visible = tuple(item for item in remaining
                               if not is_runtime_feedback(item.observation))
        history, projected, plan_visible = project_model_history(
            source, (*source_visible, *feedback), prompts=prompts,
            covered_through=coverage.get(source.interaction_run_ref, 0), working_plan=working_plan,
            prune_through=pruning.get(source.interaction_run_ref, 0))
        predecessor_plan_visible |= plan_visible
        history = _with_prefix_summary(history, source.interaction_run_ref, checkpoint, prompts)
        by_observation: dict[tuple[str, str], list[ProjectedInteractionInput]] = defaultdict(list)
        for item in projected:
            by_observation[_observation_lookup_key(item)].append(item)
        # Identity narrows the search. Equal IDs can still carry different results.
        remaining = tuple(item for item in original_visible
                          if is_runtime_feedback(item.observation)
                          or item in by_observation.get(_observation_lookup_key(item), ()))
        # The request's stable system prefix occupies position zero.
        position = indices.index(len(source.messages)) + 1
        exchanges.extend(item.model_copy(update={"before_message_index": position}) for item in history)
    history, remaining, plan_visible = project_model_history(trace, remaining, prompts=prompts,
        covered_through=coverage.get(trace.interaction_run_ref, 0), working_plan=working_plan,
        prune_through=pruning.get(trace.interaction_run_ref, 0))
    history = _with_prefix_summary(history, trace.interaction_run_ref, checkpoint, prompts)
    return (*exchanges, *history), remaining, plan_visible or predecessor_plan_visible


def _delivered_native_answer(trace: InteractionTrace) -> ModelAssistantMessage | None:
    final = trace.final_message
    if final is None or final.disposition != "answer":
        return None
    submission = next((item for item in reversed(trace.inputs) if isinstance(item, SubmittedFinal)), None)
    if submission is None or submission.final != final:
        return None
    assistant = next((record.assistant for record in trace.model_decisions
                      if record.step_no == submission.resource_ref.revision), None)
    if assistant is None or assistant.call_ids or assistant.visible_text != final.message:
        return None
    return assistant


def omit_replayed_delivered_answers(
    trace: InteractionTrace, previous: Sequence[InteractionTrace],
    messages: list[dict[str, Any]], history: tuple[ModelHistoryEntry, ...],
) -> tuple[list[dict[str, Any]], tuple[ModelHistoryEntry, ...]]:
    """Keep one visible delivered answer, preferring its original native message."""
    positions = {index: position for position, index in enumerate(task_message_indices(trace, previous), 1)}
    delivered_answers: dict[int, ModelAssistantMessage] = {}
    for source in previous:
        assistant = _delivered_native_answer(source)
        position = positions[len(source.messages)]
        if assistant is not None and messages[position] == {"role": "assistant", "content": assistant.visible_text}:
            delivered_answers[position] = assistant

    # A summary or visibility filter can remove the native exchange before this merge.
    omitted = {position for exchange in history if isinstance(exchange, ModelToolExchange)
               and (position := exchange.before_message_index) is not None
               and delivered_answers.get(position) == exchange.assistant}
    if not omitted:
        return messages, history

    ordered_omitted = sorted(omitted)
    projected_messages = [message for position, message in enumerate(messages) if position not in omitted]
    projected_history = tuple(
        exchange.model_copy(update={"before_message_index": position - bisect_left(ordered_omitted, position)})
        if (position := exchange.before_message_index) is not None else exchange
        for exchange in history
    )
    return projected_messages, projected_history


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

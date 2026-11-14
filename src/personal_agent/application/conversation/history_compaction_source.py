"""Select and bind complete, run-scoped history prefixes for summarization."""
from bisect import bisect_right
from collections.abc import Sequence
from hashlib import sha256
import json

from personal_agent.application.artifacts.models import TextPosition
from personal_agent.application.artifacts.text_coordinates import TextCoordinates
from personal_agent.capabilities.contracts.model import ModelAssistantMessage
from personal_agent.kernel.prompt_registry import PromptCatalog

from .artifact_sources import input_resource_refs
from .analysis_tasks import task_switch_turn
from .citations import CitableInput, render_citable_input
from .context_materialization import materialize_interaction_inputs
from .goal_maintenance import goal_tool_result
from .history_models import HistoryCompactionCheckpoint, HistoryRunCoverage
from .model_history import decision_input_indices, goal_pending_rejection, render_control_disposition
from .models import AcceptedArtifactToolRequest, AcceptedPythonToolRequest, ActionObservation, InteractionInput, InteractionTrace, ModelDecisionRecord


def history_digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def main_decisions(trace: InteractionTrace) -> tuple[ModelDecisionRecord, ...]:
    switch_turn = task_switch_turn(trace)
    return tuple(record for record in trace.model_decisions
                 if record.turn_index is not None and record.turn_index > switch_turn
                 and record.assistant is not None and record.consumed)


def decision_source(trace: InteractionTrace, record: ModelDecisionRecord) -> dict:
    rejected = goal_pending_rejection(trace, record)
    if rejected is not None:
        return {"decision_turn": record.turn_index, "results_and_feedback": [
            rejected.model_dump(mode="json", exclude={"rejected_action_invocations"})
        ]}
    # Summaries need observable choices and results, not provider-private reasoning.
    assistant = {key: value for key, value in record.assistant.payload.items()
                 if key in {"role", "content", "tool_calls"}}
    return {
        "decision_turn": record.turn_index,
        "assistant": assistant,
        "protocol_exchanges": [{"assistant": {
            key: value for key, value in exchange.assistant.payload.items()
            if key in {"role", "content", "tool_calls"}},
            "results": [item.model_dump(mode="json") for item in exchange.results],
            "runtime_feedback": exchange.runtime_feedback} for exchange in record.protocol_exchanges],
        "results_and_feedback": [trace.inputs[index].model_dump(mode="json")
                                 for index in decision_input_indices(trace, record)],
        "dispositions": [
            item.model_dump(mode="json", exclude={
                field for field in ("working_plan_snapshot", "plan_waiting", "plan_review_message") if not getattr(item, field)
            })
            for item in record.dispositions
        ],
        "goal_operations": [item.model_dump(mode="json", exclude={"patch": {
            field for field in ("resolve_clarification", "delivery")
            if item.patch is not None and getattr(item.patch, field) is None
        }}) for item in trace.goal_operations
                            if item.decision_turn == record.turn_index],
    }


def run_source(trace: InteractionTrace, through_turn: int, includes_final: bool,
               *, after_turn: int = 0) -> dict:
    source = {
        "run_ref": trace.interaction_run_ref,
        "user_request": trace.messages[-1].model_dump(mode="json"),
        "decisions": [decision_source(trace, record) for record in main_decisions(trace)
                      if after_turn < record.turn_index <= through_turn],
        "delivered_result": trace.final_message.model_dump(mode="json")
                            if includes_final and trace.final_message is not None else None,
        "delivered": includes_final,
    }
    switch_turn = task_switch_turn(trace)
    if after_turn < switch_turn <= through_turn and trace.first_goal_operation is not None:
        source["goal_after_task_selection"] = trace.first_goal_operation.verification_text()
    return source


def snapshot_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _snapshot_field_start(mapping: dict, field: str) -> int:
    preceding = {key: value for key, value in mapping.items() if key < field}
    # Replace the closing brace with a comma and space before the next key.
    key_start = len(snapshot_json(preceding)) + 1 if preceding else 1
    return key_start + len(snapshot_json(field)) + len(": ")


def snapshot_result_positions(
    content: str, exported: list[dict],
) -> dict[tuple[str, int, int], TextPosition]:
    """Find receipt starts by their structural path in the immutable JSON export."""
    if snapshot_json(exported) != content:
        return {}
    lines = TextCoordinates(content).lines
    positions = {}
    run_start = 1
    for run in exported:
        decision_start = run_start + _snapshot_field_start(run, "decisions") + 1
        for decision in run["decisions"]:
            result_start = decision_start + _snapshot_field_start(decision, "results_and_feedback") + 1
            for index, result in enumerate(decision["results_and_feedback"]):
                if result["kind"] == "tool_result" and result["status"] == "succeeded":
                    line = lines[bisect_right(lines, result_start, key=lambda line: line.start_offset) - 1]
                    positions[run["run_ref"], decision["decision_turn"], index] = TextPosition(
                        line=line.line, column=result_start - line.start_offset + 1)
                result_start += len(snapshot_json(result)) + len(", ")
            decision_start += len(snapshot_json(decision)) + len(", ")
        run_start += len(snapshot_json(run)) + len(", ")
    return positions


def bind_coverage(trace: InteractionTrace, through_turn: int, includes_final: bool) -> HistoryRunCoverage:
    return HistoryRunCoverage(run_ref=trace.interaction_run_ref, through_turn=through_turn,
        includes_final=includes_final, source_digest=history_digest(run_source(trace, through_turn, includes_final)))


def select_coverage(
    sources: Sequence[InteractionTrace], previous: HistoryCompactionCheckpoint | None,
) -> tuple[HistoryRunCoverage, ...]:
    """Keep the active tail and pending operations; completed runs are compactable."""
    old = {item.run_ref: item for item in previous.sources} if previous else {}
    selected = []
    for source in sources:
        records = main_decisions(source)
        if not records:
            continue
        if source.final_message is not None:
            end = records[-1].turn_index
        else:
            costs = [len(json.dumps(decision_source(source, record), ensure_ascii=True))
                     for record in records]
            tail_budget, kept, boundary = sum(costs) * 0.16, 0, len(records)
            while boundary and (kept < tail_budget or len(records) - boundary < 2):
                boundary -= 1
                kept += costs[boundary]
            pending = {item.action_id for item in source.accepted_tool_requests
                       if ((isinstance(item, AcceptedArtifactToolRequest)
                            and item.receipt is None and item.failure is None)
                           or (isinstance(item, AcceptedPythonToolRequest) and item.receipt is None))}
            pending.update(item.action_id for item in source.experiment_records
                           if item.receipt is None or item.receipt.status == "unknown")
            for index, record in enumerate(records):
                if pending.intersection(record.assistant.call_ids):
                    boundary = min(boundary, index)
            end = records[boundary - 1].turn_index if boundary else 0
        prior = old.get(source.interaction_run_ref)
        if not end or (prior is not None and end < prior.through_turn):
            if prior is not None:
                selected.append(prior)
            continue
        selected.append(bind_coverage(source, end, source.final_message is not None))
    return tuple(selected)


def covered_observation_key(item) -> tuple:
    """Distinguish results when a provider repeats a call ID or an entire call."""
    return (item.kind, item.action_id, getattr(item, "execution_request_digest", None),
            getattr(item, "decision_turn", None), input_resource_refs((item,)))

def _assistant_history(assistant: ModelAssistantMessage, *, prompts: PromptCatalog) -> tuple[str, ...]:
    parts = []
    if text := assistant.visible_text:
        parts.append(prompts.render("conversation.context.history_assistant", text=text))
    for call in assistant.payload.get("tool_calls") or ():
        function = call.get("function")
        if isinstance(function, dict):
            parts.append(prompts.render("conversation.context.history_call", call_id=call["id"],
                tool_name=function.get("name", ""), arguments=function.get("arguments", "")))
    return tuple(parts)


def _summarizer_observation(item: InteractionInput, *, prompts: PromptCatalog) -> str:
    projected, = materialize_interaction_inputs((item,), actions=(), prompts=prompts)
    if isinstance(projected, ActionObservation):
        retrieval = projected.payload.get("retrieval")
        if isinstance(retrieval, dict):
            projected = projected.model_copy(update={"payload": {
                **projected.payload, "retrieval": {key: value for key, value in retrieval.items() if key != "read_more"},
            }})
    return render_citable_input(CitableInput(observation=projected), prompts=prompts)


def _summarizer_decision(trace: InteractionTrace, record: ModelDecisionRecord, *, prompts: PromptCatalog) -> str:
    parts = [prompts.render("conversation.context.history_decision", turn=record.turn_index)]
    rejected = goal_pending_rejection(trace, record)
    if rejected is not None:
        parts.append(_summarizer_observation(rejected, prompts=prompts))
        return "\n\n".join(parts)
    for exchange in record.protocol_exchanges:
        parts.extend(_assistant_history(exchange.assistant, prompts=prompts))
        parts.extend(prompts.render("conversation.context.history_protocol_result",
            call_id=result.call_id, text=result.content) for result in exchange.results)
        parts.extend(exchange.runtime_feedback)
    assert record.assistant is not None
    parts.extend(_assistant_history(record.assistant, prompts=prompts))
    parts.extend(_summarizer_observation(trace.inputs[index], prompts=prompts)
                 for index in decision_input_indices(trace, record))
    goal_ops = {op.call_id: op for op in trace.goal_operations if op.decision_turn == record.turn_index}
    for disposition in record.dispositions:
        text = (goal_tool_result(goal_ops[disposition.call_id], prompts=prompts)
                if disposition.call_id in goal_ops else render_control_disposition(disposition, prompts=prompts))
        parts.append(prompts.render("conversation.context.history_protocol_result", call_id=disposition.call_id, text=text))
    return "\n\n".join(parts)


def render_history_run(
    trace: InteractionTrace, coverage: HistoryRunCoverage, *, after_turn: int, prompts: PromptCatalog,
) -> str:
    """Build only the model view. Snapshot export keeps the original typed data."""
    parts = [prompts.render("conversation.context.history_run", run_ref=coverage.run_ref,
                           question=trace.messages[-1].content)]
    switch_turn = task_switch_turn(trace)
    if after_turn < switch_turn <= coverage.through_turn and trace.first_goal_operation is not None:
        parts.append(goal_tool_result(trace.first_goal_operation, prompts=prompts))
    parts.extend(_summarizer_decision(trace, record, prompts=prompts) for record in main_decisions(trace)
                 if after_turn < record.turn_index <= coverage.through_turn)
    final = trace.final_message
    if coverage.includes_final and final is not None:
        parts.append(prompts.render("conversation.context.history_final", disposition=final.disposition, text=final.message))
    else:
        parts.append(prompts.get("conversation.context.history.partial").template)
    return "\n\n".join(parts)

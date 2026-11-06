"""Select and bind complete, run-scoped history prefixes for summarization."""
from collections.abc import Sequence
from hashlib import sha256
import json

from .history_models import HistoryCompactionCheckpoint, HistoryRunCoverage
from .model_history import decision_input_indices, goal_pending_rejection
from .models import AcceptedArtifactToolRequest, AcceptedPythonToolRequest, InteractionTrace, ModelDecisionRecord


def history_digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def main_decisions(trace: InteractionTrace) -> tuple[ModelDecisionRecord, ...]:
    return tuple(record for record in trace.model_decisions
                 if record.turn_index is not None and record.assistant is not None and record.consumed)


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
        "dispositions": [item.model_dump(mode="json") for item in record.dispositions],
        "goal_operations": [item.model_dump(mode="json") for item in trace.goal_operations
                            if item.decision_turn == record.turn_index],
    }


def run_source(trace: InteractionTrace, through_turn: int, includes_final: bool,
               *, after_turn: int = 0) -> dict:
    return {
        "run_ref": trace.interaction_run_ref,
        "user_request": trace.messages[-1].model_dump(mode="json"),
        "decisions": [decision_source(trace, record) for record in main_decisions(trace)
                      if after_turn < record.turn_index <= through_turn],
        "delivered_result": trace.final_message.model_dump(mode="json")
                            if includes_final and trace.final_message is not None else None,
        "delivered": includes_final,
    }


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
    """Execution digests distinguish results even when providers reuse call IDs."""
    return (item.kind, item.action_id, getattr(item, "execution_request_digest", None),
            getattr(item, "decision_turn", None))

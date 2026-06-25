"""Adapters and sequential runner for real multi-turn conversations."""

from __future__ import annotations

from typing import Callable

from personal_agent.kernel.models import EntryInput

from .dataset import (
    ConversationEvalCase,
    ConversationRunOutput,
    ConversationTurnOutput,
)
from .metrics import TERMINAL_EVENTS


def _event_type(event) -> str:
    if isinstance(event, dict):
        return str(event.get("type", ""))
    return str(getattr(event, "type", "") or "")


def _checkpoint_contents(service, thread_id: str) -> list[str]:
    if not thread_id:
        return []
    try:
        runtime = getattr(service, "runtime", service)
        graph = runtime._entry._get_orch_graph()
        values = graph.get_state({"configurable": {"thread_id": thread_id}}).values
        return [str(getattr(message, "content", "") or "") for message in values.get("messages", [])]
    except Exception:
        return []


def _retained_refs(contents: list[str], prior_inputs: list[str]) -> list[int]:
    return [
        index
        for index, text in enumerate(prior_inputs)
        if text and any(text in content for content in contents)
    ]


def project_turn(
    result,
    *,
    kind: str,
    resumed_from_run_id: str = "",
    retained_context_refs: list[int] | None = None,
) -> ConversationTurnOutput:
    events = [_event_type(event) for event in list(getattr(result, "events", []) or [])]
    status = str(getattr(result, "run_status", "") or "")
    return ConversationTurnOutput(
        kind=kind,
        outcome="clarify" if status == "waiting_confirmation" else "ready",
        intents=list(getattr(result, "intents", []) or []),
        event_types=events,
        reply_text=str(getattr(result, "reply_text", "") or ""),
        run_id=str(getattr(result, "run_id", "") or ""),
        thread_id=str(getattr(result, "thread_id", "") or ""),
        resumed_from_run_id=resumed_from_run_id,
        retained_context_refs=list(retained_context_refs or []),
        reached_terminal=any(event in TERMINAL_EVENTS for event in events),
    )


def execute_conversation(
    service,
    case: ConversationEvalCase,
    *,
    user_id: str,
    session_id: str,
    note_counter: Callable[[str], int] | None = None,
) -> ConversationRunOutput:
    """Execute every turn in order in one session, including true HITL resume."""
    count_notes = note_counter or (
        lambda uid: len(getattr(service, "runtime", service).store.list_notes(uid))
    )
    output = ConversationRunOutput(initial_note_count=count_notes(user_id))
    prior_inputs: list[str] = []
    pending_result = None

    for turn in case.turns:
        if turn.kind == "resume":
            if pending_result is None:
                raise RuntimeError(f"{case.id}: resume turn has no pending interrupted run")
            source_run_id = str(pending_result.run_id or "")
            result = service.resume_entry(
                run_id=source_run_id,
                thread_id=str(pending_result.thread_id or ""),
                decision=turn.decision,
                user_id=user_id,
                text=turn.user_input,
                option_id=turn.option_id or None,
            )
            kind = "resume"
        else:
            source_run_id = ""
            result = service.execute_entry(
                EntryInput(
                    text=turn.user_input,
                    user_id=user_id,
                    session_id=session_id,
                )
            )
            kind = "entry"

        contents = _checkpoint_contents(service, str(result.thread_id or ""))
        projection = project_turn(
            result,
            kind=kind,
            resumed_from_run_id=source_run_id,
            retained_context_refs=_retained_refs(contents, prior_inputs),
        )
        output.turns.append(projection)
        prior_inputs.append(turn.user_input)
        pending_result = result if projection.outcome == "clarify" else None

    output.final_note_count = count_notes(user_id)
    return output

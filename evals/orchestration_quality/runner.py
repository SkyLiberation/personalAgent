"""Adapter from a live EntryResult to the scoreable OrchestrationRunOutput."""

from __future__ import annotations

from .dataset import OrchestrationRunOutput
from .metrics import TERMINAL_EVENTS


def _event_type(event) -> str:
    if isinstance(event, dict):
        return str(event.get("type", ""))
    return str(getattr(event, "type", "") or "")


def run_output_from_entry_result(result) -> OrchestrationRunOutput:
    """Project an ``EntryResult`` into an OrchestrationRunOutput.

    ``primary_result_contract`` is ``result_contracts[-1]``. ``outcome`` is
    ``clarify`` when the run paused for a clarification interrupt, else
    ``ready``.
    """
    result_contracts = list(getattr(result, "result_contracts", []) or [])
    status = getattr(result, "run_status", None)
    events = list(getattr(result, "events", []) or [])
    event_types = [_event_type(e) for e in events]
    paused = status == "waiting" or "clarification_required" in event_types
    return OrchestrationRunOutput(
        outcome="clarify" if paused else "ready",
        primary_result_contract=result_contracts[-1] if result_contracts else "",
        event_types=event_types,
        paused_for_clarification=paused,
        reached_terminal=any(e in TERMINAL_EVENTS for e in event_types),
    )

"""Adapter from a live router decision to the scoreable RouterRunOutput.

The scorer only knows :class:`RouterRunOutput`. This bridges the router's
domain :class:`RouterDecision` (or the transport :class:`RouterOutput`) to that
projection, so the gate can drive either the deterministic stub router or a real
``DefaultIntentRouter`` and score the result the same way.
"""

from __future__ import annotations

from .dataset import RouterRunOutput


def run_output_from_decision(decision) -> RouterRunOutput:
    """Project a domain ``RouterDecision`` into a RouterRunOutput."""
    intents = [g.intent for g in getattr(decision, "goals", []) or []]
    clarify = bool(getattr(decision, "requires_clarification", False))
    return RouterRunOutput(
        outcome="clarify" if clarify else "ready",
        intents=intents,
        raised_clarification=clarify,
        missing_information=list(getattr(decision, "missing_information", []) or []),
    )


def run_output_from_router_output(output) -> RouterRunOutput:
    """Project the transport ``RouterOutput`` (what the stub LLM emits) into a
    RouterRunOutput, without going through domain conversion."""
    clarify = getattr(output, "outcome", "ready") == "clarify"
    intents = [g.intent for g in getattr(output, "goals", []) or []]
    clarification = getattr(output, "clarification", None)
    missing = list(getattr(clarification, "missing_information", []) or []) if clarification else []
    return RouterRunOutput(
        outcome="clarify" if clarify else "ready",
        intents=intents,
        raised_clarification=clarify,
        missing_information=missing,
    )

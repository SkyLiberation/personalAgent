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
    route_type = str(getattr(decision, "route_type", ""))
    outcome = "clarify" if clarify else route_type if route_type in {"unsupported", "rejected"} else "ready"
    return RouterRunOutput(
        outcome=outcome,
        intents=intents,
        route_type=route_type,
        coverage=str(getattr(decision, "coverage", "")),
        matched_capabilities=[
            str(value) for value in getattr(decision, "matched_capabilities", []) or []
        ],
        missing_requirements=[
            str(value) for value in getattr(decision, "missing_requirements", []) or []
        ],
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
        outcome=str(getattr(output, "outcome", "clarify" if clarify else "ready")),
        intents=intents,
        route_type=str(getattr(output, "route_type", "")),
        coverage=str(getattr(output, "coverage", "")),
        matched_capabilities=[
            str(value) for value in getattr(output, "matched_capabilities", []) or []
        ],
        missing_requirements=[
            str(value) for value in getattr(output, "missing_requirements", []) or []
        ],
        raised_clarification=clarify,
        missing_information=missing,
    )

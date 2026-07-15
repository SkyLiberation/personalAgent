"""Orchestration-specific metric primitives.

Cross-harness primitives are re-exported from :mod:`evals._metrics_core`:
  - ``outcome_correct``  -> ``exact_match`` (ready/clarify decision)
  - ``event_subsequence_match`` -> ``ordered_subsequence`` (event milestones)
  - ``reached_terminal`` / ``TERMINAL_EVENTS`` (run must not hang)

Unique to orchestration are the primary-result-contract match and the negative
``forbidden_events`` invariant: a clarify run must never compile a goal graph.
"""

from __future__ import annotations

from .._metrics_core import TERMINAL_EVENTS  # noqa: F401 — re-exported for runner
from .._metrics_core import exact_match as outcome_correct
from .._metrics_core import ordered_subsequence as event_subsequence_match
from .._metrics_core import reached_terminal

__all__ = [
    "TERMINAL_EVENTS",
    "outcome_correct",
    "event_subsequence_match",
    "reached_terminal",
    "primary_result_contract_correct",
    "forbidden_events_absent",
]


def primary_result_contract_correct(predicted: str, gold: str) -> float:
    """Score the terminal goal's result contract; clarify has no contract."""
    if not gold:
        return 1.0
    return 1.0 if predicted == gold else 0.0


def forbidden_events_absent(event_types: list[str], forbidden: list[str]) -> float:
    """1.0 when none of the forbidden event types appear. 1.0 when none listed."""
    if not forbidden:
        return 1.0
    seen = set(event_types)
    return 1.0 if not (seen & set(forbidden)) else 0.0

"""TaskAnalyzer-specific metric primitives.

The ready/clarify decision (``outcome_correct``) is the cross-harness
``exact_match`` re-exported from :mod:`evals._metrics_core`. Unique to task understanding
are result-contract set-F1, ordered exact-match over the goal sequence, and clarify
field precision. All functions are pure and deterministic.
"""

from __future__ import annotations

from .._metrics_core import exact_match as outcome_correct

__all__ = [
    "outcome_correct",
    "result_contract_set_f1",
    "result_contract_sequence_exact",
    "clarify_field_precision",
]


def result_contract_set_f1(predicted: list[str], gold: list[str]) -> float:
    """F1 over the semantic result-contract set (order-insensitive).

    Returns 1.0 when both are empty (a clarify case asserts no result_contracts).
    Duplicate result contracts are collapsed because goals are distinct outcomes.
    """
    p, g = set(predicted), set(gold)
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    tp = len(p & g)
    if tp == 0:
        return 0.0
    precision = tp / len(p)
    recall = tp / len(g)
    return round(2 * precision * recall / (precision + recall), 4)


def result_contract_sequence_exact(predicted: list[str], gold: list[str]) -> float:
    """1.0 when the ordered result-contract sequence matches exactly.

    Order matters because goals render as
    ``a → b``, so a swapped sequence is a real task-understanding difference. Returns 1.0
    when both are empty.
    """
    return 1.0 if list(predicted) == list(gold) else 0.0


def clarify_field_precision(predicted: list[str], expected: list[str]) -> float:
    """Fraction of expected missing-info substrings that the analyzer's
    clarification actually surfaced (substring match, order-insensitive).

    Returns 1.0 when nothing was expected (case opts out of field assertion).
    """
    if not expected:
        return 1.0
    blob = " ".join(predicted)
    hits = sum(1 for needle in expected if needle in blob)
    return round(hits / len(expected), 4)

"""Metric primitives for the router-quality harness.

Three families, mirroring the RAG harness's pure/LLM-free style:
  - outcome:  ready/clarify decision accuracy
  - intent:   set-F1 + ordered exact-match over the goal sequence
  - clarify:  precision that the right fields were flagged as missing

All functions are pure and deterministic.
"""

from __future__ import annotations


def outcome_correct(predicted: str, gold: str) -> float:
    """1.0 when the ready/clarify decision matches, else 0.0."""
    return 1.0 if predicted == gold else 0.0


def intent_set_f1(predicted: list[str], gold: list[str]) -> float:
    """F1 over the intent *set* (order-insensitive).

    Returns 1.0 when both are empty (a clarify case asserts no intents).
    Duplicate intents are collapsed — the router decomposes distinct goals.
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


def intent_sequence_exact(predicted: list[str], gold: list[str]) -> float:
    """1.0 when the ordered intent sequence matches exactly.

    Order matters: ``primary_intent`` is ``goals[-1]`` and goals render as
    ``a → b``, so a swapped sequence is a real routing difference. Returns 1.0
    when both are empty.
    """
    return 1.0 if list(predicted) == list(gold) else 0.0


def clarify_field_precision(predicted: list[str], expected: list[str]) -> float:
    """Fraction of the expected missing-info substrings that the router's
    clarification actually surfaced (substring match, order-insensitive).

    Returns 1.0 when nothing was expected (case opts out of field assertion).
    """
    if not expected:
        return 1.0
    blob = " ".join(predicted)
    hits = sum(1 for needle in expected if needle in blob)
    return round(hits / len(expected), 4)

"""Conversation-specific metric primitives.

Cross-harness primitives (``exact_match`` for per-turn outcome/intent,
``ordered_subsequence`` for per-turn event milestones, ``TERMINAL_EVENTS``)
are re-exported from :mod:`evals._metrics_core`. Everything below is unique to
multi-turn evaluation: history retention, grounding, thread continuity, HITL
resume and side-effect deltas.
"""

from __future__ import annotations

from .._metrics_core import TERMINAL_EVENTS, exact_match, ordered_subsequence

__all__ = [
    "TERMINAL_EVENTS",
    "exact_match",
    "ordered_subsequence",
    "reference_recall",
    "response_contains",
    "thread_continuity",
    "resume_success",
    "side_effect_accuracy",
]


def reference_recall(observed: list[int], expected: list[int]) -> float:
    """Recall of annotated prior turns retained in the thread checkpoint."""
    if not expected:
        return 1.0
    seen = set(observed)
    return round(sum(ref in seen for ref in expected) / len(expected), 4)


def response_contains(reply: str, expected_terms: list[str]) -> float:
    if not expected_terms:
        return 1.0
    normalized = reply.casefold()
    return round(
        sum(term.casefold() in normalized for term in expected_terms) / len(expected_terms),
        4,
    )


def thread_continuity(thread_ids: list[str], required: bool) -> float:
    if not required:
        return 1.0
    nonempty = [value for value in thread_ids if value]
    return 1.0 if len(nonempty) == len(thread_ids) and len(set(nonempty)) <= 1 else 0.0


def resume_success(
    kind: str,
    run_id: str,
    resumed_from_run_id: str,
    outcome: str,
    reached_terminal: bool,
) -> float:
    if kind != "resume":
        return 1.0
    return 1.0 if (
        run_id
        and run_id == resumed_from_run_id
        and outcome != "clarify"
        and reached_terminal
    ) else 0.0


def side_effect_accuracy(actual_delta: int, expected_delta: int | None) -> float:
    if expected_delta is None:
        return 1.0
    return 1.0 if actual_delta == expected_delta else 0.0

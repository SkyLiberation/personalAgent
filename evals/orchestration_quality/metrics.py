"""Metric primitives for the orchestration-quality harness.

Pure, deterministic, LLM-free — mirrors the rag/router harnesses.
  - outcome:  ready/clarify decision accuracy
  - intent:   primary-intent match
  - sequence: ordered-subsequence containment of expected event milestones
  - safety:   forbidden events stayed absent
"""

from __future__ import annotations


def outcome_correct(predicted: str, gold: str) -> float:
    return 1.0 if predicted == gold else 0.0


def primary_intent_correct(predicted: str, gold: str) -> float:
    """1.0 when the primary intent matches. Returns 1.0 when no gold intent is
    annotated (clarify cases route to no goal)."""
    if not gold:
        return 1.0
    return 1.0 if predicted == gold else 0.0


def event_subsequence_match(event_types: list[str], expected: list[str]) -> float:
    """1.0 when every expected event appears in ``event_types`` IN ORDER (not
    necessarily contiguous). Returns 1.0 when nothing is expected.

    This is ordered-subsequence containment: it pins milestone ordering while
    tolerating extra events between milestones and an environment-dependent tail.
    """
    if not expected:
        return 1.0
    it = iter(event_types)
    return 1.0 if all(any(e == want for e in it) for want in expected) else 0.0


def forbidden_events_absent(event_types: list[str], forbidden: list[str]) -> float:
    """1.0 when none of the forbidden event types appear. 1.0 when none listed."""
    if not forbidden:
        return 1.0
    seen = set(event_types)
    return 1.0 if not (seen & set(forbidden)) else 0.0


# Terminal events: a run that proceeds past planning MUST end on one of these.
# A run that hangs (e.g. blocked in synchronous Graphiti ingest) emits neither
# and leaves the SSE stream open forever — the production "卡住" failure.
TERMINAL_EVENTS = ("run_completed", "run_failed")


def reached_terminal(event_types: list[str], require: bool) -> float:
    """1.0 when the run ended on a terminal event (run_completed / run_failed).

    ``require=False`` opts a case out (e.g. a clarify run pauses mid-flight and
    is *expected* not to terminate), scoring 1.0. When ``require=True``, a run
    that emitted neither terminal event scores 0.0 — it hung or was cut off.
    """
    if not require:
        return 1.0
    return 1.0 if any(e in TERMINAL_EVENTS for e in event_types) else 0.0

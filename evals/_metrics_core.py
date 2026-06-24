"""Harness-agnostic metric primitives shared across the golden sets.

These three primitives are the *only* genuinely cross-harness scoring logic:
exact equality, ordered-subsequence containment, and terminal-event detection.
They were independently duplicated in the router / orchestration / conversation
harnesses (``outcome_correct`` == ``exact_match``; ``event_subsequence_match``
== ``ordered_subsequence``; ``reached_terminal`` / ``TERMINAL_EVENTS``).

Each capability harness re-exports what it needs from here under its own
conventional name, so scorers, runners and tests keep a stable ``.metrics``
import surface while the logic lives in one place. Harness-specific metrics
(RAG IR scores, router intent F1, conversation thread/resume/side-effect, …)
stay in their own ``metrics.py`` — this module deliberately holds nothing that
belongs to a single harness.
"""

from __future__ import annotations

# Terminal events: a run that proceeds past planning MUST end on one of these.
# A run that hangs (e.g. blocked in synchronous Graphiti ingest) emits neither
# and leaves the SSE stream open forever — the production "卡住" failure mode.
TERMINAL_EVENTS = ("run_completed", "run_failed")


def exact_match(predicted: object, expected: object) -> float:
    """1.0 when the two values are equal, else 0.0.

    Used for scalar decisions (ready/clarify outcome, primary intent) and for
    list equality (a turn's ordered intent list). Equality semantics are
    delegated to ``==`` so both work without special-casing.
    """
    return 1.0 if predicted == expected else 0.0


def ordered_subsequence(actual: list[str], expected: list[str]) -> float:
    """1.0 when every ``expected`` item appears in ``actual`` IN ORDER.

    Ordered-subsequence containment: the expected milestones must appear in the
    given order but need not be contiguous, so it pins milestone ordering while
    tolerating extra events between milestones and an environment-dependent
    tail. Returns 1.0 when nothing is expected.
    """
    if not expected:
        return 1.0
    iterator = iter(actual)
    return 1.0 if all(any(item == wanted for item in iterator) for wanted in expected) else 0.0


def reached_terminal(event_types: list[str], require: bool) -> float:
    """1.0 when the run ended on a terminal event (run_completed / run_failed).

    ``require=False`` opts a case out (e.g. a clarify run pauses mid-flight and
    is *expected* not to terminate), scoring 1.0. When ``require=True``, a run
    that emitted neither terminal event scores 0.0 — it hung or was cut off.
    """
    if not require:
        return 1.0
    return 1.0 if any(event in TERMINAL_EVENTS for event in event_types) else 0.0

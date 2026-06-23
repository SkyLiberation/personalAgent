"""Unit tests for orchestration-quality metric primitives — pure, no DB/LLM."""

from __future__ import annotations

from .metrics import (
    event_subsequence_match,
    forbidden_events_absent,
    outcome_correct,
    primary_intent_correct,
    reached_terminal,
)


class TestOutcomeCorrect:
    def test_match(self):
        assert outcome_correct("ready", "ready") == 1.0

    def test_mismatch(self):
        assert outcome_correct("ready", "clarify") == 0.0


class TestPrimaryIntentCorrect:
    def test_match(self):
        assert primary_intent_correct("ask", "ask") == 1.0

    def test_mismatch(self):
        assert primary_intent_correct("ask", "summarize_thread") == 0.0

    def test_no_gold_is_perfect(self):
        assert primary_intent_correct("", "") == 1.0


class TestEventSubsequenceMatch:
    def test_contiguous(self):
        assert event_subsequence_match(["a", "b", "c"], ["a", "b"]) == 1.0

    def test_non_contiguous_in_order(self):
        assert event_subsequence_match(["a", "x", "b", "y", "c"], ["a", "b", "c"]) == 1.0

    def test_out_of_order_fails(self):
        assert event_subsequence_match(["b", "a"], ["a", "b"]) == 0.0

    def test_missing_milestone_fails(self):
        assert event_subsequence_match(["a", "c"], ["a", "b", "c"]) == 0.0

    def test_empty_expected_is_perfect(self):
        assert event_subsequence_match(["a"], []) == 1.0


class TestForbiddenEventsAbsent:
    def test_absent(self):
        assert forbidden_events_absent(["a", "b"], ["x"]) == 1.0

    def test_present_fails(self):
        assert forbidden_events_absent(["a", "steps_projected"], ["steps_projected"]) == 0.0

    def test_none_forbidden_is_perfect(self):
        assert forbidden_events_absent(["a"], []) == 1.0


class TestReachedTerminal:
    def test_run_completed_counts(self):
        assert reached_terminal(["entry_started", "run_completed"], require=True) == 1.0

    def test_run_failed_counts(self):
        assert reached_terminal(["entry_started", "run_failed"], require=True) == 1.0

    def test_no_terminal_event_hangs(self):
        # The production "卡住" shape: proceeded to capture, then no terminal.
        assert reached_terminal(
            ["entry_started", "intent_classified", "steps_projected", "step_started"],
            require=True,
        ) == 0.0

    def test_not_required_opts_out(self):
        # Clarify runs pause mid-flight by design — not required to terminate.
        assert reached_terminal(["entry_started", "clarification_required"], require=False) == 1.0

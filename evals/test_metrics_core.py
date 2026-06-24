"""Unit tests for the shared, harness-agnostic metric core — pure, no DB/LLM."""

from __future__ import annotations

from evals._metrics_core import (
    TERMINAL_EVENTS,
    exact_match,
    ordered_subsequence,
    reached_terminal,
)


class TestExactMatch:
    def test_scalar_match(self):
        assert exact_match("ready", "ready") == 1.0

    def test_scalar_mismatch(self):
        assert exact_match("ready", "clarify") == 0.0

    def test_list_equality(self):
        assert exact_match(["ask", "solidify"], ["ask", "solidify"]) == 1.0
        assert exact_match(["ask", "solidify"], ["solidify", "ask"]) == 0.0


class TestOrderedSubsequence:
    def test_allows_intermediate_items(self):
        assert ordered_subsequence(["a", "noise", "b"], ["a", "b"]) == 1.0

    def test_order_matters(self):
        assert ordered_subsequence(["b", "a"], ["a", "b"]) == 0.0

    def test_empty_expected_is_vacuously_true(self):
        assert ordered_subsequence([], []) == 1.0
        assert ordered_subsequence(["a"], []) == 1.0

    def test_missing_milestone_fails(self):
        assert ordered_subsequence(["a"], ["a", "b"]) == 0.0


class TestReachedTerminal:
    def test_opt_out_when_not_required(self):
        assert reached_terminal([], require=False) == 1.0

    def test_required_and_present(self):
        assert reached_terminal(["entry_started", "run_completed"], require=True) == 1.0
        assert reached_terminal(["run_failed"], require=True) == 1.0

    def test_required_but_hung(self):
        assert reached_terminal(["entry_started", "steps_projected"], require=True) == 0.0

    def test_terminal_events_membership(self):
        assert set(TERMINAL_EVENTS) == {"run_completed", "run_failed"}

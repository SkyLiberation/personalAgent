"""Unit tests for the router-quality metric primitives — pure math, no data."""

from __future__ import annotations

from .metrics import (
    clarify_field_precision,
    intent_sequence_exact,
    intent_set_f1,
    outcome_correct,
)


class TestOutcomeCorrect:
    def test_match(self):
        assert outcome_correct("ready", "ready") == 1.0

    def test_mismatch(self):
        assert outcome_correct("ready", "clarify") == 0.0


class TestIntentSetF1:
    def test_both_empty_is_perfect(self):
        assert intent_set_f1([], []) == 1.0

    def test_exact_set(self):
        assert intent_set_f1(["ask"], ["ask"]) == 1.0

    def test_order_insensitive(self):
        assert intent_set_f1(["a", "b"], ["b", "a"]) == 1.0

    def test_partial_overlap(self):
        # predicted {a,b}, gold {a,c}: tp=1, p=0.5, r=0.5 -> f1=0.5
        assert intent_set_f1(["a", "b"], ["a", "c"]) == 0.5

    def test_disjoint(self):
        assert intent_set_f1(["a"], ["b"]) == 0.0

    def test_one_empty(self):
        assert intent_set_f1(["a"], []) == 0.0

    def test_duplicates_collapsed(self):
        assert intent_set_f1(["a", "a"], ["a"]) == 1.0


class TestIntentSequenceExact:
    def test_same_order(self):
        assert intent_sequence_exact(["a", "b"], ["a", "b"]) == 1.0

    def test_swapped_order_fails(self):
        assert intent_sequence_exact(["a", "b"], ["b", "a"]) == 0.0

    def test_both_empty(self):
        assert intent_sequence_exact([], []) == 1.0


class TestClarifyFieldPrecision:
    def test_no_expectation_is_perfect(self):
        assert clarify_field_precision(["anything"], []) == 1.0

    def test_substring_hit(self):
        assert clarify_field_precision(["明确的目标、问题或操作对象"], ["明确的目标"]) == 1.0

    def test_partial(self):
        assert clarify_field_precision(["缺少对象"], ["对象", "时间"]) == 0.5

    def test_miss(self):
        assert clarify_field_precision(["无关内容"], ["对象"]) == 0.0

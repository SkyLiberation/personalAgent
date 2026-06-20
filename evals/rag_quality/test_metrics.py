from __future__ import annotations

from evals.rag_quality.dataset import RagEvalCase, RunOutput, load_cases
from evals.rag_quality.metrics import (
    answer_relevance,
    claim_entailment_accuracy,
    context_precision,
    contrastive_coverage,
    faithfulness,
    precision_at_k,
)
from evals.rag_quality.scorer import aggregate, score_all
from evals.rag_quality.dataset import default_cases_path


class TestPrecisionAtK:
    def test_all_relevant(self):
        assert precision_at_k(["a", "b"], {"a", "b"}, 2) == 1.0

    def test_partial(self):
        assert precision_at_k(["a", "x", "b"], {"a", "b"}, 3) == 2 / 3

    def test_empty_topk_is_zero(self):
        assert precision_at_k([], {"a"}, 5) == 0.0

    def test_context_precision_uses_pack_size(self):
        assert context_precision(["a", "b", "c"], {"a"}) == 1 / 3


class TestGenerationMetrics:
    def test_answer_relevance_matches_reference(self):
        score = answer_relevance("Redis 缓存降低数据库负载", "Redis 有什么用", "Redis 缓存降低数据库负载")
        assert score > 0.5

    def test_answer_relevance_empty_is_zero(self):
        assert answer_relevance("", "任意问题") == 0.0

    def test_faithfulness_full_when_grounded(self):
        assert faithfulness("Redis 缓存", ["Redis 缓存降低负载"]) > 0.5

    def test_faithfulness_zero_without_evidence(self):
        assert faithfulness("有内容的答案", []) == 0.0

    def test_faithfulness_empty_answer_is_one(self):
        assert faithfulness("", ["任意证据"]) == 1.0


class TestGroundingMetrics:
    def test_perfect_claim_accuracy(self):
        assert claim_entailment_accuracy(["supported", "contradicted"],
                                         ["supported", "contradicted"]) == 1.0

    def test_length_mismatch_degrades_not_zero(self):
        # one correct claim vs two gold -> 1/2, not 0
        assert claim_entailment_accuracy(["supported"], ["supported", "supported"]) == 0.5

    def test_no_gold_is_one(self):
        assert claim_entailment_accuracy([], []) == 1.0

    def test_contrastive_coverage_full_when_none_needed(self):
        assert contrastive_coverage(0, 0) == 1.0

    def test_contrastive_coverage_partial(self):
        assert contrastive_coverage(2, 1) == 0.5

    def test_contrastive_coverage_capped_at_one(self):
        assert contrastive_coverage(1, 5) == 1.0


class TestDatasetAndAggregate:
    def test_bundled_cases_load(self):
        cases = load_cases(default_cases_path())
        assert len(cases) >= 5
        assert all(isinstance(c, RagEvalCase) for c in cases)
        assert len({c.id for c in cases}) == len(cases)

    def test_loader_ignores_unknown_keys(self):
        import tempfile
        from pathlib import Path as _P

        d = tempfile.mkdtemp()
        try:
            f = _P(d) / "c.json"
            f.write_text('[{"id": "x", "question": "q", "extra_note": "ignored"}]', encoding="utf-8")
            cases = load_cases(f)
            assert cases[0].id == "x"
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_aggregate_is_zeroed(self):
        report = aggregate([])
        assert report.num_cases == 0
        assert report.means["recall_5"] == 0.0

    def test_score_all_skips_missing_runs(self):
        cases = [RagEvalCase(id="a", question="q", gold_evidence_ids=["n1"])]
        runs = {"a": RunOutput(ranked_evidence_ids=["n1"], selected_evidence_ids=["n1"])}
        report = score_all(cases, runs)
        assert report.num_cases == 1
        assert report.means["recall_5"] == 1.0

    def test_threshold_failures_reported(self):
        cases = [RagEvalCase(id="a", question="q", gold_evidence_ids=["n1"])]
        runs = {"a": RunOutput(ranked_evidence_ids=["wrong"])}
        report = score_all(cases, runs)
        failures = report.check_thresholds({"recall_5": 0.5})
        assert failures and "recall_5" in failures[0]

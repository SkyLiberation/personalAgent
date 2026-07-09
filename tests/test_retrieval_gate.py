from __future__ import annotations

from evals.retrieval_gate import (
    RetrievalGateInput,
    RetrievalGateThresholds,
    build_gate_input_from_eval_results,
    evaluate_retrieval_gate,
    gate_payload,
)


def _metrics(value: float) -> dict[str, float]:
    return {"mrr": value, "recall_10": value, "ndcg_10": value}


def test_retrieval_gate_passes_when_all_profiles_clear_baseline_and_budgets():
    decision = evaluate_retrieval_gate(
        RetrievalGateInput(
            strategy_name="hybrid",
            metrics_by_profile={
                "open": _metrics(0.8),
                "galileo": _metrics(0.7),
                "business": _metrics(0.9),
            },
            baseline_by_profile={
                "open": _metrics(0.79),
                "galileo": _metrics(0.69),
                "business": _metrics(0.88),
            },
            latency_ms=1200,
            cost_usd=0.01,
            grounding_score=0.92,
            harmed_fraction=0.01,
        ),
        RetrievalGateThresholds(
            max_latency_ms=1500,
            max_cost_usd=0.02,
            min_grounding_score=0.9,
            max_harmed_fraction=0.02,
        ),
    )

    assert decision.passed is True
    assert decision.checked_profiles == ("open", "galileo", "business")
    assert gate_payload(decision)["passed"] is True


def test_retrieval_gate_fails_on_quality_and_resource_regressions():
    decision = evaluate_retrieval_gate(
        RetrievalGateInput(
            strategy_name="hybrid",
            metrics_by_profile={
                "open": _metrics(0.8),
                "galileo": {"mrr": 0.7, "recall_10": 0.61, "ndcg_10": 0.7},
                "business": _metrics(0.9),
            },
            baseline_by_profile={
                "open": _metrics(0.8),
                "galileo": _metrics(0.7),
                "business": _metrics(0.9),
            },
            latency_ms=2000,
            cost_usd=0.03,
            grounding_score=0.82,
            harmed_fraction=0.04,
        ),
        RetrievalGateThresholds(
            max_latency_ms=1500,
            max_cost_usd=0.02,
            min_grounding_score=0.9,
            max_harmed_fraction=0.02,
        ),
    )

    assert decision.passed is False
    assert any("galileo.recall_10 regressed" in item for item in decision.failures)
    assert any("latency_ms over budget" in item for item in decision.failures)
    assert any("cost_usd over budget" in item for item in decision.failures)
    assert any("grounding_score below floor" in item for item in decision.failures)
    assert any("harmed_fraction over budget" in item for item in decision.failures)


def test_build_gate_input_from_eval_results_uses_utilized_lower_bound():
    current_galileo = [{
        "strategy": "hybrid",
        "metrics": {"mrr": 0.9, "recall_10": 0.95, "ndcg_10": 0.92},
        "utilized_metrics": {"mrr": 0.7, "recall_10": 0.8, "ndcg_10": 0.75},
    }]
    baseline_galileo = [{
        "strategy": "hybrid",
        "metrics": {"mrr": 0.6, "recall_10": 0.7, "ndcg_10": 0.65},
        "utilized_metrics": {"mrr": 0.65, "recall_10": 0.72, "ndcg_10": 0.7},
    }]

    gate_input = build_gate_input_from_eval_results(
        strategy_name="hybrid",
        current_by_profile={"galileo": current_galileo},
        baseline_by_profile={"galileo": baseline_galileo},
    )

    assert gate_input.metrics_by_profile["galileo"]["mrr"] == 0.7
    assert gate_input.metrics_by_profile["galileo"]["recall_10"] == 0.8
    assert gate_input.baseline_by_profile["galileo"]["mrr"] == 0.6


def test_build_gate_input_from_eval_results_feeds_gate_decision():
    payload = [{
        "strategy": "hybrid",
        "metrics": {"mrr": 0.8, "recall_10": 0.9, "ndcg_10": 0.85},
    }]
    gate_input = build_gate_input_from_eval_results(
        strategy_name="hybrid",
        current_by_profile={"open": payload},
        baseline_by_profile={"open": payload},
    )
    decision = evaluate_retrieval_gate(
        gate_input,
        RetrievalGateThresholds(required_profiles=("open",)),
    )

    assert decision.passed is True


def test_build_gate_input_supports_profile_strategy_aliases():
    open_payload = [{
        "strategy": "ask_retrieve_shared_evidence_selector_lexical",
        "metrics": {"mrr": 0.8, "recall_10": 0.9, "ndcg_10": 0.85},
    }]
    galileo_payload = [{
        "strategy": "galileo_shared_evidence_selector",
        "metrics": {"mrr": 0.7, "recall_10": 0.8, "ndcg_10": 0.75},
        "utilized_metrics": {"mrr": 0.69, "recall_10": 0.78, "ndcg_10": 0.74},
    }]

    gate_input = build_gate_input_from_eval_results(
        strategy_name="shared_sparse_support",
        current_by_profile={"open": open_payload, "galileo": galileo_payload},
        baseline_by_profile={"open": open_payload, "galileo": galileo_payload},
        strategy_by_profile={
            "open": "ask_retrieve_shared_evidence_selector_lexical",
            "galileo": "galileo_shared_evidence_selector",
        },
    )

    assert gate_input.strategy_name == "shared_sparse_support"
    assert gate_input.metrics_by_profile["open"]["recall_10"] == 0.9
    assert gate_input.metrics_by_profile["galileo"]["recall_10"] == 0.78


def test_build_gate_input_supports_separate_baseline_strategy_aliases():
    payload = [
        {
            "strategy": "keyword",
            "metrics": {"mrr": 0.5, "recall_10": 0.6, "ndcg_10": 0.55},
        },
        {
            "strategy": "shared",
            "metrics": {"mrr": 0.8, "recall_10": 0.9, "ndcg_10": 0.85},
        },
    ]

    gate_input = build_gate_input_from_eval_results(
        strategy_name="shared_sparse_support",
        current_by_profile={"open": payload},
        baseline_by_profile={"open": payload},
        strategy_by_profile={"open": "shared"},
        baseline_strategy_by_profile={"open": "keyword"},
    )

    assert gate_input.metrics_by_profile["open"]["mrr"] == 0.8
    assert gate_input.baseline_by_profile["open"]["mrr"] == 0.5

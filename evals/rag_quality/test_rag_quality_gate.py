"""Hermetic RAG-quality regression gate.

Scores the bundled dataset against *reference* run outputs and asserts the
aggregate means clear the frozen baseline. Fully offline: no Postgres, no LLM.
The grounding metric is exercised against the REAL verifier — each reference
run's claim verdicts come from ``EntailmentAnswerVerifier.verify``, not
hand-typed — so a regression in the verifier surfaces here too.

Run explicitly (evals/ is outside the default testpaths):
    uv run pytest evals/rag_quality/test_rag_quality_gate.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.agent.verifier import EntailmentAnswerVerifier
from personal_agent.core.evidence import EvidenceItem

from .dataset import RunOutput, default_cases_path, load_cases
from .runner import run_output_from_result
from .scorer import score_all, score_case


def _ev(source_id: str, title: str, snippet: str, retrieved_by: str = "") -> EvidenceItem:
    meta = {"retrieved_by": retrieved_by} if retrieved_by else {}
    return EvidenceItem(
        source_type="note", source_id=source_id, title=title, snippet=snippet, metadata=meta,
    )


# Reference evidence pools + answers per case — a stand-in for a healthy
# pipeline run. The verifier scores the answer against this evidence to produce
# real claim verdicts.
_REFERENCE = {
    "rq-001": {
        "evidence": [_ev("n1", "服务降级", "服务降级是在系统压力过大时主动关闭非核心功能以保障核心链路可用性的策略。")],
        "answer": "服务降级是在系统压力过大时主动关闭非核心功能以保障核心链路可用性的策略。",
    },
    "rq-002": {
        "evidence": [
            _ev("n1", "pytest入门", "pytest 是 Python 最流行的测试框架，支持 fixture 和参数化。"),
            _ev("n2", "unittest基础", "unittest 是 Python 标准库自带的测试框架。"),
            _ev("n3", "nose2简介", "nose2 是 unittest 的扩展，提供更灵活的测试发现。"),
        ],
        "answer": "Python 常见测试框架包括 pytest、unittest 和 nose2。pytest 支持 fixture 与参数化。",
    },
    "rq-003": {
        "evidence": [
            _ev("n1", "LangGraph StateGraph", "StateGraph 是 LangGraph 的核心编排抽象。"),
            _ev("n2", "LangGraph节点", "节点是 StateGraph 中的处理单元。"),
        ],
        "answer": "LangGraph 以 StateGraph 为核心编排抽象，节点是 StateGraph 中的处理单元。",
    },
    "rq-004": {
        "evidence": [
            _ev("n1", "Redis 缓存实测", "实测表明 Redis 缓存不能降低数据库负载，反而增加了运维复杂度。"),
            _ev("c1", "缓存风险", "缓存一致性与运维复杂度是引入 Redis 的主要风险。", retrieved_by="contrastive"),
        ],
        "answer": "Redis 缓存能降低数据库负载。",
    },
    "rq-005": {
        "evidence": [
            _ev("x9", "天气", "今天的天气晴朗，适合户外活动。"),
            _ev("c2", "量子计算局限", "当前量子计算尚未具备颠覆现代密码学的工程能力，存在争议。", retrieved_by="contrastive"),
        ],
        "answer": "量子计算将彻底颠覆现代密码学体系。",
    },
}


def _build_runs() -> dict[str, RunOutput]:
    """Project each reference scenario into a RunOutput, deriving claim verdicts
    from the real EntailmentAnswerVerifier."""
    verifier = EntailmentAnswerVerifier()
    runs: dict[str, RunOutput] = {}
    for case_id, ref in _REFERENCE.items():
        evidence = ref["evidence"]
        result = verifier.verify(
            question=case_id, answer=ref["answer"],
            citations=[], matches=[], evidence=evidence,
        )

        class _Result:
            pass

        proj = _Result()
        proj.answer = ref["answer"]
        proj.evidence = evidence
        runs[case_id] = run_output_from_result(proj, verification=result)
    return runs


@pytest.fixture(scope="module")
def cases():
    return load_cases(default_cases_path())


@pytest.fixture(scope="module")
def runs():
    return _build_runs()


@pytest.fixture(scope="module")
def baseline():
    path = Path(__file__).parent / "baseline.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


class TestRagQualityGate:
    def test_dataset_and_runs_align(self, cases, runs):
        case_ids = {c.id for c in cases}
        assert set(runs) == case_ids, "every case needs a reference run"

    def test_aggregate_meets_baseline(self, cases, runs, baseline):
        report = score_all(cases, runs)
        failures = report.check_thresholds(baseline)
        assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"

    def test_well_supported_cases_recall_gold(self, cases, runs):
        for case in cases:
            if case.gold_evidence_ids:
                score = score_case(case, runs[case.id])
                assert score.recall_5 > 0.0, f"{case.id} recalled no gold evidence"

    def test_contradiction_case_detected(self, cases, runs):
        # rq-004's answer disagrees with its evidence -> verifier must flag it.
        run = runs["rq-004"]
        assert "contradicted" in run.claim_verdicts

    def test_unsupported_case_not_grounded(self, cases, runs):
        # rq-005 asserts what the evidence opposes; the contrastive counter-
        # evidence flips the verdict to contradicted (not silently not_found).
        run = runs["rq-005"]
        assert all(v == "contradicted" for v in run.claim_verdicts)

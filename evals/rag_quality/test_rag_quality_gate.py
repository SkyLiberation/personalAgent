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


def _ev(entry: dict) -> EvidenceItem:
    retrieved_by = entry.get("retrieved_by", "")
    meta = {"retrieved_by": retrieved_by} if retrieved_by else {}
    return EvidenceItem(
        source_type=entry.get("source_type", "note"),
        source_id=entry["source_id"],
        title=entry.get("title", ""),
        snippet=entry.get("snippet", ""),
        metadata=meta,
    )


def default_reference_runs_path() -> Path:
    return Path(__file__).parent / "reference_runs.json"


def load_reference_runs(path: Path) -> dict[str, dict]:
    """Load the {case_id: {answer, evidence[]}} reference scenarios — a stand-in
    for healthy pipeline runs. Underscore-prefixed keys are human notes."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _build_runs() -> dict[str, RunOutput]:
    """Project each reference scenario into a RunOutput, deriving claim verdicts
    from the real EntailmentAnswerVerifier."""
    verifier = EntailmentAnswerVerifier()
    references = load_reference_runs(default_reference_runs_path())
    runs: dict[str, RunOutput] = {}
    for case_id, ref in references.items():
        evidence = [_ev(e) for e in ref["evidence"]]
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

    def test_contradiction_cases_detected(self, cases, runs):
        # Any case whose gold marks a contradicted claim must surface one.
        for case in cases:
            if "contradicted" in case.gold_claim_verdicts:
                run = runs[case.id]
                assert "contradicted" in run.claim_verdicts, (
                    f"{case.id}: expected a contradicted verdict, got {run.claim_verdicts}"
                )

    def test_contrastive_cases_have_counter_evidence(self, cases, runs):
        # Cases that need counter-evidence must actually carry some in the pool.
        for case in cases:
            if case.claims_needing_contrast > 0:
                run = runs[case.id]
                assert run.counter_evidence_found > 0, (
                    f"{case.id}: needs contrastive evidence but none found"
                )

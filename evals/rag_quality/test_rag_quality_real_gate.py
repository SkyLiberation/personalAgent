"""Real-pipeline RAG Golden Test (needs LLM + Postgres).

Seeds each case's reference evidence as real notes, runs the real ``execute_ask``
pipeline (retrieve → generate → verify) end to end, and scores the result
against ``baseline_real.json`` (looser than offline — live retrieval+generation
is non-deterministic). Skips cleanly when LLM/Postgres is unconfigured.

This is the layer that scores the real RAG pipeline, not hand-built reference
evidence. It exercises what the offline gate cannot: whether the real retriever
surfaces the right notes and the real generator stays grounded.

    uv run pytest evals/rag_quality/test_rag_quality_real_gate.py -v

The per-case recall report prints every case where the real retriever missed
its seeded gold notes, so retrieval regressions are visible even when the
aggregate clears the floor.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from .dataset import default_cases_path, load_cases
from .real_runner import ask_case, build_real_service, seed_case_notes
from .scorer import score_all, score_case

_SERVICE = build_real_service()
_SKIP_REASON = "LLM/Postgres not configured (set OPENAI_* + PERSONAL_AGENT_POSTGRES_URL to run)"


def _load_reference_runs() -> dict[str, dict]:
    path = Path(__file__).parent / "reference_runs.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@pytest.fixture(scope="module")
def cases():
    # Only cases that have gold evidence to seed are meaningful for the real
    # retrieval gate; no-answer cases (empty gold) are exercised offline.
    return [c for c in load_cases(default_cases_path()) if c.gold_evidence_ids]


@pytest.fixture(scope="module")
def remapped(cases):
    """Seed each case's evidence, then return (remapped_case, run) pairs keyed
    by id. Gold ids are remapped to the seeded real note ids."""
    if _SERVICE is None:
        pytest.skip(_SKIP_REASON)
    references = _load_reference_runs()
    out: dict[str, tuple] = {}
    for case in cases:
        ref = references.get(case.id)
        if not ref:
            continue
        id_map = seed_case_notes(_SERVICE, case, ref)
        remapped_gold = [id_map.get(g, g) for g in case.gold_evidence_ids]
        remapped_case = dataclasses.replace(case, gold_evidence_ids=remapped_gold)
        run = ask_case(_SERVICE, case)
        out[case.id] = (remapped_case, run)
    return out


@pytest.fixture(scope="module")
def baseline():
    path = Path(__file__).parent / "baseline_real.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP_REASON)
class TestRagQualityRealGate:
    def test_aggregate_meets_real_baseline(self, remapped, baseline):
        eval_cases = [c for c, _ in remapped.values()]
        runs = {cid: run for cid, (_, run) in remapped.items()}
        report = score_all(eval_cases, runs)
        misses = [
            f"  {c.id}: recall_5={score_case(c, runs[c.id]).recall_5:.2f} "
            f"gold={c.gold_evidence_ids} ranked={runs[c.id].ranked_evidence_ids[:5]}"
            for c in eval_cases
            if score_case(c, runs[c.id]).recall_5 == 0.0
        ]
        report_text = report.summary() + "\nzero-recall cases:\n" + "\n".join(misses or ["  (none)"])
        print(report_text)
        failures = report.check_thresholds(baseline)
        assert not failures, f"real-RAG regression:\n{report_text}\nfailures={failures}"

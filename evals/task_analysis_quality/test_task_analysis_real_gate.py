"""Real-environment TaskAnalyzer golden test.

Drives the bundled golden set through a real ``DefaultTaskAnalyzer`` and scores
it against ``baseline_real.json`` (looser than the offline baseline — a live
model is not deterministic). Skips cleanly when no TaskAnalyzer model is configured, so
it is safe to collect in CI but only enforces when a key is present.

This is the layer that scores the *real* model, not the stub — the gap the DNS
incident exposed. Run it with a configured structured model:
    uv run pytest evals/task_analysis_quality/test_task_analysis_real_gate.py -v

The per-case mismatch report prints every input where the real analyzer diverged
from gold, so prompt regressions (e.g. a question mis-routed to solidify) are
visible even when the aggregate still clears the looser floor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .dataset import TaskAnalysisRunOutput, default_cases_path, load_cases
from .real_runner import build_real_analyzer, classify_case
from .scorer import score_all

_ANALYZER = build_real_analyzer()
_SKIP_REASON = "TaskAnalyzer model is not configured"


@pytest.fixture(scope="module")
def cases():
    return load_cases(default_cases_path())


@pytest.fixture(scope="module")
def runs(cases) -> dict[str, TaskAnalysisRunOutput]:
    if _ANALYZER is None:
        pytest.skip(_SKIP_REASON)
    return {case.id: classify_case(_ANALYZER, case) for case in cases}


@pytest.fixture(scope="module")
def baseline():
    path = Path(__file__).parent / "baseline_real.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@pytest.mark.skipif(_ANALYZER is None, reason=_SKIP_REASON)
class TestTaskAnalysisRealGate:
    def test_aggregate_meets_real_baseline(self, cases, runs, baseline):
        report = score_all(cases, runs)
        # Always surface per-case divergences for debuggability.
        mismatches = [
            f"  {c.id} [{c.text[:20]}]: gold={c.expected_outcome}/{c.expected_result_contracts} "
            f"got={runs[c.id].outcome}/{runs[c.id].result_contracts}"
            for c in cases
            if runs[c.id].outcome != c.expected_outcome
            or runs[c.id].result_contracts != c.expected_result_contracts
        ]
        report_text = report.summary() + "\nmismatches:\n" + "\n".join(mismatches or ["  (none)"])
        print(report_text)
        failures = report.check_thresholds(baseline)
        assert not failures, f"real TaskAnalyzer regression:\n{report_text}\nfailures={failures}"

    def test_dns_incident_question_routes_to_ask(self, cases, runs):
        """Regression for the DNS incident: a bare knowledge question must route
        to ask, never solidify_conversation."""
        for case in cases:
            if case.expected_result_contracts == ["response"]:
                run = runs[case.id]
                assert "external_state" not in run.result_contracts, (
                    f"{case.id} [{case.text[:20]}]: question mis-routed to "
                    f"solidify_conversation (the DNS incident shape); got {run.result_contracts}"
                )

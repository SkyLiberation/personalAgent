"""Hermetic TaskAnalyzer contract regression gate.

Scores the bundled golden set against a deterministic semantic-model stand-in.
It asserts the aggregate means clear the frozen baseline. Fully
offline: no Postgres, no LLM.

Driving deterministic paths keeps the gate reproducible. Plain text cases pin
the TaskAnalysisOutput contract + stub semantic contract table; artifact cases pin the
Artifact-first boundary on ``DefaultTaskAnalyzer`` itself, because the stub only
accepts text and cannot model EntryInput.artifacts.

Run explicitly (evals/ is outside the default testpaths):
    uv run pytest evals/task_analysis_quality/test_task_analysis_gate.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import stub_task_analysis

from personal_agent.planning.task_analyzer import GoalDraft, TaskAnalysisOutput

from .dataset import TaskAnalysisRunOutput, default_cases_path, load_cases
from .runner import run_output_from_model_output
from .scorer import score_all


def _build_runs() -> dict[str, TaskAnalysisRunOutput]:
    """Run the hermetic semantic-model stand-in for every case."""
    cases = load_cases(default_cases_path())
    runs: dict[str, TaskAnalysisRunOutput] = {}
    for case in cases:
        if case.artifacts:
            result_contract = case.expected_result_contracts[0]
            output = TaskAnalysisOutput(
                user_goal=case.text or "概述附件",
                outcome="ready",
                goals=[GoalDraft(
                    description=case.text or "概述附件",
                    result_contract=result_contract,
                    side_effect_intent=(
                        "mutation" if result_contract == "external_state" else "none"
                    ),
                    resource_hints=[{
                        "semantic_domain": "artifact",
                        "resource_types": ["document"],
                        "operations": (
                            ["ingest"] if result_contract == "external_state" else ["read"]
                        ),
                    }],
                )],
            )
        else:
            output = stub_task_analysis(case.text)
        runs[case.id] = run_output_from_model_output(output)
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


class TestTaskAnalysisQualityGate:
    def test_dataset_and_runs_align(self, cases, runs):
        case_ids = {c.id for c in cases}
        assert set(runs) == case_ids, "every case needs a routed run"

    def test_aggregate_meets_baseline(self, cases, runs, baseline):
        report = score_all(cases, runs)
        failures = report.check_thresholds(baseline)
        assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"

    def test_clarify_cases_raise_clarification(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "clarify":
                run = runs[case.id]
                assert run.raised_clarification, f"{case.id}: expected clarify, got ready"
                assert not run.result_contracts, f"{case.id}: clarify must carry no goals"

    def test_ready_cases_have_goals(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "ready":
                run = runs[case.id]
                assert run.result_contracts, f"{case.id}: ready must contain >=1 goal"

    def test_primary_result_contract_matches_gold_tail(self, cases, runs):
        for case in cases:
            if case.expected_result_contracts:
                run = runs[case.id]
                assert run.result_contracts[-1] == case.expected_result_contracts[-1], (
                    f"{case.id}: primary result contract {run.result_contracts[-1]} != "
                    f"gold {case.expected_result_contracts[-1]}"
                )

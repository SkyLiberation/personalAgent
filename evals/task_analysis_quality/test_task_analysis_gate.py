"""Hermetic TaskAnalyzer contract regression gate.

Scores the bundled golden set against a deterministic semantic-model stand-in.
It asserts the aggregate means clear the frozen baseline. Fully
offline: no Postgres, no LLM.

Driving deterministic paths keeps the gate reproducible. Plain text cases pin
the TaskAnalysisProposalBody contract + stub semantic contract table; artifact cases pin the
Artifact-first boundary on ``DefaultTaskAnalyzer`` itself, because the stub only
accepts text and cannot model EntryInput.artifacts.

Run explicitly (evals/ is outside the default testpaths):
    uv run pytest evals/task_analysis_quality/test_task_analysis_gate.py -v
"""

from __future__ import annotations

import pytest

from tests.conftest import stub_task_analysis

from personal_agent.planning.task_analyzer import (
    GoalDraft,
    SuccessCriterionDraft,
    TaskAnalysisProposalBody,
)

from .dataset import TaskAnalysisRunOutput, default_cases_path, load_cases
from .runner import run_output_from_model_output


def _build_runs() -> dict[str, TaskAnalysisRunOutput]:
    """Run the hermetic semantic-model stand-in for every case."""
    cases = load_cases(default_cases_path())
    runs: dict[str, TaskAnalysisRunOutput] = {}
    for case in cases:
        if case.artifacts:
            result_contract = case.expected_result_contracts[0]
            output = TaskAnalysisProposalBody(
                user_goal=case.text or "概述附件",
                outcome="ready",
                goals=[GoalDraft(
                    description=case.text or "概述附件",
                    success_criteria=[SuccessCriterionDraft(
                        description="附件请求已按要求完成",
                        origin="model_inferred",
                    )],
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


class TestTaskAnalysisQualityGate:
    def test_dataset_and_runs_align(self, cases, runs):
        case_ids = {c.id for c in cases}
        assert set(runs) == case_ids, "every case needs a routed run"

    def test_each_case_has_exact_outcome_and_contracts(self, cases, runs):
        for case in cases:
            run = runs[case.id]
            assert run.outcome == case.expected_outcome, case.id
            assert run.result_contracts == case.expected_result_contracts, case.id
            if case.expected_outcome == "clarify":
                assert run.raised_clarification, f"{case.id}: expected clarify, got ready"
                assert not run.result_contracts, f"{case.id}: clarify must carry no goals"

    def test_ready_cases_have_goals(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "ready":
                run = runs[case.id]
                assert run.result_contracts, f"{case.id}: ready must contain >=1 goal"

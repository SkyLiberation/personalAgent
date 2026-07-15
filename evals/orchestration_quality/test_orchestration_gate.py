"""End-to-end orchestration-quality regression gate.

Drives every golden-set case through a real ``AgentRuntime`` (entry → task
analysis → goal graph → executive loop → optional HITL interrupt) with a
deterministic TaskAnalyzer stub, then scores the run against the frozen baseline.

Requires Postgres (the LangGraph checkpointer); TaskAnalyzer is stubbed so
analysis is deterministic and no live model endpoint is needed. Cases are
authored so the asserted event *subsequence* is reachable without live
extraction (Neo4j/LLM ingestion), keeping the gate in the fast tier — we pin
milestone ordering and the clarify/ready decision, not ingestion outcomes.

Run explicitly (evals/ is outside the default testpaths, needs Postgres):
    uv run pytest evals/orchestration_quality/test_orchestration_gate.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.kernel.models import EntryInput

from .dataset import OrchestrationRunOutput, default_cases_path, load_cases
from .runner import run_output_from_entry_result
from .scorer import score_all

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture(scope="function")
def runs(runtime) -> dict[str, OrchestrationRunOutput]:
    """Route every case through the real runtime and project to a run output."""
    cases = load_cases(default_cases_path())
    out: dict[str, OrchestrationRunOutput] = {}
    for case in cases:
        result = runtime.execute_entry(
            EntryInput(
                text=case.text,
                user_id="orch-eval",
                session_id=f"orch-{case.id}",
            )
        )
        out[case.id] = run_output_from_entry_result(result)
    return out


@pytest.fixture(scope="function")
def cases():
    return load_cases(default_cases_path())


@pytest.fixture(scope="function")
def baseline():
    path = Path(__file__).parent / "baseline.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


class TestOrchestrationQualityGate:
    def test_dataset_and_runs_align(self, cases, runs):
        assert set(runs) == {c.id for c in cases}, "every case needs a routed run"

    def test_aggregate_meets_baseline(self, cases, runs, baseline):
        report = score_all(cases, runs)
        failures = report.check_thresholds(baseline)
        assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"

    def test_clarify_cases_pause_before_planning(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "clarify":
                run = runs[case.id]
                assert run.paused_for_clarification, f"{case.id}: expected HITL pause"
                assert "goal_graph_compiled" not in run.event_types, (
                    f"{case.id}: clarify must pause before goal compilation"
                )

    def test_ready_cases_reach_goal_compilation(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "ready":
                run = runs[case.id]
                assert not run.paused_for_clarification, f"{case.id}: unexpected pause"
                assert "goal_graph_compiled" in run.event_types, (
                    f"{case.id}: ready run must compile a goal graph"
                )

    def test_primary_result_contract_matches_gold(self, cases, runs):
        for case in cases:
            if case.expected_primary_result_contract:
                run = runs[case.id]
                assert run.primary_result_contract == case.expected_primary_result_contract, (
                    f"{case.id}: {run.primary_result_contract} != "
                    f"{case.expected_primary_result_contract}"
                )

    def test_proceeding_runs_reach_terminal(self, cases, runs):
        # The production "卡住" invariant: any run that proceeds past planning
        # must end on run_completed/run_failed — never hang with neither (which
        # would leave the SSE stream open forever).
        for case in cases:
            if case.must_reach_terminal:
                run = runs[case.id]
                assert run.reached_terminal, (
                    f"{case.id}: run never reached a terminal event "
                    f"(hang risk); events={run.event_types}"
                )

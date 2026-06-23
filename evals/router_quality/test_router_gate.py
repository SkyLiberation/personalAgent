"""Hermetic router-quality regression gate.

Scores the bundled golden set against the project's deterministic router
stand-in (``tests.conftest.stub_router_decision`` — the same keyword router the
integration suite routes through) and asserts the aggregate means clear the
frozen baseline. Fully offline: no Postgres, no LLM.

Driving the *deterministic* router (not a live LLM) keeps the gate reproducible:
it pins the router contract + the stub's routing table against real-scenario
inputs, so a regression in either the RouterOutput contract or the stub's
keyword logic surfaces here. Multi-goal decomposition (ordered ``a → b`` intent
sequences) requires a real LLM router and is covered by the Golden Test,
not this offline gate — every bundled case is single-goal by construction.

Run explicitly (evals/ is outside the default testpaths):
    uv run pytest evals/router_quality/test_router_gate.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import stub_router_decision

from .dataset import RouterRunOutput, default_cases_path, load_cases
from .runner import run_output_from_router_output
from .scorer import score_all


def _build_runs() -> dict[str, RouterRunOutput]:
    """Route every case's text through the deterministic stub router and project
    the transport output into a RouterRunOutput."""
    cases = load_cases(default_cases_path())
    runs: dict[str, RouterRunOutput] = {}
    for case in cases:
        output = stub_router_decision(case.text)
        runs[case.id] = run_output_from_router_output(output)
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


class TestRouterQualityGate:
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
                assert not run.intents, f"{case.id}: clarify must carry no goals"

    def test_ready_cases_route_to_an_intent(self, cases, runs):
        for case in cases:
            if case.expected_outcome == "ready":
                run = runs[case.id]
                assert run.intents, f"{case.id}: ready must route to >=1 intent"

    def test_primary_intent_matches_gold_tail(self, cases, runs):
        # primary_intent is goals[-1]; the last expected intent must match.
        for case in cases:
            if case.expected_intents:
                run = runs[case.id]
                assert run.intents[-1] == case.expected_intents[-1], (
                    f"{case.id}: primary intent {run.intents[-1]} != "
                    f"gold {case.expected_intents[-1]}"
                )

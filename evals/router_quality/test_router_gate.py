"""Hermetic router-quality regression gate.

Scores the bundled golden set against the project's deterministic router
stand-in for plain text cases and the real router's deterministic rule path for
artifact cases. It asserts the aggregate means clear the frozen baseline. Fully
offline: no Postgres, no LLM.

Driving deterministic paths keeps the gate reproducible. Plain text cases pin
the RouterOutput contract + stub routing table; artifact cases pin the
Artifact-first boundary on ``DefaultIntentRouter`` itself, because the stub only
accepts text and cannot model EntryInput.artifacts.

Run explicitly (evals/ is outside the default testpaths):
    uv run pytest evals/router_quality/test_router_gate.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import stub_router_decision

from personal_agent.kernel.models import ArtifactRef, EntryInput
from personal_agent.planning.router import DefaultIntentRouter

from .dataset import RouterRunOutput, default_cases_path, load_cases
from .runner import run_output_from_decision, run_output_from_router_output
from .scorer import score_all


def _build_runs() -> dict[str, RouterRunOutput]:
    """Route every case through a deterministic router path."""
    cases = load_cases(default_cases_path())
    runs: dict[str, RouterRunOutput] = {}
    artifact_router = DefaultIntentRouter(None)
    for case in cases:
        if case.artifacts:
            decision = artifact_router.classify(EntryInput(
                text=case.text,
                source_type=case.source_type,
                artifacts=[_artifact_ref(item) for item in case.artifacts],
            ))
            runs[case.id] = run_output_from_decision(decision)
        else:
            output = stub_router_decision(case.text)
            runs[case.id] = run_output_from_router_output(output)
    return runs


def _artifact_ref(data: dict) -> ArtifactRef:
    filename = str(data.get("filename") or "artifact.bin")
    source_type = str(data.get("source_type") or "file")
    return ArtifactRef(
        artifact_id=str(data.get("artifact_id") or f"art-golden-{filename}"),
        filename=filename,
        content_type=data.get("content_type"),
        source_type=source_type,
        file_path=str(data.get("file_path") or f"/tmp/{filename}"),
        size_bytes=int(data.get("size_bytes") or 1),
    )


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

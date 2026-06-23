"""Multi-turn Golden Test using the real router LLM and real runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .dataset import default_cases_path, load_cases
from .real_runner import build_real_service, execute_real_case
from .scorer import score_all

_SERVICE = build_real_service()
_SKIP = "router LLM/Postgres not configured for real conversation evaluation"


@pytest.fixture(scope="module")
def cases():
    return load_cases(default_cases_path())


@pytest.fixture(scope="module")
def runs(cases):
    if _SERVICE is None:
        pytest.skip(_SKIP)
    return {case.id: execute_real_case(_SERVICE, case) for case in cases}


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP)
def test_real_multi_turn_suite_meets_baseline(cases, runs):
    report = score_all(cases, runs)
    print(report.summary())
    raw = json.loads(
        (Path(__file__).parent / "baseline_real.json").read_text(encoding="utf-8")
    )
    baseline = {key: value for key, value in raw.items() if not key.startswith("_")}
    failures = report.check_thresholds(baseline)
    assert not failures, f"real conversation regression:\n{report.summary()}\n{failures}"


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP)
def test_real_runs_never_fork_a_case_across_threads(cases, runs):
    for case in cases:
        run = runs[case.id]
        thread_ids = [turn.thread_id for turn in run.turns]
        assert thread_ids and len(set(thread_ids)) == 1, f"{case.id}: {thread_ids}"

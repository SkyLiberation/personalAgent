"""Offline conversation golden-set gate; no Postgres or live model required."""

from __future__ import annotations

import json
from pathlib import Path

from .dataset import (
    default_cases_path,
    default_reference_runs_path,
    load_cases,
    load_runs,
)
from .scorer import score_all


def _baseline() -> dict[str, float]:
    raw = json.loads((Path(__file__).parent / "baseline.json").read_text(encoding="utf-8"))
    return {key: value for key, value in raw.items() if not key.startswith("_")}


def test_dataset_has_real_multi_turn_shape():
    cases = load_cases(default_cases_path())
    assert len(cases) >= 8
    assert all(len(case.turns) >= 2 for case in cases)
    assert any(any(turn.kind == "resume" for turn in case.turns) for case in cases)
    assert any(case.expected_final_note_delta is not None for case in cases)
    assert any(
        turn.expected_context_refs
        for case in cases
        for turn in case.turns
    )


def test_reference_runs_align_and_meet_baseline():
    cases = load_cases(default_cases_path())
    runs = load_runs(default_reference_runs_path())
    assert set(runs) == {case.id for case in cases}
    report = score_all(cases, runs)
    failures = report.check_thresholds(_baseline())
    assert not failures, f"conversation regression:\n{report.summary()}\n{failures}"


def test_resume_projection_reuses_run_and_thread():
    cases = load_cases(default_cases_path())
    runs = load_runs(default_reference_runs_path())
    for case in cases:
        for gold, actual in zip(case.turns, runs[case.id].turns):
            if gold.kind != "resume":
                continue
            assert actual.run_id == actual.resumed_from_run_id
            assert actual.reached_terminal

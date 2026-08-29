"""The impact map must stay honest as the tree changes.

The failure mode worth defending against is not a wrong rule, it is a *missing*
rule that silently produces a small live selection for a change nobody routed.
``test_every_source_path_is_routed`` is the one that will fail on new packages,
and that failure is the point: adding production code should force a decision
about which live evidence it can break.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES
from evals.e2e_quality.impact_map import (
    IMPACT_RULES,
    ImpactKind,
    ImpactRule,
    match_rule,
    select_live_cases,
    validate_impact_map,
)
from scripts.e2e_impact import (
    _FULL_COMMAND,
    _FULL_ITERATION_COMMAND,
    _emit,
    _history_ordered_iteration_command,
    _latest_complete_release_durations,
    _release_nodeids,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCANNED_ROOTS = ("src", "evals", "scripts", "tests")
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def _all_repo_paths() -> list[str]:
    paths: list[str] = []
    for base in _SCANNED_ROOTS:
        for root, dirs, files in os.walk(REPO_ROOT / base):
            dirs[:] = [item for item in dirs if item not in _SKIP_DIRS]
            for name in files:
                full = Path(root) / name
                paths.append(full.relative_to(REPO_ROOT).as_posix())
    return paths


def test_catalog_consistency_is_validated_at_import() -> None:
    validate_impact_map()


def test_every_source_path_is_routed() -> None:
    unrouted = sorted(path for path in _all_repo_paths() if match_rule(path) is None)
    assert not unrouted, (
        "these paths have no impact rule, so a change to them cannot be routed "
        "to live evidence. Add a rule (CASES / FULL_MATRIX / NO_IMPACT) for each:\n"
        + "\n".join(f"  {path}" for path in unrouted)
    )


def test_every_rule_prefix_exists_on_disk() -> None:
    """A rule for a path that no longer exists is a stale guess, not coverage."""
    stale: list[str] = []
    for rule in IMPACT_RULES:
        target = REPO_ROOT / rule.path_prefix
        if target.exists():
            continue
        parent = target.parent
        if parent.is_dir() and any(
            child.as_posix().startswith(target.as_posix()) for child in parent.iterdir()
        ):
            continue
        stale.append(rule.path_prefix)
    assert not stale, "impact rules point at paths that do not exist: " + ", ".join(stale)


def test_unmapped_path_forces_full_matrix() -> None:
    selection = select_live_cases(["src/personal_agent/brand_new_package/thing.py"])
    assert selection.full_matrix_required is True
    assert selection.unmapped_paths == ("src/personal_agent/brand_new_package/thing.py",)
    assert "unmapped_path" in selection.reasons


def test_declared_no_impact_selects_nothing() -> None:
    selection = select_live_cases(["docs/README.md", "tests/test_something.py"])
    assert selection.full_matrix_required is False
    assert selection.case_ids == ()
    assert len(selection.no_impact_paths) == 2


def test_interaction_loop_owner_forces_full_matrix() -> None:
    """The turn loop touches every conversation journey; it must not narrow."""
    selection = select_live_cases(
        ["src/personal_agent/application/conversation/service.py"]
    )
    assert selection.full_matrix_required is True


def test_selection_maps_to_real_pytest_node_names() -> None:
    selection = select_live_cases(
        ["src/personal_agent/tools/interaction_verifier.py"]
    )
    assert selection.case_ids == ("L06",)
    known_names = {case.test_name for case in EVIDENCE_CASES}
    for name in selection.pytest_k_expression().split(" or "):
        assert name in known_names


def test_full_matrix_selection_has_no_k_expression() -> None:
    """A full-matrix outcome must not emit a filter that would narrow the run."""
    selection = select_live_cases(["src/personal_agent/main.py"])
    assert selection.full_matrix_required is True
    assert selection.pytest_k_expression() == ""


def test_full_matrix_output_separates_iteration_from_release_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    selection = select_live_cases(["src/personal_agent/main.py"])

    assert _emit(selection, quiet=False) == 0

    output = capsys.readouterr().out
    assert "iteration command (fail-fast; not release evidence):" in output
    assert "--e2e-require-complete-matrix -x" in output
    assert "release evidence command (records every case outcome):" in output
    assert _FULL_COMMAND in output
    assert "--e2e-require-complete-matrix -x" in _FULL_ITERATION_COMMAND
    assert " -x " not in _FULL_COMMAND


def test_quiet_full_matrix_output_preserves_complete_release_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    selection = select_live_cases(["src/personal_agent/main.py"])

    assert _emit(selection, quiet=True) == 0

    assert capsys.readouterr().out == f"{_FULL_COMMAND}\n"


def test_iteration_command_orders_every_release_node_by_sealed_duration() -> None:
    nodeids = _release_nodeids()
    durations = {
        nodeid: float(index)
        for index, nodeid in enumerate(reversed(nodeids), start=1)
    }

    command = _history_ordered_iteration_command(durations)

    ordered = sorted(nodeids, key=lambda nodeid: (durations[nodeid], nodeid))
    positions = [command.index(nodeid) for nodeid in ordered]
    assert positions == sorted(positions)
    assert all(command.count(nodeid) == 1 for nodeid in nodeids)
    assert "--e2e-require-complete-matrix -x" in command


def test_iteration_command_falls_back_without_complete_history() -> None:
    assert _history_ordered_iteration_command(None) == _FULL_ITERATION_COMMAND


def test_duration_order_uses_latest_complete_checksum_valid_release_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodeids = _release_nodeids()

    def write_summary(name: str, finished_at: str, selected: tuple[str, ...]) -> None:
        run_dir = tmp_path / name
        run_dir.mkdir()
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "finished_at": finished_at,
                    "tests": [
                        {
                            "nodeid": nodeid,
                            "phases": {
                                "call": {"duration_seconds": float(index + 1)}
                            },
                        }
                        for index, nodeid in enumerate(selected)
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_summary("older-complete", "2026-08-27T00:00:00Z", nodeids)
    write_summary("newer-incomplete", "2026-08-28T00:00:00Z", nodeids[:-1])
    write_summary("invalid-complete", "2026-08-29T00:00:00Z", nodeids)
    monkeypatch.setattr(
        "scripts.e2e_impact.archive_checksums_valid",
        lambda run_dir: run_dir.name != "invalid-complete",
    )

    durations, source = _latest_complete_release_durations(tmp_path)

    assert durations is not None
    assert set(durations) == set(nodeids)
    assert source == "data/e2e_traces/older-complete/summary.json"


@pytest.mark.parametrize("kind", [ImpactKind.FULL_MATRIX, ImpactKind.NO_IMPACT])
def test_non_case_rules_reject_case_ids(kind: ImpactKind) -> None:
    with pytest.raises(ValueError, match="must not carry case_ids"):
        ImpactRule(
            path_prefix="src/x", kind=kind, case_ids=frozenset({"E01"}), rationale="x"
        )


def test_cases_rule_requires_at_least_one_case() -> None:
    with pytest.raises(ValueError, match="declares CASES but selects none"):
        ImpactRule(path_prefix="src/x", kind=ImpactKind.CASES, rationale="x")


def test_rule_requires_rationale() -> None:
    with pytest.raises(ValueError, match="requires a rationale"):
        ImpactRule(path_prefix="src/x", kind=ImpactKind.NO_IMPACT)

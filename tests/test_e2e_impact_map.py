"""The impact map must stay honest as the tree changes.

The failure mode worth defending against is not a wrong rule, it is a *missing*
rule that silently produces a small live selection for a change nobody routed.
``test_every_source_path_is_routed`` is the one that will fail on new packages,
and that failure is the point: adding production code should force a decision
about which live evidence it can break.
"""

from __future__ import annotations

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

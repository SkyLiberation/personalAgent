"""Route the current diff to the live E2E cases that must re-run.

The full matrix is expensive enough that it runs rarely, which is exactly how
a change ends up with no live support at all.  This prints the smallest live
command that still covers the diff, so live validation can happen per change
instead of only before a release.

It never claims release qualification. Release eligibility still comes only
from ``release_gate.py`` over a clean matching revision.

Usage:
    python scripts/e2e_impact.py                  # uncommitted work
    python scripts/e2e_impact.py --base HEAD~3    # against a base ref
    python scripts/e2e_impact.py --paths a.py b.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.e2e_quality.impact_map import (  # noqa: E402
    ImpactKind,
    match_rule,
    select_live_cases,
)
from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES  # noqa: E402
from evals.e2e_quality.trace_archive import archive_checksums_valid  # noqa: E402


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_paths(base: str | None) -> list[str]:
    if base:
        return _git("diff", "--name-only", f"{base}...HEAD")
    tracked = _git("diff", "--name-only", "HEAD")
    untracked = _git("ls-files", "--others", "--exclude-standard")
    return sorted(set(tracked) | set(untracked))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="compare against this ref instead of the worktree")
    parser.add_argument("--paths", nargs="*", help="explicit paths instead of git")
    parser.add_argument(
        "--quiet", action="store_true", help="print only the pytest command"
    )
    args = parser.parse_args()

    paths = args.paths if args.paths else changed_paths(args.base)
    if not paths:
        print("no changed paths; nothing to route")
        return 0

    selection = select_live_cases(paths)

    if not args.quiet:
        print(f"changed paths: {len(paths)}")
        interesting = [
            (path, rule)
            for path, rule in (
                (path, match_rule(path)) for path in paths
            )
            if rule is not None and rule.kind is not ImpactKind.NO_IMPACT
        ]
        for path, rule in interesting:
            marker = "FULL" if rule.kind is ImpactKind.FULL_MATRIX else ",".join(
                sorted(rule.case_ids)
            )
            print(f"  {path}\n      -> {marker}  ({rule.rationale.splitlines()[0]})")
        if selection.no_impact_paths:
            print(f"  declared no-impact: {len(selection.no_impact_paths)} path(s)")
        if selection.unmapped_paths:
            print("  UNMAPPED (forces full matrix):")
            for path in selection.unmapped_paths:
                print(f"      {path}")
        print()
    return _emit(selection, quiet=args.quiet)


_FULL_COMMAND = (
    "pytest evals/e2e_quality --e2e-scope=release --e2e-require-complete-matrix -q -s"
)
_FULL_ITERATION_COMMAND = (
    "pytest evals/e2e_quality --e2e-scope=release "
    "--e2e-require-complete-matrix -x -q -s"
)
_TRACE_ROOT = REPO_ROOT / "data" / "e2e_traces"


def _release_nodeids() -> tuple[str, ...]:
    return tuple(
        f"evals/e2e_quality/{case.module}::{case.test_name}"
        for case in EVIDENCE_CASES
        if case.release_eligible
    )


def _history_ordered_iteration_command(
    durations: Mapping[str, float] | None,
) -> str:
    if durations is None:
        return _FULL_ITERATION_COMMAND
    nodeids = sorted(
        _release_nodeids(),
        key=lambda nodeid: (durations[nodeid], nodeid),
    )
    return (
        "pytest "
        + " ".join(nodeids)
        + " --e2e-scope=release --e2e-require-complete-matrix -x -q -s"
    )


def _latest_complete_release_durations(
    trace_root: Path = _TRACE_ROOT,
) -> tuple[dict[str, float] | None, str | None]:
    """Read ordering only from the latest sealed run that contains every release case."""
    required = set(_release_nodeids())
    candidates: list[tuple[str, str, dict[str, float]]] = []
    if not trace_root.is_dir():
        return None, None
    for run_dir in trace_root.iterdir():
        summary_path = run_dir / "summary.json"
        if not run_dir.is_dir() or not summary_path.is_file():
            continue
        if not archive_checksums_valid(run_dir):
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            durations = {
                str(item["nodeid"]).split("[", 1)[0]: float(
                    item["phases"]["call"]["duration_seconds"]
                )
                for item in summary["tests"]
                if isinstance(item.get("phases", {}).get("call"), dict)
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not required.issubset(durations):
            continue
        candidates.append(
            (str(summary.get("finished_at", "")), run_dir.name, durations)
        )
    if not candidates:
        return None, None
    _, run_name, durations = max(candidates, key=lambda item: (item[0], item[1]))
    return durations, f"data/e2e_traces/{run_name}/summary.json"


def _emit(selection, *, quiet: bool) -> int:
    if selection.full_matrix_required:
        if not quiet:
            durations, ordering_source = _latest_complete_release_durations()
            iteration_command = _history_ordered_iteration_command(durations)
            print("routing: FULL MATRIX required")
            for reason in selection.reasons:
                print(f"  reason: {reason}")
            print()
            print("iteration command (fail-fast; not release evidence):")
            print(iteration_command)
            if ordering_source is not None:
                print(f"ordering evidence: {ordering_source}")
            print()
            print("release evidence command (records every case outcome):")
        print(_FULL_COMMAND)
        return 0

    if not selection.case_ids:
        print("no live case is affected by this diff")
        return 0

    expression = selection.pytest_k_expression()
    if not quiet:
        print(f"routing: {len(selection.case_ids)} live case(s): "
              f"{', '.join(selection.case_ids)}")
        print("this narrows day-to-day validation only; the periodic full matrix")
        print("still owns provider-side and prompt-wording drift.")
        print()
    print(
        "pytest evals/e2e_quality --e2e-scope=release -q -s \\\n"
        f'  -k "{expression}"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

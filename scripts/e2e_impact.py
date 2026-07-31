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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.e2e_quality.impact_map import (  # noqa: E402
    ImpactKind,
    match_rule,
    select_live_cases,
)


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


def _emit(selection, *, quiet: bool) -> int:
    if selection.full_matrix_required:
        if not quiet:
            print("routing: FULL MATRIX required")
            for reason in selection.reasons:
                print(f"  reason: {reason}")
            print()
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

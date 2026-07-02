from __future__ import annotations

import re
from typing import Iterable


def split_selector(value: str | None) -> tuple[str, ...]:
    """Parse comma/semicolon/whitespace separated selector values."""
    if not value:
        return ()
    return tuple(item for item in re.split(r"[,;\s]+", value.strip()) if item)


def select_case_ids(
    cases: Iterable[object],
    runner_ids: Iterable[str],
    *,
    case_selector: str | None = None,
    branch_selector: str | None = None,
) -> tuple[str, ...]:
    case_by_id = {str(getattr(case, "id")): case for case in cases}
    ordered_runner_ids = tuple(str(item) for item in runner_ids)
    known_runner_ids = set(ordered_runner_ids)
    selected = list(ordered_runner_ids)

    requested_cases = split_selector(case_selector)
    if requested_cases:
        unknown = sorted(set(requested_cases) - set(case_by_id))
        if unknown:
            raise ValueError(f"Unknown e2e_quality case id(s): {', '.join(unknown)}")
        missing_runners = sorted(set(requested_cases) - known_runner_ids)
        if missing_runners:
            raise ValueError(
                "Selected e2e_quality case(s) have no runner: "
                + ", ".join(missing_runners)
            )
        requested = set(requested_cases)
        selected = [case_id for case_id in selected if case_id in requested]

    requested_branches = split_selector(branch_selector)
    if requested_branches:
        known_branches = {str(getattr(case, "branch")) for case in case_by_id.values()}
        unknown = sorted(set(requested_branches) - known_branches)
        if unknown:
            raise ValueError(f"Unknown e2e_quality branch(es): {', '.join(unknown)}")
        requested = set(requested_branches)
        selected = [
            case_id for case_id in selected
            if str(getattr(case_by_id[case_id], "branch")) in requested
        ]

    if not selected:
        raise ValueError("No e2e_quality cases selected.")
    return tuple(selected)


def selection_requested(
    *,
    case_selector: str | None = None,
    branch_selector: str | None = None,
) -> bool:
    return bool(split_selector(case_selector) or split_selector(branch_selector))


def baseline_should_be_enforced(
    *,
    case_selector: str | None = None,
    branch_selector: str | None = None,
    enforce_value: str | None = None,
) -> bool:
    value = (enforce_value or "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return not selection_requested(
        case_selector=case_selector,
        branch_selector=branch_selector,
    )

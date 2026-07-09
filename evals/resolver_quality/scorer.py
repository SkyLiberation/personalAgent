from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from evals.resolver_quality.dataset import ResolverQualityCase


@dataclass(frozen=True)
class ResolverQualityRun:
    case_id: str
    selected_capability_ids: tuple[str, ...]
    denied_reasons: tuple[str, ...]


@dataclass(frozen=True)
class MetricScore:
    name: str
    score: float
    reason: str = ""


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    score: float
    metrics: tuple[MetricScore, ...]


@dataclass(frozen=True)
class ResolverQualityReport:
    scores: tuple[CaseScore, ...]

    @property
    def overall_score(self) -> float:
        return round(mean(score.score for score in self.scores), 4) if self.scores else 0.0

    def check_thresholds(self, baseline: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        min_overall = float(baseline.get("min_overall", 0.0))
        if self.overall_score < min_overall:
            failures.append(f"overall {self.overall_score:.4f} < {min_overall:.4f}")
        min_case_score = float(baseline.get("min_case_score", 0.0))
        for score in self.scores:
            if score.score < min_case_score:
                failures.append(f"{score.case_id} {score.score:.4f} < {min_case_score:.4f}")
        critical_min = float(baseline.get("critical_case_min_score", 1.0))
        by_id = {score.case_id: score for score in self.scores}
        for case_id in baseline.get("critical_cases", ()) or ():
            score = by_id.get(str(case_id))
            if score is None:
                failures.append(f"critical {case_id} missing")
            elif score.score < critical_min:
                failures.append(f"critical {case_id} {score.score:.4f} < {critical_min:.4f}")
        return failures


def score_all(
    cases: tuple[ResolverQualityCase, ...],
    runs: tuple[ResolverQualityRun, ...],
) -> ResolverQualityReport:
    by_id = {run.case_id: run for run in runs}
    return ResolverQualityReport(tuple(score_case(case, by_id[case.id]) for case in cases))


def score_case(case: ResolverQualityCase, run: ResolverQualityRun) -> CaseScore:
    metrics: list[MetricScore] = []
    selected = set(run.selected_capability_ids)
    missing = set(case.expected_capability_ids) - selected
    metrics.append(MetricScore(
        "expected_capabilities",
        1.0 if not missing else 0.0,
        "" if not missing else f"missing={sorted(missing)} actual={list(run.selected_capability_ids)}",
    ))
    forbidden = set(case.forbidden_capability_ids) & selected
    metrics.append(MetricScore(
        "forbidden_capabilities",
        1.0 if not forbidden else 0.0,
        "" if not forbidden else f"forbidden={sorted(forbidden)}",
    ))
    if case.expected_denial_reasons:
        missing_reasons = set(case.expected_denial_reasons) - set(run.denied_reasons)
        metrics.append(MetricScore(
            "denial_reasons",
            1.0 if not missing_reasons else 0.0,
            "" if not missing_reasons else f"missing={sorted(missing_reasons)} actual={list(run.denied_reasons)}",
        ))
    if case.min_selected:
        metrics.append(MetricScore(
            "min_selected",
            1.0 if len(run.selected_capability_ids) >= case.min_selected else 0.0,
            f"actual={len(run.selected_capability_ids)} min={case.min_selected}",
        ))
    if case.max_selected is not None:
        metrics.append(MetricScore(
            "max_selected",
            1.0 if len(run.selected_capability_ids) <= case.max_selected else 0.0,
            f"actual={len(run.selected_capability_ids)} max={case.max_selected}",
        ))
    return CaseScore(
        case_id=case.id,
        score=round(mean(metric.score for metric in metrics), 4) if metrics else 1.0,
        metrics=tuple(metrics),
    )


__all__ = [
    "CaseScore",
    "MetricScore",
    "ResolverQualityReport",
    "ResolverQualityRun",
    "score_all",
    "score_case",
]

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from evals.agent_gateway_quality.dataset import AgentGatewayQualityCase


@dataclass(frozen=True)
class AgentGatewayQualityRun:
    case_id: str
    agent_id: str
    status: str
    permission_scope: str = ""
    artifact_statuses: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    stream_event_types: tuple[str, ...] = ()


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
class AgentGatewayQualityReport:
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
        by_id = {score.case_id: score for score in self.scores}
        for score in self.scores:
            if score.score < min_case_score:
                failures.append(f"{score.case_id} {score.score:.4f} < {min_case_score:.4f}")
        critical_min = float(baseline.get("critical_case_min_score", 1.0))
        for case_id in baseline.get("critical_cases", ()) or ():
            score = by_id.get(str(case_id))
            if score is None:
                failures.append(f"critical {case_id} missing")
            elif score.score < critical_min:
                failures.append(f"critical {case_id} {score.score:.4f} < {critical_min:.4f}")
        return failures


def score_all(
    cases: tuple[AgentGatewayQualityCase, ...],
    runs: tuple[AgentGatewayQualityRun, ...],
) -> AgentGatewayQualityReport:
    by_id = {run.case_id: run for run in runs}
    return AgentGatewayQualityReport(tuple(score_case(case, by_id[case.id]) for case in cases))


def score_case(case: AgentGatewayQualityCase, run: AgentGatewayQualityRun) -> CaseScore:
    metrics: list[MetricScore] = []
    if case.expected_status:
        metrics.append(_exact("status", run.status, case.expected_status))
    if case.expected_permission_scope:
        metrics.append(_exact("permission_scope", run.permission_scope, case.expected_permission_scope))
    if case.expected_artifact_status:
        metrics.append(MetricScore(
            "artifact_status",
            1.0 if case.expected_artifact_status in run.artifact_statuses else 0.0,
            f"actual={run.artifact_statuses!r}",
        ))
    if case.expected_stream_event_types:
        missing = set(case.expected_stream_event_types) - set(run.stream_event_types)
        metrics.append(MetricScore(
            "stream_event_types",
            1.0 if not missing else 0.0,
            "" if not missing else f"missing={sorted(missing)} actual={list(run.stream_event_types)}",
        ))
    for forbidden in case.forbidden_agent_ids:
        metrics.append(MetricScore(
            f"agent_forbidden:{forbidden}",
            0.0 if run.agent_id == forbidden else 1.0,
            f"actual={run.agent_id!r}" if run.agent_id == forbidden else "",
        ))
    if case.min_events:
        metrics.append(MetricScore(
            "events",
            1.0 if len(run.event_types) >= case.min_events else 0.0,
            f"actual={len(run.event_types)} min={case.min_events}",
        ))
    return CaseScore(
        case_id=case.id,
        score=round(mean(metric.score for metric in metrics), 4) if metrics else 1.0,
        metrics=tuple(metrics),
    )


def _exact(name: str, actual: str, expected: str) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual == expected else 0.0,
        "" if actual == expected else f"actual={actual!r} expected={expected!r}",
    )


__all__ = [
    "AgentGatewayQualityReport",
    "AgentGatewayQualityRun",
    "CaseScore",
    "MetricScore",
    "score_all",
    "score_case",
]

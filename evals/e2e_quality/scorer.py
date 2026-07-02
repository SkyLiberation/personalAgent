from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class E2EQualityCase:
    id: str
    branch: str
    description: str
    expected_intents: tuple[str, ...] = ()
    expected_workflow_id: str = ""
    expected_steps: tuple[str, ...] = ()
    expected_run_statuses: tuple[str, ...] = ()
    expected_research_statuses: tuple[str, ...] = ()
    expected_event_statuses: tuple[str, ...] = ()
    expected_confidence_labels: tuple[str, ...] = ()
    expected_stop_reason: str = ""
    expected_task_dependency: tuple[str, str] | None = None
    expected_grounding_statuses: tuple[str, ...] = ()
    expected_claim_statuses: tuple[str, ...] = ()
    expected_web_tried: bool | None = None
    expected_satisfaction_should_continue: bool | None = None
    expected_gap_types: tuple[str, ...] = ()
    expected_tool_error_kinds: tuple[str, ...] = ()
    required_web_query_terms: tuple[str, ...] = ()
    required_web_query_term_groups: tuple[tuple[str, ...], ...] = ()
    required_answer_terms: tuple[str, ...] = ()
    required_answer_term_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_answer_terms: tuple[str, ...] = ()
    required_digest_terms: tuple[str, ...] = ()
    required_digest_term_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_digest_terms: tuple[str, ...] = ()
    min_matches: int = 0
    min_citations: int = 0
    min_evidence: int = 0
    min_verification_score: float | None = None
    max_matches: int | None = None
    max_citations: int | None = None
    max_evidence: int | None = None
    max_llm_calls: int | None = None
    min_notes: int = 0
    min_sources: int = 0
    min_events: int = 0
    max_events: int | None = None
    min_digest_items: int = 0
    min_web_search_calls: int = 0
    min_tool_call_traces: int = 0
    min_failed_tool_calls: int = 0
    min_stage_timings: int = 0
    min_satisfaction_coverage_score: float | None = None
    min_satisfaction_confidence_score: float | None = None
    max_satisfaction_marginal_gain: float | None = None
    require_unique_canonical_urls: bool = False


@dataclass(frozen=True)
class E2EQualityRun:
    case_id: str
    branch: str
    intents: tuple[str, ...] = ()
    run_status: str = ""
    workflow_id: str = ""
    step_ids: tuple[str, ...] = ()
    answer: str = ""
    matches_count: int = 0
    citations_count: int = 0
    evidence_count: int = 0
    llm_call_count: int = 0
    verification_score: float = 0.0
    grounding_status: str = ""
    claim_statuses: tuple[str, ...] = ()
    web_tried: bool = False
    note_count: int = 0
    dependency_edges: tuple[tuple[str, str], ...] = ()
    research_status: str = ""
    source_count: int = 0
    event_count: int = 0
    digest_item_count: int = 0
    digest_text: str = ""
    event_statuses: tuple[str, ...] = ()
    confidence_labels: tuple[str, ...] = ()
    web_search_queries: tuple[str, ...] = ()
    gap_types: tuple[str, ...] = ()
    satisfaction_should_continue: bool | None = None
    satisfaction_coverage_score: float = 0.0
    satisfaction_confidence_score: float = 0.0
    satisfaction_marginal_gain: float = 0.0
    stop_reason: str = ""
    tool_call_trace_count: int = 0
    failed_tool_call_count: int = 0
    tool_error_kinds: tuple[str, ...] = ()
    stage_timing_count: int = 0
    canonical_urls: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricScore:
    name: str
    score: float
    reason: str = ""


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    branch: str
    score: float
    metrics: tuple[MetricScore, ...]


@dataclass(frozen=True)
class E2EQualityReport:
    scores: tuple[CaseScore, ...]

    @property
    def overall_score(self) -> float:
        return round(mean(score.score for score in self.scores), 4) if self.scores else 0.0

    def branch_score(self, branch: str) -> float:
        branch_scores = [score.score for score in self.scores if score.branch == branch]
        return round(mean(branch_scores), 4) if branch_scores else 0.0

    def summary(self) -> str:
        lines = [f"overall={self.overall_score:.4f}"]
        for branch in sorted({score.branch for score in self.scores}):
            lines.append(f"{branch}={self.branch_score(branch):.4f}")
        for score in self.scores:
            failed = [metric for metric in score.metrics if metric.score < 1.0]
            if failed:
                details = "; ".join(f"{m.name}:{m.reason}" for m in failed)
                lines.append(f"{score.case_id}={score.score:.4f} {details}")
        return "\n".join(lines)

    def check_thresholds(self, baseline: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        min_overall = float(baseline.get("min_overall", 0.0))
        if self.overall_score < min_overall:
            failures.append(f"overall {self.overall_score:.4f} < {min_overall:.4f}")
        min_case_score = float(baseline.get("min_case_score", 0.0))
        for score in self.scores:
            if score.score < min_case_score:
                failures.append(
                    f"{score.case_id} {score.score:.4f} < {min_case_score:.4f}"
                )
        for case_id, threshold in (baseline.get("min_case_scores") or {}).items():
            case_score = self._score_by_case_id(str(case_id))
            threshold_value = float(threshold)
            if case_score is None:
                failures.append(f"{case_id} missing")
            elif case_score.score < threshold_value:
                failures.append(
                    f"{case_id} {case_score.score:.4f} < {threshold_value:.4f}"
                )
        critical_threshold = float(baseline.get("critical_case_min_score", 1.0))
        for case_id in baseline.get("critical_cases", ()) or ():
            case_score = self._score_by_case_id(str(case_id))
            if case_score is None:
                failures.append(f"critical {case_id} missing")
            elif case_score.score < critical_threshold:
                failures.append(
                    f"critical {case_id} {case_score.score:.4f} < "
                    f"{critical_threshold:.4f}"
                )
        min_pass_rate = baseline.get("min_case_pass_rate")
        if min_pass_rate is not None:
            pass_score = float(baseline.get("case_pass_score", min_case_score))
            pass_rate = self.case_pass_rate(pass_score)
            threshold_value = float(min_pass_rate)
            if pass_rate < threshold_value:
                failures.append(
                    f"case_pass_rate {pass_rate:.4f} < {threshold_value:.4f} "
                    f"at score {pass_score:.4f}"
                )
        for branch, threshold in (baseline.get("min_branch_scores") or {}).items():
            branch_score = self.branch_score(str(branch))
            threshold_value = float(threshold)
            if branch_score < threshold_value:
                failures.append(
                    f"{branch} {branch_score:.4f} < {threshold_value:.4f}"
                )
        return failures

    def case_pass_rate(self, min_score: float) -> float:
        if not self.scores:
            return 0.0
        passed = sum(1 for score in self.scores if score.score >= min_score)
        return round(passed / len(self.scores), 4)

    def _score_by_case_id(self, case_id: str) -> CaseScore | None:
        return next((score for score in self.scores if score.case_id == case_id), None)


def score_all(
    cases: list[E2EQualityCase],
    runs: dict[str, E2EQualityRun],
) -> E2EQualityReport:
    return E2EQualityReport(tuple(score_case(case, runs[case.id]) for case in cases))


def score_case(case: E2EQualityCase, run: E2EQualityRun) -> CaseScore:
    metrics = tuple(_metrics(case, run))
    score = round(mean(metric.score for metric in metrics), 4) if metrics else 1.0
    return CaseScore(case_id=case.id, branch=case.branch, score=score, metrics=metrics)


def _metrics(case: E2EQualityCase, run: E2EQualityRun) -> list[MetricScore]:
    metrics: list[MetricScore] = []
    if case.expected_intents:
        metrics.append(_exact("route_intents", run.intents, case.expected_intents))
    if case.expected_workflow_id:
        metrics.append(_exact("workflow_id", run.workflow_id, case.expected_workflow_id))
    if case.expected_steps:
        missing = set(case.expected_steps) - set(run.step_ids)
        metrics.append(MetricScore(
            "workflow_steps",
            1.0 if not missing else 0.0,
            "" if not missing else f"missing={sorted(missing)}",
        ))
    if case.expected_run_statuses:
        metrics.append(_one_of(
            "run_status",
            run.run_status,
            case.expected_run_statuses,
        ))
    if case.min_matches or case.max_matches is not None:
        metrics.append(_range("matches", run.matches_count, case.min_matches, case.max_matches))
    if case.min_citations or case.max_citations is not None:
        metrics.append(_range("citations", run.citations_count, case.min_citations, case.max_citations))
    if case.min_evidence or case.max_evidence is not None:
        metrics.append(_range("evidence", run.evidence_count, case.min_evidence, case.max_evidence))
    if case.max_llm_calls is not None:
        metrics.append(_max("llm_calls", run.llm_call_count, case.max_llm_calls))
    if case.min_verification_score is not None:
        metrics.append(_min_float(
            "verification_score",
            run.verification_score,
            case.min_verification_score,
        ))
    if case.expected_grounding_statuses:
        metrics.append(_one_of(
            "grounding_status",
            run.grounding_status,
            case.expected_grounding_statuses,
        ))
    if case.expected_claim_statuses:
        metrics.append(_intersects(
            "claim_status",
            run.claim_statuses,
            case.expected_claim_statuses,
        ))
    if case.expected_web_tried is not None:
        metrics.append(_exact("web_tried", run.web_tried, case.expected_web_tried))
    for term in case.required_answer_terms:
        metrics.append(_contains("answer_contains", run.answer, term))
    for terms in case.required_answer_term_groups:
        metrics.append(_contains_any("answer_contains_any", run.answer, terms))
    for term in case.forbidden_answer_terms:
        metrics.append(_not_contains("answer_excludes", run.answer, term))
    if case.min_notes:
        metrics.append(_min("notes", run.note_count, case.min_notes))
    if case.expected_task_dependency is not None:
        edge = case.expected_task_dependency
        metrics.append(MetricScore(
            "task_dependency",
            1.0 if edge in run.dependency_edges else 0.0,
            "" if edge in run.dependency_edges else f"missing={edge}",
        ))
    if case.expected_research_statuses:
        metrics.append(_one_of(
            "research_status",
            run.research_status,
            case.expected_research_statuses,
        ))
    if case.min_sources:
        metrics.append(_min("sources", run.source_count, case.min_sources))
    if case.min_events:
        metrics.append(_min("events", run.event_count, case.min_events))
    if case.max_events is not None:
        metrics.append(_max("events", run.event_count, case.max_events))
    if case.min_digest_items:
        metrics.append(_min("digest_items", run.digest_item_count, case.min_digest_items))
    for term in case.required_digest_terms:
        metrics.append(_contains("digest_contains", run.digest_text, term))
    for terms in case.required_digest_term_groups:
        metrics.append(_contains_any("digest_contains_any", run.digest_text, terms))
    for term in case.forbidden_digest_terms:
        metrics.append(_not_contains("digest_excludes", run.digest_text, term))
    if case.expected_event_statuses:
        metrics.append(_intersects(
            "event_status",
            run.event_statuses,
            case.expected_event_statuses,
        ))
    if case.expected_confidence_labels:
        metrics.append(_intersects(
            "confidence_label",
            run.confidence_labels,
            case.expected_confidence_labels,
        ))
    if case.min_web_search_calls:
        metrics.append(_min("web_search_calls", len(run.web_search_queries), case.min_web_search_calls))
    for term in case.required_web_query_terms:
        found = any(term in query for query in run.web_search_queries)
        metrics.append(MetricScore(
            f"web_query_contains:{term}",
            1.0 if found else 0.0,
            "" if found else f"queries={list(run.web_search_queries)}",
        ))
    for terms in case.required_web_query_term_groups:
        found = any(any(term in query for term in terms) for query in run.web_search_queries)
        label = "|".join(terms)
        metrics.append(MetricScore(
            f"web_query_contains_any:{label}",
            1.0 if found else 0.0,
            "" if found else f"terms={list(terms)!r} queries={list(run.web_search_queries)}",
        ))
    if case.require_unique_canonical_urls:
        unique = len(run.canonical_urls) == len(set(run.canonical_urls))
        metrics.append(MetricScore(
            "canonical_url_uniqueness",
            1.0 if unique else 0.0,
            "" if unique else f"canonical_urls={list(run.canonical_urls)}",
        ))
    if case.expected_satisfaction_should_continue is not None:
        metrics.append(_exact(
            "satisfaction_should_continue",
            run.satisfaction_should_continue,
            case.expected_satisfaction_should_continue,
        ))
    if case.expected_gap_types:
        missing_gaps = set(case.expected_gap_types) - set(run.gap_types)
        metrics.append(MetricScore(
            "gap_types",
            1.0 if not missing_gaps else 0.0,
            "" if not missing_gaps else f"missing={sorted(missing_gaps)} actual={list(run.gap_types)}",
        ))
    if case.min_satisfaction_coverage_score is not None:
        metrics.append(_min_float(
            "satisfaction_coverage",
            run.satisfaction_coverage_score,
            case.min_satisfaction_coverage_score,
        ))
    if case.min_satisfaction_confidence_score is not None:
        metrics.append(_min_float(
            "satisfaction_confidence",
            run.satisfaction_confidence_score,
            case.min_satisfaction_confidence_score,
        ))
    if case.max_satisfaction_marginal_gain is not None:
        metrics.append(_max_float(
            "satisfaction_marginal_gain",
            run.satisfaction_marginal_gain,
            case.max_satisfaction_marginal_gain,
        ))
    if case.expected_stop_reason:
        metrics.append(_exact("stop_reason", run.stop_reason, case.expected_stop_reason))
    if case.min_tool_call_traces:
        metrics.append(_min("tool_call_traces", run.tool_call_trace_count, case.min_tool_call_traces))
    if case.min_failed_tool_calls:
        metrics.append(_min("failed_tool_calls", run.failed_tool_call_count, case.min_failed_tool_calls))
    if case.expected_tool_error_kinds:
        missing_errors = set(case.expected_tool_error_kinds) - set(run.tool_error_kinds)
        metrics.append(MetricScore(
            "tool_error_kinds",
            1.0 if not missing_errors else 0.0,
            "" if not missing_errors else f"missing={sorted(missing_errors)} actual={list(run.tool_error_kinds)}",
        ))
    if case.min_stage_timings:
        metrics.append(_min("stage_timings", run.stage_timing_count, case.min_stage_timings))
    return metrics


def _exact(name: str, actual: Any, expected: Any) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual == expected else 0.0,
        "" if actual == expected else f"actual={actual!r} expected={expected!r}",
    )


def _one_of(name: str, actual: str, expected: tuple[str, ...]) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual in expected else 0.0,
        "" if actual in expected else f"actual={actual!r} expected_one_of={expected!r}",
    )


def _intersects(name: str, actual: tuple[str, ...], expected: tuple[str, ...]) -> MetricScore:
    overlap = set(actual) & set(expected)
    return MetricScore(
        name,
        1.0 if overlap else 0.0,
        "" if overlap else f"actual={actual!r} expected_any={expected!r}",
    )


def _min(name: str, actual: int, expected_min: int) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual >= expected_min else 0.0,
        "" if actual >= expected_min else f"actual={actual} min={expected_min}",
    )


def _min_float(name: str, actual: float, expected_min: float) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual >= expected_min else 0.0,
        "" if actual >= expected_min else f"actual={actual:.4f} min={expected_min:.4f}",
    )


def _max(name: str, actual: int, expected_max: int) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual <= expected_max else 0.0,
        "" if actual <= expected_max else f"actual={actual} max={expected_max}",
    )


def _max_float(name: str, actual: float, expected_max: float) -> MetricScore:
    return MetricScore(
        name,
        1.0 if actual <= expected_max else 0.0,
        "" if actual <= expected_max else f"actual={actual:.4f} max={expected_max:.4f}",
    )


def _range(
    name: str,
    actual: int,
    expected_min: int,
    expected_max: int | None,
) -> MetricScore:
    if actual < expected_min:
        return MetricScore(name, 0.0, f"actual={actual} min={expected_min}")
    if expected_max is not None and actual > expected_max:
        return MetricScore(name, 0.0, f"actual={actual} max={expected_max}")
    return MetricScore(name, 1.0)


def _contains(name: str, text: str, term: str) -> MetricScore:
    found = term in text
    return MetricScore(
        f"{name}:{term}",
        1.0 if found else 0.0,
        "" if found else f"term={term!r} text={text[:200]!r}",
    )


def _contains_any(name: str, text: str, terms: tuple[str, ...]) -> MetricScore:
    found = next((term for term in terms if term in text), "")
    label = "|".join(terms)
    return MetricScore(
        f"{name}:{label}",
        1.0 if found else 0.0,
        "" if found else f"terms={list(terms)!r} text={text[:200]!r}",
    )


def _not_contains(name: str, text: str, term: str) -> MetricScore:
    found = term in text
    return MetricScore(
        f"{name}:{term}",
        0.0 if found else 1.0,
        f"forbidden={term!r} text={text[:200]!r}" if found else "",
    )

"""Scoring for Research workflow golden cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import (
    ExpectedResearchEvent,
    ResearchEventQualityEvalCase,
    ResearchEventQualityRunOutput,
)


@dataclass(frozen=True)
class ResearchEventQualityCaseScore:
    case_id: str
    understanding_topic_accuracy: float
    understanding_instruction_coverage: float
    understanding_max_items_accuracy: float
    understanding_policy_accuracy: float
    source_count_exact: float
    min_iterations_met: float
    query_plan_coverage: float
    query_coverage: float
    decision_execution_rate: float
    decision_phase_coverage: float
    gap_coverage: float
    stop_reason_match: float
    satisfaction_recorded: float
    satisfaction_continue_match: float
    satisfaction_coverage_met: float
    satisfaction_confidence_met: float
    satisfaction_marginal_gain_met: float
    satisfaction_gap_coverage: float
    stage_trace_coverage: float
    tool_trace_coverage: float
    source_trace_rate: float
    decision_elapsed_rate: float
    event_frame_rate: float
    event_source_trace_rate: float
    event_recall: float
    event_precision: float
    status_accuracy: float
    source_support_accuracy: float
    personal_relevance_accuracy: float
    digest_coverage: float
    claim_support_rate: float
    claim_evidence_span_rate: float
    claim_support_level_accuracy: float
    primary_source_rate: float
    overall_score: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_event_quality_case(
    case: ResearchEventQualityEvalCase,
    run: ResearchEventQualityRunOutput,
) -> ResearchEventQualityCaseScore:
    matched_events = [
        _match_expected_event(expected, run.events)
        for expected in case.expected_events
    ]
    matched_actual_ids = {
        id(event)
        for event in matched_events
        if event is not None
    }
    understanding_topic_accuracy = (
        1.0
        if not case.expected_understanding_topic
        or run.understood_topic == case.expected_understanding_topic
        else 0.0
    )
    understanding_instruction_coverage = (
        1.0
        if not case.expected_understanding_instruction_terms
        or _contains_terms(
            run.understood_instructions,
            case.expected_understanding_instruction_terms,
        )
        else 0.0
    )
    understanding_max_items_accuracy = (
        1.0
        if case.expected_understanding_max_items is None
        or run.understood_max_items == case.expected_understanding_max_items
        else 0.0
    )
    understanding_policy_accuracy = (
        1.0
        if not case.expected_policy_type
        or run.policy_type == case.expected_policy_type
        else 0.0
    )
    source_count_exact = (
        1.0
        if case.expected_source_count is None
        or run.source_count == case.expected_source_count
        else 0.0
    )
    min_iterations_met = (
        1.0
        if case.min_iterations is None
        or run.iteration_count >= case.min_iterations
        else 0.0
    )
    query_plan_coverage = _text_list_coverage(
        run.query_plan,
        case.expected_query_plan_terms,
    )
    query_coverage = _text_list_coverage(
        run.query_history,
        case.expected_query_terms,
    )
    decision_execution_rate = (
        sum(1 for status in run.decision_statuses if status == "executed")
        / len(run.decision_statuses)
        if run.decision_statuses else 0.0
    )
    decision_phase_coverage = _text_list_coverage(
        run.decision_phases,
        [[phase] for phase in case.expected_decision_phases],
    )
    gap_coverage = (
        sum(1 for gap_type in case.expected_gap_types if gap_type in run.gap_types)
        / len(case.expected_gap_types)
        if case.expected_gap_types else 1.0
    )
    stop_reason_match = (
        1.0
        if not case.expected_stop_reason_terms
        or _contains_terms(run.stop_reason, case.expected_stop_reason_terms)
        else 0.0
    )
    satisfaction_recorded = 1.0 if run.satisfaction_recorded else 0.0
    satisfaction_continue_match = (
        1.0
        if case.expected_satisfaction_should_continue is None
        or run.satisfaction_should_continue == case.expected_satisfaction_should_continue
        else 0.0
    )
    satisfaction_coverage_met = (
        1.0
        if case.min_satisfaction_coverage_score is None
        or run.satisfaction_coverage_score >= case.min_satisfaction_coverage_score
        else 0.0
    )
    satisfaction_confidence_met = (
        1.0
        if case.min_satisfaction_confidence_score is None
        or run.satisfaction_confidence_score >= case.min_satisfaction_confidence_score
        else 0.0
    )
    satisfaction_marginal_gain_met = (
        1.0
        if case.max_satisfaction_marginal_gain is None
        or run.satisfaction_marginal_gain <= case.max_satisfaction_marginal_gain
        else 0.0
    )
    satisfaction_gap_coverage = _list_coverage(
        run.satisfaction_gap_types,
        case.expected_satisfaction_gap_types,
    )
    stage_trace_coverage = _text_list_coverage(
        run.stage_names,
        [[stage] for stage in (
            case.expected_stage_names
            or [
                "next_research_decision",
                "execute_research_decision",
                "cluster_sources",
                "personalize_and_rank",
                "evaluate_research_satisfaction",
            ]
        )],
    )
    tool_trace_coverage = _text_list_coverage(
        run.tool_names,
        [[tool] for tool in (
            case.expected_tool_names
            or ["web_search", "graph_search"]
        )],
    )
    event_recall = (
        sum(1 for event in matched_events if event is not None)
        / len(case.expected_events)
        if case.expected_events else 1.0
    )
    event_precision = (
        len(matched_actual_ids) / len(run.events)
        if run.events else (1.0 if not case.expected_events else 0.0)
    )
    status_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        lambda expected, event: (
            expected.expected_status is None
            or getattr(event, "status", None) == expected.expected_status
        ),
    )
    source_support_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        _source_support_matches,
    )
    personal_relevance_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        _personal_relevance_matches,
    )
    digest_coverage = _digest_coverage(
        run.digest_titles,
        case.expected_digest_title_terms,
    )
    claim_support_rate = _claim_support_rate(run.digest_items)
    claim_evidence_span_rate = _claim_evidence_span_rate(run.digest_items)
    claim_support_level_accuracy = _claim_support_level_accuracy(
        run.claim_support_levels,
        case.expected_claim_support_levels,
    )
    primary_source_rate = (
        sum(1 for event in run.events if _has_primary_source(event)) / len(run.events)
        if run.events else 1.0
    )
    overall_score = round(sum([
        understanding_topic_accuracy,
        understanding_instruction_coverage,
        understanding_max_items_accuracy,
        understanding_policy_accuracy,
        source_count_exact,
        min_iterations_met,
        query_plan_coverage,
        query_coverage,
        decision_execution_rate,
        decision_phase_coverage,
        gap_coverage,
        stop_reason_match,
        satisfaction_recorded,
        satisfaction_continue_match,
        satisfaction_coverage_met,
        satisfaction_confidence_met,
        satisfaction_marginal_gain_met,
        satisfaction_gap_coverage,
        stage_trace_coverage,
        tool_trace_coverage,
        run.source_trace_rate,
        run.decision_elapsed_rate,
        run.event_frame_rate,
        run.event_source_trace_rate,
        event_recall,
        event_precision,
        status_accuracy,
        source_support_accuracy,
        personal_relevance_accuracy,
        digest_coverage,
        claim_support_rate,
        claim_evidence_span_rate,
        claim_support_level_accuracy,
    ]) / 33, 4)
    return ResearchEventQualityCaseScore(
        case_id=case.id,
        understanding_topic_accuracy=understanding_topic_accuracy,
        understanding_instruction_coverage=understanding_instruction_coverage,
        understanding_max_items_accuracy=understanding_max_items_accuracy,
        understanding_policy_accuracy=understanding_policy_accuracy,
        source_count_exact=source_count_exact,
        min_iterations_met=min_iterations_met,
        query_plan_coverage=round(query_plan_coverage, 4),
        query_coverage=round(query_coverage, 4),
        decision_execution_rate=round(decision_execution_rate, 4),
        decision_phase_coverage=round(decision_phase_coverage, 4),
        gap_coverage=round(gap_coverage, 4),
        stop_reason_match=stop_reason_match,
        satisfaction_recorded=satisfaction_recorded,
        satisfaction_continue_match=satisfaction_continue_match,
        satisfaction_coverage_met=satisfaction_coverage_met,
        satisfaction_confidence_met=satisfaction_confidence_met,
        satisfaction_marginal_gain_met=satisfaction_marginal_gain_met,
        satisfaction_gap_coverage=round(satisfaction_gap_coverage, 4),
        stage_trace_coverage=round(stage_trace_coverage, 4),
        tool_trace_coverage=round(tool_trace_coverage, 4),
        source_trace_rate=round(run.source_trace_rate, 4),
        decision_elapsed_rate=round(run.decision_elapsed_rate, 4),
        event_frame_rate=round(run.event_frame_rate, 4),
        event_source_trace_rate=round(run.event_source_trace_rate, 4),
        event_recall=round(event_recall, 4),
        event_precision=round(event_precision, 4),
        status_accuracy=round(status_accuracy, 4),
        source_support_accuracy=round(source_support_accuracy, 4),
        personal_relevance_accuracy=round(personal_relevance_accuracy, 4),
        digest_coverage=round(digest_coverage, 4),
        claim_support_rate=round(claim_support_rate, 4),
        claim_evidence_span_rate=round(claim_evidence_span_rate, 4),
        claim_support_level_accuracy=round(claim_support_level_accuracy, 4),
        primary_source_rate=round(primary_source_rate, 4),
        overall_score=overall_score,
    )


_EVENT_METRIC_NAMES = (
    "understanding_topic_accuracy",
    "understanding_instruction_coverage",
    "understanding_max_items_accuracy",
    "understanding_policy_accuracy",
    "source_count_exact",
    "min_iterations_met",
    "query_plan_coverage",
    "query_coverage",
    "decision_execution_rate",
    "decision_phase_coverage",
    "gap_coverage",
    "stop_reason_match",
    "satisfaction_recorded",
    "satisfaction_continue_match",
    "satisfaction_coverage_met",
    "satisfaction_confidence_met",
    "satisfaction_marginal_gain_met",
    "satisfaction_gap_coverage",
    "stage_trace_coverage",
    "tool_trace_coverage",
    "source_trace_rate",
    "decision_elapsed_rate",
    "event_frame_rate",
    "event_source_trace_rate",
    "event_recall",
    "event_precision",
    "status_accuracy",
    "source_support_accuracy",
    "personal_relevance_accuracy",
    "digest_coverage",
    "claim_support_rate",
    "claim_evidence_span_rate",
    "claim_support_level_accuracy",
    "primary_source_rate",
    "overall_score",
)


@dataclass(frozen=True)
class ResearchEventQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ResearchEventQualityCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [score.as_dict() for score in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Research Event Quality Report ({self.num_cases} cases)"]
        for name in _EVENT_METRIC_NAMES:
            lines.append(f"  {name:<30} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate_event_quality(
    scores: list[ResearchEventQualityCaseScore],
) -> ResearchEventQualityReport:
    if not scores:
        return ResearchEventQualityReport(
            num_cases=0,
            means=dict.fromkeys(_EVENT_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _EVENT_METRIC_NAMES
    }
    return ResearchEventQualityReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def score_event_quality_all(
    cases: list[ResearchEventQualityEvalCase],
    runs: dict[str, ResearchEventQualityRunOutput],
) -> ResearchEventQualityReport:
    scores = [
        score_event_quality_case(case, runs[case.id])
        for case in cases
        if case.id in runs
    ]
    return aggregate_event_quality(scores)


def _match_expected_event(expected: ExpectedResearchEvent, events: list[object]):
    for event in events:
        if _contains_terms(getattr(event, "title", ""), expected.title_terms):
            return event
    return None


def _contains_terms(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    return all(term.lower() in normalized for term in terms)


def _expected_event_average(expected_events, matched_events, predicate) -> float:
    if not expected_events:
        return 1.0
    scores: list[float] = []
    for expected, event in zip(expected_events, matched_events, strict=False):
        if event is None:
            scores.append(0.0)
        else:
            scores.append(1.0 if predicate(expected, event) else 0.0)
    return sum(scores) / len(expected_events)


def _source_support_matches(expected: ExpectedResearchEvent, event) -> bool:
    sources = list(getattr(event, "sources", []) or [])
    if len(sources) < expected.min_sources:
        return False
    return not expected.requires_primary_source or _has_primary_source(event)


def _personal_relevance_matches(expected: ExpectedResearchEvent, event) -> bool:
    if expected.min_personal_relevance is None:
        return True
    relevance = getattr(event, "personal_relevance", None)
    score = getattr(relevance, "score", 0.0)
    return score >= expected.min_personal_relevance


def _claim_support_rate(digest_items: list[object]) -> float:
    claims = _digest_claims(digest_items)
    if not claims:
        return 1.0 if not digest_items else 0.0
    supported = {
        "supported",
        "partially_supported",
    }
    return sum(
        1 for claim in claims
        if getattr(claim, "support_level", "") in supported
    ) / len(claims)


def _claim_evidence_span_rate(digest_items: list[object]) -> float:
    claims = [
        claim for claim in _digest_claims(digest_items)
        if getattr(claim, "support_level", "") in {"supported", "partially_supported"}
    ]
    if not claims:
        return 1.0 if not digest_items else 0.0
    return sum(
        1 for claim in claims
        if getattr(claim, "evidence_spans", None)
    ) / len(claims)


def _digest_claims(digest_items: list[object]) -> list[object]:
    claims: list[object] = []
    for item in digest_items:
        claims.extend(list(getattr(item, "claims", []) or []))
    return claims


def _has_primary_source(event) -> bool:
    primary_source_types = {
        "official",
        "docs",
        "github",
        "paper",
        "filing",
        "investor_relations",
        "transcript",
    }
    return any(
        getattr(source, "source_type", "") in primary_source_types
        for source in (getattr(event, "sources", []) or [])
    )


def _digest_coverage(digest_titles: list[str], expected_terms: list[list[str]]) -> float:
    if not expected_terms:
        return 1.0
    matched = sum(
        1
        for terms in expected_terms
        if any(_contains_terms(title, terms) for title in digest_titles)
    )
    return matched / len(expected_terms)


def _list_coverage(actual: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    lowered = {item.lower() for item in actual}
    return sum(1 for item in expected if item.lower() in lowered) / len(expected)


def _claim_support_level_accuracy(
    actual: list[str],
    expected: list[str],
) -> float:
    if not expected:
        return 1.0
    if len(actual) != len(expected):
        return 0.0
    return 1.0 if actual == expected else 0.0


def _text_list_coverage(texts: list[str], expected_terms: list[list[str]]) -> float:
    if not expected_terms:
        return 1.0
    matched = sum(
        1
        for terms in expected_terms
        if any(_contains_terms(text, terms) for text in texts)
    )
    return matched / len(expected_terms)

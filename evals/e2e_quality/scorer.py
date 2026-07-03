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
    expected_claim_states: tuple[str, ...] = ()
    forbidden_claim_states: tuple[str, ...] = ()
    expected_admission_results: tuple[str, ...] = ()
    expected_relation_types: tuple[str, ...] = ()
    forbidden_relation_types: tuple[str, ...] = ()
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
    min_evidence_blocks: int = 0
    min_evidence_spans: int = 0
    min_grounding_runs: int = 0
    min_claim_admission_decisions: int = 0
    min_knowledge_items: int = 0
    min_decisions: int = 0
    min_knowledge_relations: int = 0
    min_user_claims: int = 0
    min_research_events: int = 0
    min_review_items: int = 0
    min_knowledge_gaps: int = 0
    min_graph_projections: int = 0
    min_table_evidence_blocks: int = 0
    min_deleted_claims: int = 0
    min_replay_diff_count: int = 0
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
    require_citation_resolves_to_artifact: bool = False
    expected_evidence_coverages: tuple[str, ...] = ()
    min_missing_sections: int = 0
    max_projection_job_failed_count: int | None = None
    max_partial_failure_count: int | None = None
    max_answer_claim_saved_count: int | None = None
    max_active_claim_count_delta: int | None = None
    max_assistant_inference_active_count: int | None = None
    max_pending_decision_count: int | None = None
    require_graph_projection_backlinks: bool = False
    min_claim_quality_passed_count: int = 0
    max_claim_without_evidence_ref_count: int | None = None
    min_coverage_manifest_omitted_count: int = 0
    max_review_invalid_claim_count: int | None = None
    max_projection_eligibility_violation_count: int | None = None
    required_semantic_component_terms: tuple[str, ...] = ()
    forbidden_grounding_verifiers: tuple[str, ...] = ()


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
    evidence_block_count: int = 0
    evidence_span_count: int = 0
    grounding_run_count: int = 0
    claim_admission_decision_count: int = 0
    knowledge_item_count: int = 0
    decision_count: int = 0
    pending_decision_count: int = 0
    knowledge_relation_count: int = 0
    user_claim_count: int = 0
    research_event_count: int = 0
    review_item_count: int = 0
    knowledge_gap_count: int = 0
    graph_projection_count: int = 0
    llm_call_count: int = 0
    verification_score: float = 0.0
    grounding_status: str = ""
    claim_statuses: tuple[str, ...] = ()
    claim_states: tuple[str, ...] = ()
    admission_results: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    table_evidence_block_count: int = 0
    deleted_claim_count: int = 0
    replay_diff_count: int = 0
    citation_evidence_span_ids: tuple[str, ...] = ()
    citation_evidence_block_ids: tuple[str, ...] = ()
    citation_artifact_ids: tuple[str, ...] = ()
    evidence_coverage: str = ""
    missing_section_count: int = 0
    projection_job_failed_count: int = 0
    partial_failure_count: int = 0
    answer_claim_saved_count: int = 0
    active_claim_count_delta: int = 0
    assistant_inference_active_count: int = 0
    graph_projection_backlink_ok: bool = False
    claim_quality_passed_count: int = 0
    claim_without_evidence_ref_count: int = 0
    coverage_manifest_omitted_count: int = 0
    review_invalid_claim_count: int = 0
    projection_eligibility_violation_count: int = 0
    semantic_component_names: tuple[str, ...] = ()
    grounding_verifiers: tuple[str, ...] = ()
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
    if case.min_evidence_blocks:
        metrics.append(_min("evidence_blocks", run.evidence_block_count, case.min_evidence_blocks))
    if case.min_evidence_spans:
        metrics.append(_min("evidence_spans", run.evidence_span_count, case.min_evidence_spans))
    if case.min_grounding_runs:
        metrics.append(_min("grounding_runs", run.grounding_run_count, case.min_grounding_runs))
    if case.min_claim_admission_decisions:
        metrics.append(_min(
            "claim_admission_decisions",
            run.claim_admission_decision_count,
            case.min_claim_admission_decisions,
        ))
    if case.min_knowledge_items:
        metrics.append(_min("knowledge_items", run.knowledge_item_count, case.min_knowledge_items))
    if case.min_decisions:
        metrics.append(_min("decisions", run.decision_count, case.min_decisions))
    if case.min_knowledge_relations:
        metrics.append(_min("knowledge_relations", run.knowledge_relation_count, case.min_knowledge_relations))
    if case.min_user_claims:
        metrics.append(_min("user_claims", run.user_claim_count, case.min_user_claims))
    if case.min_research_events:
        metrics.append(_min("research_events", run.research_event_count, case.min_research_events))
    if case.min_review_items:
        metrics.append(_min("review_items", run.review_item_count, case.min_review_items))
    if case.min_knowledge_gaps:
        metrics.append(_min("knowledge_gaps", run.knowledge_gap_count, case.min_knowledge_gaps))
    if case.min_graph_projections:
        metrics.append(_min("graph_projections", run.graph_projection_count, case.min_graph_projections))
    if case.min_table_evidence_blocks:
        metrics.append(_min("table_evidence_blocks", run.table_evidence_block_count, case.min_table_evidence_blocks))
    if case.min_deleted_claims:
        metrics.append(_min("deleted_claims", run.deleted_claim_count, case.min_deleted_claims))
    if case.min_replay_diff_count:
        metrics.append(_min("replay_diff_count", run.replay_diff_count, case.min_replay_diff_count))
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
    if case.expected_claim_states:
        metrics.append(_intersects(
            "claim_state",
            run.claim_states,
            case.expected_claim_states,
        ))
    for state in case.forbidden_claim_states:
        forbidden = state in run.claim_states
        metrics.append(MetricScore(
            f"claim_state_forbidden:{state}",
            0.0 if forbidden else 1.0,
            f"actual={run.claim_states!r}" if forbidden else "",
        ))
    if case.expected_admission_results:
        metrics.append(_intersects(
            "admission_result",
            run.admission_results,
            case.expected_admission_results,
        ))
    if case.expected_relation_types:
        metrics.append(_intersects(
            "relation_type",
            run.relation_types,
            case.expected_relation_types,
        ))
    for relation_type in case.forbidden_relation_types:
        forbidden = relation_type in run.relation_types
        metrics.append(MetricScore(
            f"relation_type_forbidden:{relation_type}",
            0.0 if forbidden else 1.0,
            f"actual={run.relation_types!r}" if forbidden else "",
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
    if case.require_citation_resolves_to_artifact:
        resolves = (
            bool(run.citation_evidence_span_ids)
            and len(run.citation_evidence_span_ids) == len(run.citation_evidence_block_ids)
            and len(run.citation_evidence_span_ids) == len(run.citation_artifact_ids)
            and all(run.citation_evidence_span_ids)
            and all(run.citation_evidence_block_ids)
            and all(run.citation_artifact_ids)
        )
        metrics.append(MetricScore(
            "citation_resolves_to_artifact",
            1.0 if resolves else 0.0,
            "" if resolves else (
                f"spans={run.citation_evidence_span_ids!r} "
                f"blocks={run.citation_evidence_block_ids!r} "
                f"artifacts={run.citation_artifact_ids!r}"
            ),
        ))
    if case.expected_evidence_coverages:
        metrics.append(_one_of(
            "evidence_coverage",
            run.evidence_coverage,
            case.expected_evidence_coverages,
        ))
    if case.min_missing_sections:
        metrics.append(_min("missing_sections", run.missing_section_count, case.min_missing_sections))
    if case.max_projection_job_failed_count is not None:
        metrics.append(_max(
            "projection_job_failed_count",
            run.projection_job_failed_count,
            case.max_projection_job_failed_count,
        ))
    if case.max_partial_failure_count is not None:
        metrics.append(_max(
            "partial_failure_count",
            run.partial_failure_count,
            case.max_partial_failure_count,
        ))
    if case.max_answer_claim_saved_count is not None:
        metrics.append(_max(
            "answer_claim_saved_count",
            run.answer_claim_saved_count,
            case.max_answer_claim_saved_count,
        ))
    if case.max_active_claim_count_delta is not None:
        metrics.append(_max(
            "active_claim_count_delta",
            run.active_claim_count_delta,
            case.max_active_claim_count_delta,
        ))
    if case.max_assistant_inference_active_count is not None:
        metrics.append(_max(
            "assistant_inference_active_count",
            run.assistant_inference_active_count,
            case.max_assistant_inference_active_count,
        ))
    if case.max_pending_decision_count is not None:
        metrics.append(_max(
            "pending_decision_count",
            run.pending_decision_count,
            case.max_pending_decision_count,
        ))
    if case.require_graph_projection_backlinks:
        metrics.append(_exact(
            "graph_projection_backlink_ok",
            run.graph_projection_backlink_ok,
            True,
        ))
    if case.min_claim_quality_passed_count:
        metrics.append(_min("claim_quality_passed_count", run.claim_quality_passed_count, case.min_claim_quality_passed_count))
    if case.max_claim_without_evidence_ref_count is not None:
        metrics.append(_max("claim_without_evidence_ref_count", run.claim_without_evidence_ref_count, case.max_claim_without_evidence_ref_count))
    if case.min_coverage_manifest_omitted_count:
        metrics.append(_min("coverage_manifest_omitted_count", run.coverage_manifest_omitted_count, case.min_coverage_manifest_omitted_count))
    if case.max_review_invalid_claim_count is not None:
        metrics.append(_max("review_invalid_claim_count", run.review_invalid_claim_count, case.max_review_invalid_claim_count))
    if case.max_projection_eligibility_violation_count is not None:
        metrics.append(_max(
            "projection_eligibility_violation_count",
            run.projection_eligibility_violation_count,
            case.max_projection_eligibility_violation_count,
        ))
    for term in case.required_semantic_component_terms:
        has_component = any(term.lower() in component.lower() for component in run.semantic_component_names)
        metrics.append(MetricScore(
            f"semantic_component_contains:{term}",
            1.0 if has_component else 0.0,
            "" if has_component else f"components={run.semantic_component_names!r}",
        ))
    for verifier in case.forbidden_grounding_verifiers:
        forbidden = verifier in run.grounding_verifiers
        metrics.append(MetricScore(
            f"grounding_verifier_forbidden:{verifier}",
            0.0 if forbidden else 1.0,
            f"grounding_verifiers={run.grounding_verifiers!r}" if forbidden else "",
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

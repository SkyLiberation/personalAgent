from __future__ import annotations

from evals.e2e_quality.scorer import (
    CaseScore,
    E2EQualityCase,
    E2EQualityReport,
    E2EQualityRun,
    MetricScore,
    score_case,
)
from evals.e2e_quality.selection import (
    baseline_should_be_enforced,
    select_case_ids,
    split_selector,
)


def test_required_term_groups_accept_equivalent_phrasing():
    case = E2EQualityCase(
        id="E2E-ASK-005",
        branch="ask",
        description="compound capture then ask",
        required_answer_terms=("蓝绿发布",),
        required_answer_term_groups=(("一半流量", "50%流量", "半数流量"),),
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        answer="蓝绿发布时每组各承载50%流量。",
    )

    result = score_case(case, run)

    assert result.score == 1.0


def test_expected_run_statuses_accept_hitl_waiting_confirmation():
    case = E2EQualityCase(
        id="E2E-WF-DELETE-001",
        branch="workflow",
        description="delete pauses for confirmation",
        expected_run_statuses=("waiting_confirmation",),
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        run_status="waiting_confirmation",
    )

    result = score_case(case, run)

    assert result.score == 1.0


def test_live_thresholds_allow_soft_cases_but_keep_critical_cases_strict():
    report = E2EQualityReport((
        CaseScore("E2E-ASK-002", "ask", 1.0, (MetricScore("ok", 1.0),)),
        CaseScore("E2E-RES-001", "research", 0.2, (MetricScore("drift", 0.2),)),
    ))
    baseline = {
        "min_overall": 0.50,
        "min_case_score": 0.0,
        "case_pass_score": 1.0,
        "min_case_pass_rate": 0.50,
        "critical_case_min_score": 1.0,
        "critical_cases": ["E2E-ASK-002"],
        "min_branch_scores": {"ask": 1.0, "research": 0.2},
    }

    assert report.check_thresholds(baseline) == []


def test_live_thresholds_fail_when_critical_case_regresses():
    report = E2EQualityReport((
        CaseScore("E2E-ASK-002", "ask", 0.9, (MetricScore("route", 0.9),)),
        CaseScore("E2E-RES-001", "research", 0.9, (MetricScore("ok", 0.9),)),
    ))
    baseline = {
        "min_overall": 0.70,
        "min_case_score": 0.30,
        "critical_case_min_score": 1.0,
        "critical_cases": ["E2E-ASK-002"],
    }

    failures = report.check_thresholds(baseline)

    assert failures == ["critical E2E-ASK-002 0.9000 < 1.0000"]


def test_split_selector_accepts_commas_semicolons_and_spaces():
    assert split_selector("A,B; C\nD") == ("A", "B", "C", "D")


def test_select_case_ids_filters_by_case_list_and_branch():
    cases = [
        E2EQualityCase(id="E2E-ASK-001", branch="ask", description="ask"),
        E2EQualityCase(id="E2E-ART-001", branch="artifact", description="artifact"),
        E2EQualityCase(id="E2E-RES-001", branch="research", description="research"),
    ]

    selected = select_case_ids(
        cases,
        ("E2E-ASK-001", "E2E-ART-001", "E2E-RES-001"),
        case_selector="E2E-ASK-001,E2E-RES-001",
        branch_selector="research",
    )

    assert selected == ("E2E-RES-001",)


def test_select_case_ids_rejects_unknown_case():
    cases = [E2EQualityCase(id="E2E-ASK-001", branch="ask", description="ask")]

    try:
        select_case_ids(cases, ("E2E-ASK-001",), case_selector="missing")
    except ValueError as exc:
        assert "Unknown e2e_quality case" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_selected_subset_disables_baseline_by_default():
    assert baseline_should_be_enforced(case_selector="", branch_selector="") is True
    assert baseline_should_be_enforced(case_selector="E2E-ASK-001", branch_selector="") is False
    assert baseline_should_be_enforced(
        case_selector="E2E-ASK-001",
        branch_selector="",
        enforce_value="true",
    ) is True


def test_lifecycle_case_scores_p0_hard_assertions():
    case = E2EQualityCase(
        id="E2E-LIFE-003",
        branch="life",
        description="workspace P0 evidence-grounded ask",
        min_evidence_blocks=1,
        min_evidence_spans=1,
        min_grounding_runs=1,
        min_claim_admission_decisions=1,
        expected_claim_states=("active",),
        expected_admission_results=("allow_active",),
        require_citation_resolves_to_artifact=True,
        max_answer_claim_saved_count=0,
        max_active_claim_count_delta=0,
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        evidence_block_count=1,
        evidence_span_count=2,
        grounding_run_count=1,
        claim_admission_decision_count=1,
        claim_states=("active",),
        admission_results=("allow_active",),
        citation_evidence_span_ids=("span-1",),
        citation_evidence_block_ids=("block-1",),
        citation_artifact_ids=("artifact-1",),
        answer_claim_saved_count=0,
        active_claim_count_delta=0,
    )

    result = score_case(case, run)

    assert result.score == 1.0


def test_lifecycle_case_fails_unresolved_citation_and_accidental_persistence():
    case = E2EQualityCase(
        id="E2E-LIFE-003",
        branch="life",
        description="workspace P0 evidence-grounded ask",
        require_citation_resolves_to_artifact=True,
        max_answer_claim_saved_count=0,
        max_active_claim_count_delta=0,
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        citation_evidence_span_ids=("span-1",),
        citation_evidence_block_ids=(),
        citation_artifact_ids=(),
        answer_claim_saved_count=1,
        active_claim_count_delta=1,
    )

    result = score_case(case, run)

    failed_names = {metric.name for metric in result.metrics if metric.score == 0.0}
    assert "citation_resolves_to_artifact" in failed_names
    assert "answer_claim_saved_count" in failed_names
    assert "active_claim_count_delta" in failed_names


def test_lifecycle_case_scores_relation_and_assistant_inference_guards():
    case = E2EQualityCase(
        id="E2E-LIFE-006",
        branch="life",
        description="workspace potential conflict lifecycle",
        min_knowledge_relations=1,
        expected_relation_types=("potential_conflict",),
        expected_claim_states=("active",),
        max_assistant_inference_active_count=0,
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        knowledge_relation_count=1,
        relation_types=("potential_conflict",),
        claim_states=("active", "active"),
        assistant_inference_active_count=0,
    )

    result = score_case(case, run)

    assert result.score == 1.0


def test_lifecycle_case_scores_p4_p5_p6_counts_and_graph_backlinks():
    case = E2EQualityCase(
        id="E2E-LIFE-010",
        branch="life",
        description="workspace p4 p5 p6",
        min_research_events=1,
        min_review_items=1,
        min_knowledge_gaps=1,
        min_graph_projections=1,
        require_graph_projection_backlinks=True,
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        research_event_count=1,
        review_item_count=1,
        knowledge_gap_count=1,
        graph_projection_count=1,
        graph_projection_backlink_ok=True,
    )

    result = score_case(case, run)

    assert result.score == 1.0


def test_lifecycle_case_scores_knowledge_items_and_decisions():
    case = E2EQualityCase(
        id="E2E-LIFE-007",
        branch="life",
        description="decision policy does not overload HITL",
        min_knowledge_items=1,
        min_decisions=1,
        max_pending_decision_count=1,
    )
    run = E2EQualityRun(
        case_id=case.id,
        branch=case.branch,
        knowledge_item_count=1,
        decision_count=1,
        pending_decision_count=1,
    )

    result = score_case(case, run)

    assert result.score == 1.0

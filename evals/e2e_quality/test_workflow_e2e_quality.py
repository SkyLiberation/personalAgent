from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
import traceback

import pytest

from personal_agent.application.research import ResearchBudget
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.kernel.models import ArtifactRef, EntryInput, ReviewCard, local_now
from personal_agent.orchestration.service import AgentService
from tests.conftest import POSTGRES_URL

from .scorer import E2EQualityCase, E2EQualityRun, score_all
from .selection import baseline_should_be_enforced, select_case_ids

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


CASES = [
    E2EQualityCase(
        id="E2E-ASK-001",
        branch="ask",
        description="seeded note ask carries evidence to EntryResult",
        expected_intents=("ask",),
        expected_workflow_id="ask",
        min_matches=1,
        min_citations=1,
        min_evidence=1,
        min_verification_score=0.35,
        expected_grounding_statuses=("supported", "weak_evidence"),
        required_answer_terms=("服务降级", "核心链路"),
        forbidden_answer_terms=("天气", "无法确定"),
    ),
    E2EQualityCase(
        id="E2E-ASK-002",
        branch="ask",
        description="private no-evidence ask returns conservative answer without web fallback",
        expected_intents=("ask",),
        min_matches=0,
        min_citations=0,
        min_evidence=0,
        max_matches=0,
        max_citations=0,
        max_evidence=0,
        max_llm_calls=0,
        required_answer_terms=("无法", "足够依据"),
    ),
    E2EQualityCase(
        id="E2E-ASK-003",
        branch="ask",
        description="multi-note ask keeps multiple matches, citations and evidence items",
        expected_intents=("ask",),
        min_matches=2,
        min_citations=2,
        min_evidence=2,
        min_verification_score=0.55,
        expected_grounding_statuses=("supported",),
        required_answer_terms=("pytest", "unittest", "nose2"),
    ),
    E2EQualityCase(
        id="E2E-ASK-005",
        branch="ask",
        description="compound capture then ask uses the note written in the same run",
        expected_intents=("capture_text", "ask"),
        min_matches=1,
        min_notes=1,
        expected_task_dependency=("goal_2", "goal_1"),
        required_answer_terms=("蓝绿发布",),
        required_answer_term_groups=(("一半流量", "50%流量", "半数流量", "半量流量"),),
    ),
    E2EQualityCase(
        id="E2E-ASK-006",
        branch="ask",
        description="source filters constrain ask retrieval to the requested file source",
        min_matches=1,
        min_citations=1,
        min_evidence=1,
        required_answer_terms=("deploy.md",),
        required_answer_term_groups=(("一半流量", "50%流量", "半数流量", "半量流量"),),
        forbidden_answer_terms=("example.com",),
    ),
    E2EQualityCase(
        id="E2E-ASK-SEM-002",
        branch="ask",
        description="conflicting evidence produces an uncertainty-aware answer",
        expected_intents=("ask",),
        min_matches=2,
        min_citations=2,
        min_evidence=2,
        required_answer_terms=("默认开启", "默认关闭"),
        required_answer_term_groups=(
            ("冲突", "相反", "矛盾"),
            (
                "不能给确定结论",
                "不能给出确定结论",
                "无法给出统一默认值",
                "无法给出单一默认值",
                "不能一概而论",
                "无法一概而论",
            ),
        ),
        forbidden_answer_terms=("一定默认开启", "一定默认关闭"),
    ),
    E2EQualityCase(
        id="E2E-ASK-WEB-002",
        branch="ask",
        description="no local evidence triggers bounded web fallback instead of research",
        expected_intents=("ask",),
        expected_web_tried=True,
        min_citations=1,
        min_evidence=1,
        required_answer_terms=("Kappa API",),
        required_answer_term_groups=(("rate limit", "速率限制", "限流", "配额"),),
        forbidden_answer_terms=("research_once", "调研"),
    ),
    E2EQualityCase(
        id="E2E-ART-001",
        branch="artifact",
        description="text artifact analysis answers from uploaded file context",
        expected_intents=("analyze_artifact",),
        expected_workflow_id="analyze_artifact",
        expected_steps=("artifact-inspect", "artifact-compose"),
        required_answer_terms=("蓝绿发布", "一半流量"),
        forbidden_answer_terms=("已保存", "写入知识库"),
    ),
    E2EQualityCase(
        id="E2E-ART-002",
        branch="artifact",
        description="image artifact without vision model degrades with metadata-only context",
        expected_intents=("analyze_artifact",),
        expected_workflow_id="analyze_artifact",
        expected_steps=("artifact-inspect", "artifact-compose"),
        required_answer_terms=("chart.png",),
        forbidden_answer_terms=("蓝绿发布", "已保存"),
    ),
    E2EQualityCase(
        id="E2E-WF-DIRECT-001",
        branch="workflow",
        description="simple conversational request stays on direct_answer workflow",
        expected_intents=("direct_answer",),
        expected_workflow_id="direct_answer",
        expected_steps=("direct-compose",),
        expected_run_statuses=("completed",),
        required_answer_term_groups=(("你好", "您好", "可以", "帮你"),),
    ),
    E2EQualityCase(
        id="E2E-WF-CAPTURE-001",
        branch="workflow",
        description="explicit text memory request routes to capture_text and writes a note",
        expected_intents=("capture_text",),
        expected_workflow_id="capture_text",
        expected_steps=("cap-structure",),
        expected_run_statuses=("completed",),
        min_notes=1,
        required_answer_term_groups=(("已保存", "已记录", "已收进知识库", "记下", "保存"),),
    ),
    E2EQualityCase(
        id="E2E-WF-CAPTURE-FILE-001",
        branch="workflow",
        description="explicit attachment save routes to capture_file and persists interpreted content",
        expected_intents=("capture_file",),
        expected_workflow_id="capture_file",
        expected_steps=("cap-file-inspect", "cap-file-store"),
        expected_run_statuses=("completed",),
        min_notes=1,
        required_answer_term_groups=(("已保存", "已记录", "已收进知识库", "保存", "附件"),),
    ),
    E2EQualityCase(
        id="E2E-WF-SUM-001",
        branch="workflow",
        description="explicit thread summary loads conversation context and summarizes it",
        expected_intents=("summarize_thread",),
        expected_workflow_id="summarize_thread",
        expected_steps=("sum-compose",),
        expected_run_statuses=("completed",),
        required_answer_terms=("Orion",),
        required_answer_term_groups=(("缓存", "cache"),),
    ),
    E2EQualityCase(
        id="E2E-WF-SOLIDIFY-001",
        branch="workflow",
        description="explicit solidify request turns prior conversation into a persisted note",
        expected_intents=("solidify_conversation",),
        expected_workflow_id="solidify_conversation",
        expected_steps=("sol-1", "sol-2"),
        expected_run_statuses=("completed",),
        min_notes=1,
        required_answer_terms=("DNS",),
    ),
    E2EQualityCase(
        id="E2E-WF-REVIEW-001",
        branch="workflow",
        description="review digest request uses due review cards and recent notes",
        expected_intents=("review_digest",),
        expected_workflow_id="review_digest",
        expected_steps=("digest-generate", "digest-compose"),
        expected_run_statuses=("completed",),
        required_answer_term_groups=(("知识简报", "待复习", "复习"),),
    ),
    E2EQualityCase(
        id="E2E-WF-CONSOLIDATE-001",
        branch="workflow",
        description="topic consolidation selects related notes and creates a summary note",
        expected_intents=("consolidate_knowledge",),
        expected_workflow_id="consolidate_knowledge",
        expected_steps=("consolidate-run", "consolidate-compose"),
        expected_run_statuses=("completed",),
        min_notes=3,
        required_answer_terms=("Redis",),
    ),
    E2EQualityCase(
        id="E2E-WF-GAP-001",
        branch="workflow",
        description="knowledge gap inspection reports weak or conflicting areas",
        expected_intents=("inspect_knowledge_gaps",),
        expected_workflow_id="inspect_knowledge_gaps",
        expected_steps=("gap-inspect", "gap-compose"),
        expected_run_statuses=("completed",),
        required_answer_term_groups=(("缺口", "冲突", "薄弱", "孤岛"),),
    ),
    E2EQualityCase(
        id="E2E-WF-INSPECT-001",
        branch="workflow",
        description="workflow inspection can explain a previous run by run_id",
        expected_intents=("inspect_workflow",),
        expected_workflow_id="inspect_workflow",
        expected_steps=("workflow-inspect-decide", "workflow-inspect-compose"),
        expected_run_statuses=("completed",),
        required_answer_term_groups=(("workflow", "run", "步骤", "执行"),),
    ),
    E2EQualityCase(
        id="E2E-WF-DELETE-001",
        branch="workflow",
        description="delete_knowledge resolves candidates and pauses for human confirmation",
        expected_intents=("delete_knowledge",),
        expected_workflow_id="delete_knowledge",
        expected_steps=("del-1", "del-2", "del-3"),
        expected_run_statuses=("waiting_confirmation",),
        required_answer_term_groups=(("确认", "待确认", "删除"),),
    ),
    E2EQualityCase(
        id="E2E-WF-COMPLEX-001",
        branch="workflow",
        description="complex request captures a new fact and answers from same-run memory without research",
        expected_intents=("capture_text", "ask"),
        min_matches=1,
        min_notes=1,
        expected_task_dependency=("goal_2", "goal_1"),
        required_answer_terms=("Gamma",),
        required_answer_term_groups=(("周五", "星期五"), ("20:00", "晚上8点", "晚上 8 点")),
        forbidden_answer_terms=("research_once", "调研"),
    ),
    E2EQualityCase(
        id="E2E-RES-001",
        branch="research",
        description="research workflow produces sourced digest through all research steps",
        expected_research_statuses=("completed", "completed_with_limitations", "completed_verified"),
        expected_workflow_id="research_once",
        expected_steps=(
            "research-prepare",
            "research-initialize",
            "research-loop",
            "research-synthesize",
            "research-verify",
            "research-compose",
        ),
        expected_event_statuses=("verified", "reported"),
        expected_confidence_labels=("已验证", "多方报道"),
        min_sources=2,
        min_events=1,
        min_digest_items=1,
        required_digest_terms=("Agent Runtime SDK", "workflow runtime"),
        expected_satisfaction_should_continue=False,
        min_satisfaction_coverage_score=1.0,
    ),
    E2EQualityCase(
        id="E2E-RES-002",
        branch="research",
        description="ask and research_once route boundary stays distinct",
        expected_intents=("research_once",),
        expected_workflow_id="research_once",
    ),
    E2EQualityCase(
        id="E2E-RES-004",
        branch="research",
        description="single-source research triggers a verification query for official evidence",
        min_sources=2,
        min_web_search_calls=2,
        required_web_query_terms=("official announcement",),
    ),
    E2EQualityCase(
        id="E2E-RES-GAP-001",
        branch="research",
        description="single media source records evidence gaps when verification budget is unavailable",
        expected_research_statuses=("completed", "completed_with_limitations", "completed_verified"),
        expected_gap_types=("single_source", "missing_primary_source"),
        min_sources=1,
        min_events=1,
        min_digest_items=1,
    ),
    E2EQualityCase(
        id="E2E-RES-005",
        branch="research",
        description="research source collection canonicalizes duplicate URL variants",
        min_sources=1,
        require_unique_canonical_urls=True,
    ),
    E2EQualityCase(
        id="E2E-RES-CLUSTER-001",
        branch="research",
        description="multiple differently titled sources for the same event cluster into one event",
        expected_research_statuses=("completed", "completed_with_limitations", "completed_verified"),
        min_sources=3,
        min_events=1,
        max_events=1,
        min_digest_items=1,
        required_digest_terms=("Agent Runtime SDK",),
    ),
    E2EQualityCase(
        id="E2E-RES-CLUSTER-002",
        branch="research",
        description="similar Agent Runtime SDK sources for different events stay separated",
        expected_research_statuses=("completed", "completed_with_limitations", "completed_verified"),
        min_sources=2,
        min_events=2,
        min_digest_items=1,
        required_digest_terms=("Agent Runtime SDK",),
    ),
    E2EQualityCase(
        id="E2E-RES-008",
        branch="research",
        description="research tool budget exhaustion is observable and terminal",
        expected_stop_reason="tool budget exhausted",
        min_tool_call_traces=1,
        min_stage_timings=1,
    ),
    E2EQualityCase(
        id="E2E-RES-FAIL-002",
        branch="research",
        description="capture_url failure is traced while snippet evidence still produces a limited digest",
        expected_research_statuses=("completed", "completed_with_limitations", "completed_verified"),
        min_sources=2,
        min_events=1,
        min_digest_items=1,
        min_failed_tool_calls=1,
        expected_tool_error_kinds=("unrecoverable",),
    ),
]

CASE_BY_ID = {case.id: case for case in CASES}


@pytest.fixture
def e2e_settings(temp_dir: Path) -> Settings:
    try:
        settings = Settings.from_env()
    except Exception as exc:
        pytest.skip(f"real LLM settings are not loadable: {exc}")
    if not (settings.openai.api_key and settings.openai.base_url):
        pytest.skip("real E2E quality requires OPENAI_API_KEY and OPENAI_BASE_URL")
    if not (settings.router.api_key and settings.router.base_url):
        pytest.skip("real E2E quality requires ROUTER_* or OPENAI_* router config")
    return settings.model_copy(update={
        "data_dir": temp_dir,
        "postgres_url": POSTGRES_URL,
    })


@pytest.fixture
def service(e2e_settings: Settings) -> AgentService:
    return AgentService(e2e_settings)


def test_e2e_quality_meets_baseline(
    service: AgentService,
):
    selected_case_ids, selected_cases, selected_runners, selection = _selected_suite()
    baseline_enforced = baseline_should_be_enforced(
        case_selector=selection["case_selector"],
        branch_selector=selection["branch_selector"],
        enforce_value=selection["enforce_baseline"],
    )
    tracer = E2ETraceRecorder()
    tracer.event(
        "suite.started",
        case_count=len(selected_runners),
        total_case_count=len(CASE_RUNNERS),
        selected_case_ids=selected_case_ids,
        selection=selection,
        baseline_enforced=baseline_enforced,
    )
    runs: dict[str, E2EQualityRun] = {}
    try:
        for case_id, runner in selected_runners:
            runs[case_id] = _run_case_with_trace(service, case_id, runner, tracer)
        tracer.event("suite.cases_completed", completed_case_count=len(runs))
    except Exception as exc:
        tracer.event(
            "suite.failed",
            completed_case_count=len(runs),
            error_type=type(exc).__name__,
            error=str(exc)[:1000],
        )
        raise
    report = score_all(selected_cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "baseline.json").read_text(encoding="utf-8")
    )
    selected_baseline = _baseline_for_selected_cases(
        baseline,
        selected_case_ids,
        selected_cases,
    )
    baseline_failures = report.check_thresholds(selected_baseline)
    failures = baseline_failures if baseline_enforced else []
    tracer.event(
        "suite.scored",
        overall_score=report.overall_score,
        branch_scores={
            branch: report.branch_score(branch)
            for branch in sorted({case.branch for case in selected_cases})
        },
        baseline_enforced=baseline_enforced,
        baseline_failures=baseline_failures,
        failures=failures,
        summary=report.summary(),
    )
    assert not failures, (
        "e2e quality regression:\n"
        f"{report.summary()}\n"
        f"failures={failures}\n"
        f"trace={tracer.latest_path}"
    )


def _selected_suite():
    case_selector = os.getenv("E2E_QUALITY_CASES", "")
    branch_selector = os.getenv("E2E_QUALITY_BRANCHES", "")
    enforce_baseline = os.getenv("E2E_QUALITY_ENFORCE_BASELINE", "")
    runner_by_id = {case_id: runner for case_id, runner in CASE_RUNNERS}
    try:
        selected_case_ids = select_case_ids(
            CASES,
            runner_by_id.keys(),
            case_selector=case_selector,
            branch_selector=branch_selector,
        )
    except ValueError as exc:
        pytest.fail(str(exc))
    selected_cases = [CASE_BY_ID[case_id] for case_id in selected_case_ids]
    selected_runners = [(case_id, runner_by_id[case_id]) for case_id in selected_case_ids]
    return selected_case_ids, selected_cases, selected_runners, {
        "case_selector": case_selector,
        "branch_selector": branch_selector,
        "enforce_baseline": enforce_baseline,
    }


def _baseline_for_selected_cases(
    baseline: dict[str, object],
    selected_case_ids: tuple[str, ...],
    selected_cases: list[E2EQualityCase],
) -> dict[str, object]:
    selected = set(selected_case_ids)
    branches = {case.branch for case in selected_cases}
    adjusted = dict(baseline)
    adjusted["critical_cases"] = [
        case_id
        for case_id in (baseline.get("critical_cases") or [])
        if str(case_id) in selected
    ]
    adjusted["min_case_scores"] = {
        str(case_id): threshold
        for case_id, threshold in dict(baseline.get("min_case_scores") or {}).items()
        if str(case_id) in selected
    }
    adjusted["min_branch_scores"] = {
        str(branch): threshold
        for branch, threshold in dict(baseline.get("min_branch_scores") or {}).items()
        if str(branch) in branches
    }
    return adjusted


def _run_ask_seeded(service: AgentService) -> E2EQualityRun:
    service.execute_capture(
        text="服务降级是在系统压力过大时主动关闭非核心能力，以保障核心链路继续可用。",
        source_type="text",
        user_id="e2e-ask",
    )
    result = service.execute_entry(EntryInput(
        text="什么是服务降级？",
        user_id="e2e-ask",
        session_id="e2e-ask-session",
        source_platform="e2e_quality",
    ))
    snapshot = service.get_run_snapshot(result.run_id or "")
    return _ask_run(service, "E2E-ASK-001", result, workflow_id=snapshot.workflow_id if snapshot else "")


def _run_ask_no_evidence(service: AgentService) -> E2EQualityRun:
    result = service.execute_entry(EntryInput(
        text="我的 Phoenix 项目上线窗口是什么？",
        user_id="e2e-ask-empty",
        session_id="e2e-ask-empty-session",
        source_platform="e2e_quality",
    ))
    return _ask_run(service, "E2E-ASK-002", result)


def _run_ask_multi_note(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-ask-multi"
    for text in (
        "pytest 是 Python 常用测试框架，支持 fixture 和参数化。",
        "unittest 是 Python 标准库自带的测试框架。",
        "nose2 是 unittest 的扩展，提供测试发现能力。",
    ):
        service.execute_capture(text=text, source_type="text", user_id=user_id)
    result = service.execute_entry(EntryInput(
        text="Python 有哪些测试框架？",
        user_id=user_id,
        session_id="e2e-ask-multi-session",
        source_platform="e2e_quality",
    ))
    return _ask_run(service, "E2E-ASK-003", result)


def _run_compound_capture_then_ask(service: AgentService) -> E2EQualityRun:
    result = service.execute_entry(EntryInput(
        text="记一下：蓝绿发布需要先切一半流量，然后回答蓝绿发布怎么做？",
        user_id="e2e-compound",
        session_id="e2e-compound-session",
        source_platform="e2e_quality",
    ))
    dependency_edges = _dependency_edges(result.plan or {})
    return _ask_run(
        service,
        "E2E-ASK-005",
        result,
        note_count=len(service.memory.list_notes("e2e-compound", include_chunks=False)),
        dependency_edges=dependency_edges,
    )


def _run_ask_source_filter(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-ask-filter"
    service.execute_capture(
        text="蓝绿发布需要先把一半流量切到新版本。",
        source_type="file",
        source_ref="D:/uploads/deploy.md",
        user_id=user_id,
    )
    service.execute_capture(
        text="蓝绿发布需要先把一半流量切到新版本。",
        source_type="link",
        source_ref="https://example.com/deploy",
        user_id=user_id,
    )
    result = service.execute_entry(EntryInput(
        text="只看 deploy.md 文件，蓝绿发布怎么做？",
        user_id=user_id,
        session_id="e2e-ask-filter-session",
        source_platform="e2e_quality",
    ))
    return _ask_run(service, "E2E-ASK-006", result)


def _run_ask_conflicting_evidence(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-ask-conflict"
    for text in (
        "Feature X 灰度开关在服务端规范 A 中默认开启。",
        "Feature X 灰度开关在服务端规范 B 中默认关闭。",
    ):
        service.execute_capture(text=text, source_type="text", user_id=user_id)
    result = service.execute_entry(EntryInput(
        text="Feature X 灰度开关默认开启吗？",
        user_id=user_id,
        session_id="e2e-ask-conflict-session",
        source_platform="e2e_quality",
    ))
    return _ask_run(service, "E2E-ASK-SEM-002", result)


def _run_ask_web_fallback(service: AgentService) -> E2EQualityRun:
    result = service.execute_entry(EntryInput(
        text="Kappa API 的 rate limit 是多少？",
        user_id="e2e-ask-web",
        session_id="e2e-ask-web-session",
        source_platform="e2e_quality",
    ))
    return _ask_run(service, "E2E-ASK-WEB-002", result)


def _run_text_artifact_analysis(service: AgentService) -> E2EQualityRun:
    artifact = _write_artifact(
        service,
        filename="release-notes.txt",
        content_type="text/plain",
        source_type="file",
        content=(
            "蓝绿发布 runbook\n"
            "步骤：先把一半流量切到新版本，观察错误率，再逐步扩大流量。"
        ).encode("utf-8"),
    )
    result = service.execute_entry(EntryInput(
        text="根据附件说明，蓝绿发布第一步怎么做？",
        user_id="e2e-artifact-text",
        session_id="e2e-artifact-text-session",
        source_platform="e2e_quality",
        artifacts=[artifact],
    ))
    return _artifact_run(service, "E2E-ART-001", result)


def _run_image_artifact_metadata_degrade(service: AgentService) -> E2EQualityRun:
    artifact = _write_artifact(
        service,
        filename="chart.png",
        content_type="image/png",
        source_type="image",
        content=(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
    )
    result = service.execute_entry(EntryInput(
        text="这张图里讲了什么？",
        user_id="e2e-artifact-image",
        session_id="e2e-artifact-image-session",
        source_platform="e2e_quality",
        artifacts=[artifact],
    ))
    return _artifact_run(service, "E2E-ART-002", result)


def _run_direct_answer(service: AgentService) -> E2EQualityRun:
    result = service.execute_entry(EntryInput(
        text="你好，简短回应一句就好。",
        user_id="e2e-wf-direct",
        session_id="e2e-wf-direct-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(service, "E2E-WF-DIRECT-001", result)


def _run_capture_text_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-capture"
    result = service.execute_entry(EntryInput(
        text="记一下：Atlas 项目的值班窗口是每周三上午 10 点。",
        user_id=user_id,
        session_id="e2e-wf-capture-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(
        service,
        "E2E-WF-CAPTURE-001",
        result,
        note_count=len(service.memory.list_notes(user_id, include_chunks=False)),
    )


def _run_capture_file_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-capture-file"
    artifact = _write_artifact(
        service,
        filename="gamma-runbook.txt",
        content_type="text/plain",
        source_type="file",
        content=(
            "Gamma runbook\n"
            "发布窗口：周五 20:00。回滚联系人：Rhea。"
        ).encode("utf-8"),
    )
    result = service.execute_entry(EntryInput(
        text="把这个附件保存到知识库。",
        user_id=user_id,
        session_id="e2e-wf-capture-file-session",
        source_platform="e2e_quality",
        artifacts=[artifact],
    ))
    return _entry_run(
        service,
        "E2E-WF-CAPTURE-FILE-001",
        result,
        note_count=len(service.memory.list_notes(user_id, include_chunks=False)),
    )


def _run_summarize_thread_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-summary"
    session_id = "e2e-wf-summary-session"
    previous_loader = service.runtime._thread_message_loader
    service.set_thread_message_loader(lambda entry_input, _limit: [
        {"role": "user", "content": "Orion 缓存改造今天确认使用 Redis。"},
        {"role": "assistant", "content": "记录：Orion 缓存方案为 Redis，待办是补压测。"},
        {"role": "user", "content": "压测负责人是 Lin。"},
    ])
    try:
        result = service.execute_entry(EntryInput(
            text="总结一下这个线程刚才讨论了什么。",
            user_id=user_id,
            session_id=session_id,
            source_platform="e2e_quality",
        ))
    finally:
        service.set_thread_message_loader(previous_loader)
    return _entry_run(service, "E2E-WF-SUM-001", result)


def _run_solidify_conversation_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-solidify"
    session_id = "e2e-wf-solidify-session"
    service.execute_entry(EntryInput(
        text="DNS 是域名系统，用于把域名解析成 IP 地址。",
        user_id=user_id,
        session_id=session_id,
        source_platform="e2e_quality",
    ))
    result = service.execute_entry(EntryInput(
        text="把刚才关于 DNS 的结论固化到知识库。",
        user_id=user_id,
        session_id=session_id,
        source_platform="e2e_quality",
    ))
    return _entry_run(
        service,
        "E2E-WF-SOLIDIFY-001",
        result,
        note_count=len(service.memory.list_notes(user_id, include_chunks=False)),
    )


def _run_review_digest_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-review"
    capture = service.execute_capture(
        text="复习触达应该优先推送到飞书。",
        source_type="text",
        user_id=user_id,
    )
    service.memory.add_review(ReviewCard(
        note_id=capture.note.id,
        prompt="请回忆复习触达的主入口",
        answer_hint="飞书",
        due_at=local_now(),
    ))
    result = service.execute_entry(EntryInput(
        text="生成今天的知识简报。",
        user_id=user_id,
        session_id="e2e-wf-review-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(service, "E2E-WF-REVIEW-001", result)


def _run_consolidate_knowledge_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-consolidate"
    for text in (
        "Redis 缓存可以降低数据库读压力。",
        "Redis 热点 key 需要设置过期时间和降级策略。",
    ):
        service.execute_capture(text=text, source_type="text", user_id=user_id)
    result = service.execute_entry(EntryInput(
        text="把 Redis 相关笔记整理成一篇综述。",
        user_id=user_id,
        session_id="e2e-wf-consolidate-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(
        service,
        "E2E-WF-CONSOLIDATE-001",
        result,
        note_count=len(service.memory.list_notes(user_id, include_chunks=False)),
    )


def _run_inspect_knowledge_gaps_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-gap"
    for text in (
        "缓存方案 A 认为 Redis 默认开启持久化。",
        "缓存方案 B 认为 Redis 默认关闭持久化。",
        "孤立知识：Lambda 归档策略只记录了一个片段。",
    ):
        service.execute_capture(text=text, source_type="text", user_id=user_id)
    result = service.execute_entry(EntryInput(
        text="检查我的知识库还有哪些缺口、冲突或薄弱连接。",
        user_id=user_id,
        session_id="e2e-wf-gap-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(service, "E2E-WF-GAP-001", result)


def _run_inspect_workflow_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-inspect"
    first = service.execute_entry(EntryInput(
        text="你好，回复一句即可。",
        user_id=user_id,
        session_id="e2e-wf-inspect-first",
        source_platform="e2e_quality",
    ))
    result = service.execute_entry(EntryInput(
        text=f"查看 workflow run_id {first.run_id} 的步骤执行情况。",
        user_id=user_id,
        session_id="e2e-wf-inspect-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(service, "E2E-WF-INSPECT-001", result)


def _run_delete_knowledge_workflow(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-delete"
    service.execute_capture(
        text="Delta 临时笔记：这条记录用于删除确认测试。",
        source_type="text",
        user_id=user_id,
    )
    result = service.execute_entry(EntryInput(
        text="删除那条 Delta 临时笔记。",
        user_id=user_id,
        session_id="e2e-wf-delete-session",
        source_platform="e2e_quality",
    ))
    return _entry_run(service, "E2E-WF-DELETE-001", result)


def _run_complex_capture_ask(service: AgentService) -> E2EQualityRun:
    user_id = "e2e-wf-complex"
    result = service.execute_entry(EntryInput(
        text=(
            "先记一下：Gamma 发布窗口是周五 20:00；"
            "然后直接回答 Gamma 发布窗口是什么，不要发起调研。"
        ),
        user_id=user_id,
        session_id="e2e-wf-complex-session",
        source_platform="e2e_quality",
    ))
    dependency_edges = _dependency_edges(result.plan or {})
    return _ask_run(
        service,
        "E2E-WF-COMPLEX-001",
        result,
        note_count=len(service.memory.list_notes(user_id, include_chunks=False)),
        dependency_edges=dependency_edges,
    )


def _run_research_dual_source(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=1,
        lookback_hours=24,
    )
    snapshots = service.list_run_snapshots(user_id="e2e-research", limit=5)
    snapshot = next((s for s in snapshots if s.workflow_id == "research_once"), None)
    return _research_run("E2E-RES-001", service, run.id, workflow_id="research_once", snapshot=snapshot)


def _run_route_boundary(service: AgentService) -> E2EQualityRun:
    service.execute_entry(EntryInput(
        text="什么是 Agent Runtime SDK？",
        user_id="e2e-route-boundary",
        session_id="e2e-route-ask",
        source_platform="e2e_quality",
    ))
    result = service.execute_entry(EntryInput(
        text="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        user_id="e2e-route-boundary",
        session_id="e2e-route-research",
        source_platform="e2e_quality",
    ))
    snapshot = service.get_run_snapshot(result.run_id or "")
    return E2EQualityRun(
        case_id="E2E-RES-002",
        branch="research",
        intents=tuple(result.intents),
        workflow_id=snapshot.workflow_id if snapshot else "",
    )


def _run_research_verification_query(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research-verify",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=1,
        lookback_hours=24,
    )
    return _research_run(
        "E2E-RES-004",
        service,
        run.id,
    )


def _run_research_single_source_gap(service: AgentService) -> E2EQualityRun:
    previous_budget = service.research_service.default_budget
    service.research_service.default_budget = ResearchBudget(
        max_queries=1,
        max_exploration_queries=1,
        max_verification_queries=0,
        max_satisfaction_model_calls=0,
        max_search_results=2,
        max_fulltext_fetches=1,
        max_tool_calls=4,
    )
    try:
        run = service.run_research_once(
            user_id="e2e-research-gap",
            topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
            instructions="优先官方来源；输出中文摘要。",
            max_items=1,
            lookback_hours=24,
        )
        return _research_run("E2E-RES-GAP-001", service, run.id)
    finally:
        service.research_service.default_budget = previous_budget


def _run_research_url_dedupe(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research-dedupe",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=1,
        lookback_hours=24,
    )
    return _research_run("E2E-RES-005", service, run.id)


def _run_research_same_event_cluster(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research-cluster-same",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=1,
        lookback_hours=24,
    )
    return _research_run("E2E-RES-CLUSTER-001", service, run.id)


def _run_research_distinct_event_cluster(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research-cluster-distinct",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 2 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=2,
        lookback_hours=24,
    )
    return _research_run("E2E-RES-CLUSTER-002", service, run.id)


def _run_research_budget(service: AgentService) -> E2EQualityRun:
    previous_budget = service.research_service.default_budget
    service.research_service.default_budget = ResearchBudget(
        max_queries=2,
        max_exploration_queries=1,
        max_verification_queries=1,
        max_satisfaction_model_calls=0,
        max_search_results=4,
        max_fulltext_fetches=2,
        max_tool_calls=1,
    )
    try:
        run = service.run_research_once(
            user_id="e2e-research-budget",
            topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
            instructions="优先官方来源；输出中文摘要。",
            max_items=1,
            lookback_hours=24,
        )
        return _research_run("E2E-RES-008", service, run.id)
    finally:
        service.research_service.default_budget = previous_budget


def _run_research_capture_url_failure(service: AgentService) -> E2EQualityRun:
    run = service.run_research_once(
        user_id="e2e-research-capture-failure",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多 1 条，高可信",
        instructions="优先官方来源；输出中文摘要。",
        max_items=1,
        lookback_hours=24,
    )
    return _research_run("E2E-RES-FAIL-002", service, run.id)


CASE_RUNNERS = [
    ("E2E-ASK-001", _run_ask_seeded),
    ("E2E-ASK-002", _run_ask_no_evidence),
    ("E2E-ASK-003", _run_ask_multi_note),
    ("E2E-ASK-005", _run_compound_capture_then_ask),
    ("E2E-ASK-006", _run_ask_source_filter),
    ("E2E-ASK-SEM-002", _run_ask_conflicting_evidence),
    ("E2E-ASK-WEB-002", _run_ask_web_fallback),
    ("E2E-ART-001", _run_text_artifact_analysis),
    ("E2E-ART-002", _run_image_artifact_metadata_degrade),
    ("E2E-WF-DIRECT-001", _run_direct_answer),
    ("E2E-WF-CAPTURE-001", _run_capture_text_workflow),
    ("E2E-WF-CAPTURE-FILE-001", _run_capture_file_workflow),
    ("E2E-WF-SUM-001", _run_summarize_thread_workflow),
    ("E2E-WF-SOLIDIFY-001", _run_solidify_conversation_workflow),
    ("E2E-WF-REVIEW-001", _run_review_digest_workflow),
    ("E2E-WF-CONSOLIDATE-001", _run_consolidate_knowledge_workflow),
    ("E2E-WF-GAP-001", _run_inspect_knowledge_gaps_workflow),
    ("E2E-WF-INSPECT-001", _run_inspect_workflow_workflow),
    ("E2E-WF-DELETE-001", _run_delete_knowledge_workflow),
    ("E2E-WF-COMPLEX-001", _run_complex_capture_ask),
    ("E2E-RES-001", _run_research_dual_source),
    ("E2E-RES-002", _run_route_boundary),
    ("E2E-RES-004", _run_research_verification_query),
    ("E2E-RES-GAP-001", _run_research_single_source_gap),
    ("E2E-RES-005", _run_research_url_dedupe),
    ("E2E-RES-CLUSTER-001", _run_research_same_event_cluster),
    ("E2E-RES-CLUSTER-002", _run_research_distinct_event_cluster),
    ("E2E-RES-008", _run_research_budget),
    ("E2E-RES-FAIL-002", _run_research_capture_url_failure),
]


class E2ETraceRecorder:
    def __init__(self) -> None:
        trace_dir = Path("data") / "e2e_quality_traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = trace_dir / f"{self.run_id}.jsonl"
        self.latest_path = trace_dir / "latest.jsonl"
        self.latest_path.write_text("", encoding="utf-8")
        self.event(
            "trace.initialized",
            run_id=self.run_id,
            path=str(self.path),
            latest_path=str(self.latest_path),
        )

    def event(self, event_type: str, **payload: object) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "run_id": self.run_id,
            **payload,
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        for path in (self.path, self.latest_path):
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()


class CaseLogCapture(logging.Handler):
    def __init__(self, *, case_id: str, tracer: E2ETraceRecorder) -> None:
        super().__init__(level=logging.INFO)
        self.case_id = case_id
        self.tracer = tracer
        self.records: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING and not _is_diagnostic_logger(record.name):
            return
        entry = {
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage()[:1600],
        }
        if len(self.records) < 120:
            self.records.append(entry)
        self.tracer.event(
            "case.diagnostic_log",
            case_id=self.case_id,
            logger=entry["logger"],
            level=entry["level"],
            message=entry["message"],
        )


def _is_diagnostic_logger(name: str) -> bool:
    return name.startswith((
        "personal_agent.infra.structured_model",
        "personal_agent.planning.router",
        "personal_agent.application.verifier",
        "personal_agent.application.artifacts",
        "personal_agent.application.capture.providers.web_search",
        "personal_agent.application.research",
        "personal_agent.kernel.observability",
    ))


def _run_case_with_trace(
    service: AgentService,
    case_id: str,
    runner,
    tracer: E2ETraceRecorder,
) -> E2EQualityRun:
    case = CASE_BY_ID[case_id]
    started = perf_counter()
    tracer.event(
        "case.started",
        case_id=case_id,
        branch=case.branch,
        description=case.description,
    )
    log_capture = CaseLogCapture(case_id=case_id, tracer=tracer)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_capture)
    try:
        with collect_llm_usage() as llm_usage:
            run = runner(service)
        duration_ms = round((perf_counter() - started) * 1000, 2)
        metadata = {
            **run.metadata,
            "trace": {
                "duration_ms": duration_ms,
                "llm_call_count": llm_usage.call_count,
                "llm_latency_ms": round(llm_usage.latency_ms, 2),
                "input_tokens": llm_usage.input_tokens,
                "output_tokens": llm_usage.output_tokens,
                "total_tokens": llm_usage.total_tokens,
                "diagnostic_logs": log_capture.records,
                "trace_path": str(tracer.path),
            },
        }
        traced_run = replace(run, metadata=metadata)
        tracer.event(
            "case.completed",
            case_id=case_id,
            branch=case.branch,
            duration_ms=duration_ms,
            llm_call_count=llm_usage.call_count,
            llm_latency_ms=round(llm_usage.latency_ms, 2),
            run_summary=_run_trace_summary(traced_run),
            diagnostic_logs=log_capture.records,
        )
        return traced_run
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        tracer.event(
            "case.failed",
            case_id=case_id,
            branch=case.branch,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc)[:2000],
            traceback=traceback.format_exc()[-4000:],
            diagnostic_logs=log_capture.records,
        )
        raise
    finally:
        root_logger.removeHandler(log_capture)


def _run_trace_summary(run: E2EQualityRun) -> dict[str, object]:
    return {
        "intents": run.intents,
        "run_status": run.run_status,
        "workflow_id": run.workflow_id,
        "research_status": run.research_status,
        "matches_count": run.matches_count,
        "citations_count": run.citations_count,
        "evidence_count": run.evidence_count,
        "verification_score": run.verification_score,
        "grounding_status": run.grounding_status,
        "web_tried": run.web_tried,
        "source_count": run.source_count,
        "event_count": run.event_count,
        "digest_item_count": run.digest_item_count,
        "stop_reason": run.stop_reason,
        "tool_call_trace_count": run.tool_call_trace_count,
        "failed_tool_call_count": run.failed_tool_call_count,
        "tool_error_kinds": run.tool_error_kinds,
        "stage_timing_count": run.stage_timing_count,
    }


def _ask_run(
    service: AgentService,
    case_id: str,
    result,
    *,
    workflow_id: str = "",
    llm_call_count: int = 0,
    note_count: int = 0,
    dependency_edges: tuple[tuple[str, str], ...] = (),
) -> E2EQualityRun:
    ask_result = result.ask_result
    ctx = (
        service.runtime.graph_contexts.steps.ask_run_context_store.get(result.run_id)
        if result.run_id else None
    )
    verification = getattr(ctx, "verification", None) if ctx else None
    repair = getattr(ctx, "repair", None) if ctx else None
    return E2EQualityRun(
        case_id=case_id,
        branch="ask",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=workflow_id,
        answer=ask_result.answer if ask_result else "",
        matches_count=len(ask_result.matches) if ask_result else 0,
        citations_count=len(ask_result.citations) if ask_result else 0,
        evidence_count=len(ask_result.evidence) if ask_result else 0,
        llm_call_count=llm_call_count,
        verification_score=float(getattr(verification, "evidence_score", 0.0) or 0.0),
        grounding_status=str(getattr(repair, "final_grounding_status", "") or ""),
        claim_statuses=tuple(
            str(getattr(item, "status", ""))
            for item in (getattr(verification, "claim_checks", []) if verification else [])
        ),
        web_tried=bool(getattr(ctx, "web_tried", False)) if ctx else False,
        note_count=note_count,
        dependency_edges=dependency_edges,
    )


def _artifact_run(
    service: AgentService,
    case_id: str,
    result,
) -> E2EQualityRun:
    snapshot = service.get_run_snapshot(result.run_id or "")
    return E2EQualityRun(
        case_id=case_id,
        branch="artifact",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(step["step_id"] for step in (snapshot.steps if snapshot else [])),
        answer=result.reply_text,
    )


def _entry_run(
    service: AgentService,
    case_id: str,
    result,
    *,
    note_count: int = 0,
    dependency_edges: tuple[tuple[str, str], ...] = (),
) -> E2EQualityRun:
    snapshot = service.get_run_snapshot(result.run_id or "")
    snapshot_steps = tuple(step["step_id"] for step in (snapshot.steps if snapshot else []))
    result_steps = tuple(
        str(step.get("step_id") or "")
        for step in (getattr(result, "steps", None) or [])
        if step.get("step_id")
    )
    workflow_id = snapshot.workflow_id if snapshot else ""
    if not workflow_id and result.intents:
        workflow_id = result.intents[-1]
    ask_result = getattr(result, "ask_result", None)
    return E2EQualityRun(
        case_id=case_id,
        branch="workflow",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=workflow_id,
        step_ids=snapshot_steps or result_steps,
        answer=(ask_result.answer if ask_result else result.reply_text),
        matches_count=len(ask_result.matches) if ask_result else 0,
        citations_count=len(ask_result.citations) if ask_result else 0,
        evidence_count=len(ask_result.evidence) if ask_result else 0,
        note_count=note_count,
        dependency_edges=dependency_edges,
    )


def _research_run(
    case_id: str,
    service: AgentService,
    run_id: str,
    *,
    workflow_id: str = "",
    snapshot=None,
    web_search_queries: tuple[str, ...] = (),
) -> E2EQualityRun:
    run = service.research_store.get_run(run_id)
    digest = service.research_service.get_digest(run.digest_id) if run and run.digest_id else None
    events = service.research_store.list_run_events(run_id)
    sources = service.research_store.list_run_sources(run_id)
    state = run.research_state if run else None
    satisfaction = state.satisfaction if state else None
    return E2EQualityRun(
        case_id=case_id,
        branch="research",
        workflow_id=workflow_id,
        step_ids=tuple(step["step_id"] for step in (snapshot.steps if snapshot else [])),
        research_status=run.status if run else "",
        source_count=run.source_count if run else 0,
        event_count=run.event_count if run else 0,
        digest_item_count=len(digest.items) if digest else 0,
        digest_text=digest.to_text() if digest else "",
        event_statuses=tuple(event.status for event in events),
        confidence_labels=tuple(item.confidence_label for item in (digest.items if digest else [])),
        web_search_queries=web_search_queries or tuple(state.query_history if state else []),
        gap_types=tuple(gap.type for gap in (state.evidence_gaps if state else [])),
        satisfaction_should_continue=(
            bool(satisfaction.should_continue) if satisfaction is not None else None
        ),
        satisfaction_coverage_score=float(
            satisfaction.coverage_score if satisfaction is not None else 0.0
        ),
        satisfaction_confidence_score=float(
            satisfaction.confidence_score if satisfaction is not None else 0.0
        ),
        satisfaction_marginal_gain=float(
            satisfaction.marginal_gain if satisfaction is not None else 0.0
        ),
        stop_reason=state.stop_reason if state else "",
        tool_call_trace_count=len(state.tool_call_traces) if state else 0,
        failed_tool_call_count=sum(
            1 for trace in (state.tool_call_traces if state else []) if not trace.ok
        ),
        tool_error_kinds=tuple(
            trace.error_kind for trace in (state.tool_call_traces if state else []) if trace.error_kind
        ),
        stage_timing_count=len(state.stage_timings) if state else 0,
        canonical_urls=tuple(source.canonical_url for source in sources),
    )


def _write_artifact(
    service: AgentService,
    *,
    filename: str,
    content_type: str,
    source_type: str,
    content: bytes,
) -> ArtifactRef:
    artifact_dir = Path(service.settings.data_dir) / "e2e_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    file_path = artifact_dir / filename
    file_path.write_bytes(content)
    return ArtifactRef(
        artifact_id=f"e2e-{filename}",
        filename=filename,
        content_type=content_type,
        source_type=source_type,
        file_path=str(file_path),
        size_bytes=len(content),
    )


def _dependency_edges(plan: dict[str, object]) -> tuple[tuple[str, str], ...]:
    edges: list[tuple[str, str]] = []
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "")
        for dep in task.get("depends_on", []):
            edges.append((task_id, str(dep)))
    return tuple(edges)

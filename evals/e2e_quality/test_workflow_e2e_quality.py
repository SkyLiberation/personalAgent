from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
import traceback
from unittest.mock import patch

import pytest
from langchain_core.tools import tool

from personal_agent.application.research import ResearchBudget
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.kernel.models import ArtifactRef, EntryInput, ReviewCard, local_now
from personal_agent.orchestration.service import AgentService
from personal_agent.tools import governance_extras, tool_response, tool_success
from personal_agent.application.workspace import (
    Claim,
    ClaimRelationAdjudication,
    ClaimRelationCandidate,
    ConversationMessage,
    WorkspaceService,
)
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
        id="E2E-LIFE-001",
        branch="life",
        description="Artifact creates EvidenceBlock and EvidenceSpan",
        min_evidence_blocks=1,
        min_evidence_spans=1,
        min_knowledge_items=1,
        max_projection_job_failed_count=0,
    ),
    E2EQualityCase(
        id="E2E-LIFE-001B",
        branch="life",
        description="Evidence-first ingest does not require claim lifecycle",
        min_evidence_blocks=1,
        min_evidence_spans=1,
        min_knowledge_items=1,
        max_partial_failure_count=0,
        max_projection_job_failed_count=0,
    ),
    E2EQualityCase(
        id="E2E-LIFE-002",
        branch="life",
        description="unsupported or sensitive candidate claim does not default active",
        min_claim_admission_decisions=1,
        min_decisions=1,
        expected_claim_states=("verified",),
        forbidden_claim_states=("active",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-003",
        branch="life",
        description="P0 workspace lifecycle answers only through resolvable EvidenceSpan citations",
        min_citations=1,
        min_evidence=1,
        min_evidence_blocks=1,
        min_evidence_spans=1,
        min_grounding_runs=1,
        min_claim_admission_decisions=1,
        expected_grounding_statuses=("supported", "weak_evidence"),
        expected_evidence_coverages=("complete", "partial", "sparse"),
        expected_claim_states=("active",),
        expected_admission_results=("allow_active",),
        require_citation_resolves_to_artifact=True,
        max_answer_claim_saved_count=0,
        max_active_claim_count_delta=0,
        required_answer_terms=("蓝绿发布",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-004",
        branch="life",
        description="no evidence question returns conservative answer",
        expected_grounding_statuses=("unsupported",),
        expected_evidence_coverages=("none",),
        max_citations=0,
        max_evidence=0,
        required_answer_terms=("证据不足",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-004B",
        branch="life",
        description="partial evidence coverage is diagnosed instead of treated as complete",
        min_citations=1,
        expected_evidence_coverages=("partial", "sparse"),
        min_missing_sections=1,
        required_answer_terms=("证据",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-005",
        branch="life",
        description="P2 solidify conversation persists only user-confirmed claims",
        min_user_claims=1,
        min_claim_admission_decisions=1,
        expected_claim_states=("active",),
        expected_admission_results=("allow_active",),
        max_assistant_inference_active_count=0,
    ),
    E2EQualityCase(
        id="E2E-LIFE-006",
        branch="life",
        description="P3 conflicting new knowledge creates potential relation and review decision",
        min_knowledge_relations=1,
        expected_relation_types=("potential_conflict",),
        expected_claim_states=("active",),
        required_answer_terms=("冲突",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-007",
        branch="life",
        description="DecisionPolicy only creates pending card for high-risk claim",
        min_decisions=1,
        max_pending_decision_count=1,
        forbidden_claim_states=("active",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-008",
        branch="life",
        description="P4 research event enters lifecycle and impacts existing claims",
        min_research_events=1,
        min_claim_admission_decisions=1,
        min_knowledge_relations=1,
    ),
    E2EQualityCase(
        id="E2E-LIFE-009",
        branch="life",
        description="P5 review and gaps are based on claim state",
        min_review_items=1,
        min_knowledge_gaps=1,
    ),
    E2EQualityCase(
        id="E2E-LIFE-010",
        branch="life",
        description="P6 graph projections backlink to Claim and Evidence",
        min_graph_projections=1,
        require_graph_projection_backlinks=True,
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-001",
        branch="life_semantic",
        description="compound source sentence becomes multiple structured claims with evidence refs",
        min_claim_admission_decisions=2,
        min_claim_quality_passed_count=2,
        max_claim_without_evidence_ref_count=0,
        expected_claim_states=("active",),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-002",
        branch="life_semantic",
        description="semantic grounding supports same meaning without requiring old term-overlap verifier",
        min_grounding_runs=1,
        expected_claim_states=("active", "grounded"),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-003",
        branch="life_semantic",
        description="coverage manifest omitted region is exposed as partial coverage",
        expected_evidence_coverages=("partial", "sparse"),
        min_missing_sections=1,
        min_coverage_manifest_omitted_count=1,
        required_semantic_component_terms=("semantic", "coverage"),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-004",
        branch="life_semantic",
        description="different scopes do not write a final conflict relation",
        forbidden_relation_types=("conflict",),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-005",
        branch="life_semantic",
        description="same-scope true conflict is written only after structured relation judge",
        min_knowledge_relations=1,
        expected_relation_types=("conflict",),
        expected_claim_states=("conflicted",),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-006",
        branch="life_semantic",
        description="table-like source becomes table EvidenceBlock and structured Claim",
        min_table_evidence_blocks=1,
        min_claim_quality_passed_count=1,
        max_claim_without_evidence_ref_count=0,
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-007",
        branch="life_semantic",
        description="ask answer claims are not saved as long-term active claims",
        min_citations=1,
        max_answer_claim_saved_count=0,
        max_active_claim_count_delta=0,
        required_semantic_component_terms=("semantic", "coverage"),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-008",
        branch="life_semantic",
        description="claim-aware ask uses scope/state as enhancement while keeping evidence citations",
        min_citations=1,
        min_claim_quality_passed_count=1,
        require_citation_resolves_to_artifact=True,
        max_claim_without_evidence_ref_count=0,
        required_answer_terms=("规范 A",),
        required_semantic_component_terms=("semantic", "grounding", "coverage"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-009",
        branch="life_semantic",
        description="solidify realistic conversation does not active assistant inference",
        min_user_claims=1,
        max_assistant_inference_active_count=0,
        expected_claim_states=("active",),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-010",
        branch="life_semantic",
        description="research claim creates impact relation without silently overwriting existing user claim",
        min_research_events=1,
        min_knowledge_relations=1,
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-011",
        branch="life_semantic",
        description="review projection excludes invalid or assistant-inference claims",
        min_review_items=1,
        min_knowledge_gaps=1,
        max_review_invalid_claim_count=0,
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-012",
        branch="life_semantic",
        description="graph projection requires eligible structured claims and backlinks",
        min_graph_projections=1,
        require_graph_projection_backlinks=True,
        max_projection_eligibility_violation_count=0,
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-013",
        branch="life_semantic",
        description="correction supersedes old claim and subsequent ask uses corrected state",
        min_knowledge_relations=1,
        expected_relation_types=("supersede",),
        expected_claim_states=("superseded", "active"),
        required_answer_terms=("周四",),
        required_semantic_component_terms=("semantic", "grounding", "coverage"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-014",
        branch="life_semantic",
        description="delete artifact cascades to dependent claims and invalidates projections",
        min_deleted_claims=1,
        expected_claim_states=("deleted",),
        required_semantic_component_terms=("semantic", "grounding"),
        forbidden_grounding_verifiers=("deterministic-term-overlap",),
    ),
    E2EQualityCase(
        id="E2E-LIFE-SEM-015",
        branch="life_semantic",
        description="semantic replay diff reports extraction differences without writing active claims",
        min_replay_diff_count=1,
        required_semantic_component_terms=("semantic",),
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
        id="E2E-GH-MCP-001",
        branch="github_mcp",
        description="GitHub repo implementation question calls github.search_code through ToolGateway",
        expected_intents=("github_repository_qa",),
        expected_workflow_id="github_repository_qa",
        expected_steps=("github-retrieve", "github-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("github.search_code",),
        forbidden_tool_names=("graph_search",),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-GH-MCP-002",
        branch="github_mcp",
        description="GitHub README/file question calls github.get_file_contents through ToolGateway",
        expected_intents=("github_repository_qa",),
        expected_workflow_id="github_repository_qa",
        expected_steps=("github-retrieve", "github-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("github.get_file_contents",),
        forbidden_tool_names=("graph_search",),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-GH-MCP-003",
        branch="github_mcp",
        description="GitHub repository discovery question calls github.search_repositories through ToolGateway",
        expected_intents=("github_repository_qa",),
        expected_workflow_id="github_repository_qa",
        expected_steps=("github-retrieve", "github-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("github.search_repositories",),
        forbidden_tool_names=("graph_search",),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-GH-MCP-004",
        branch="github_mcp",
        description="repo-qualified code search calls github.search_code through ToolGateway",
        expected_intents=("github_repository_qa",),
        expected_workflow_id="github_repository_qa",
        expected_steps=("github-retrieve", "github-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("github.search_code",),
        forbidden_tool_names=("graph_search",),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-GH-MCP-005",
        branch="github_mcp",
        description="personal knowledge question stays outside GitHub MCP workflow and tools",
        expected_intents=("ask",),
        expected_workflow_id="ask",
        forbidden_tool_names=(
            "github.search_code",
            "github.get_file_contents",
            "github.search_repositories",
        ),
    ),
    E2EQualityCase(
        id="E2E-NOTION-MCP-001",
        branch="notion_mcp",
        description="Notion workspace search question calls notion.search through ToolGateway",
        expected_intents=("notion_workspace_qa",),
        expected_workflow_id="notion_workspace_qa",
        expected_steps=("notion-retrieve", "notion-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("notion.search",),
        forbidden_tool_names=("graph_search", "notion.retrieve_page_markdown"),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-NOTION-MCP-002",
        branch="notion_mcp",
        description="Notion page read question calls notion.retrieve_page_markdown through ToolGateway",
        expected_intents=("notion_workspace_qa",),
        expected_workflow_id="notion_workspace_qa",
        expected_steps=("notion-retrieve", "notion-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("notion.retrieve_page_markdown",),
        forbidden_tool_names=("graph_search", "notion.search"),
        min_tool_call_traces=1,
    ),
    E2EQualityCase(
        id="E2E-NOTION-MCP-003",
        branch="notion_mcp",
        description="Notion write request stays outside read-only Notion MCP workflow and tools",
        expected_intents=("ask",),
        expected_workflow_id="ask",
        forbidden_tool_names=("notion.search", "notion.retrieve_page_markdown"),
    ),
    E2EQualityCase(
        id="E2E-GPTR-A2A-001",
        branch="gpt_researcher_a2a",
        description="GPT Researcher A2A request calls gpt_researcher.a2a_research through ToolGateway",
        expected_intents=("gpt_researcher_a2a",),
        expected_workflow_id="gpt_researcher_a2a",
        expected_steps=("gptr-a2a-research", "gptr-a2a-compose"),
        expected_run_statuses=("completed",),
        expected_tool_names=("gpt_researcher.a2a_research",),
        forbidden_tool_names=("graph_search", "research_run_loop"),
        min_tool_call_traces=1,
        required_answer_terms=("Agent2Agent", "GPT Researcher A2A"),
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
    requires_live_llm = _selected_suite_requires_live_llm()
    try:
        settings = Settings.from_env()
    except Exception as exc:
        pytest.skip(f"real LLM settings are not loadable: {exc}")
    if requires_live_llm and not (settings.openai.api_key and settings.openai.base_url):
        pytest.skip("real E2E quality requires OPENAI_API_KEY and OPENAI_BASE_URL")
    if requires_live_llm and not (settings.structured.api_key and settings.structured.base_url):
        pytest.skip("real E2E quality requires STRUCTURED_* / ROUTER_* / OPENAI_* structured config")
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


def _selected_suite_requires_live_llm() -> bool:
    case_selector = os.getenv("E2E_QUALITY_CASES", "")
    branch_selector = os.getenv("E2E_QUALITY_BRANCHES", "")
    runner_by_id = {case_id: runner for case_id, runner in CASE_RUNNERS}
    try:
        selected = select_case_ids(
            CASES,
            runner_by_id.keys(),
            case_selector=case_selector,
            branch_selector=branch_selector,
        )
    except ValueError:
        return True
    no_live_llm_branches = {"github_mcp", "notion_mcp", "gpt_researcher_a2a"}
    return any(CASE_BY_ID[case_id].branch not in no_live_llm_branches for case_id in selected)


def _workspace_service(service: AgentService) -> WorkspaceService:
    return service.runtime.workspace_service


def _semantic_components(workspace: WorkspaceService) -> tuple[str, ...]:
    return tuple(filter(None, (
        getattr(workspace.semantic_evidence_extractor, "name", ""),
        getattr(workspace.semantic_claim_extractor, "name", ""),
        getattr(workspace.claim_grounding_judge, "name", ""),
        getattr(workspace.answer_coverage_judge, "name", ""),
    )))


def _grounding_verifiers(ingest) -> tuple[str, ...]:
    return tuple(run.verifier for run in ingest.grounding_runs)


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
        metadata={"intent_override": "ask"},
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
        note_count=_workspace_note_count(service, "e2e-compound"),
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


def _run_lifecycle_artifact_evidence(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-artifact"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_knowledge(
        "Redis 支持缓存。",
        user_id="e2e-life-artifact",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://redis",
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-001",
        branch="life",
        evidence_block_count=len(ingest.evidence_blocks),
        evidence_span_count=len(ingest.evidence_spans),
        knowledge_item_count=len(ingest.knowledge_items),
        projection_job_failed_count=sum(1 for job in ingest.projection_jobs if job.status == "failed"),
    )


def _run_lifecycle_partial_ingest(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-partial-ingest"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_knowledge(
        "Atlas 使用蓝绿发布。发布时只切换一半流量。",
        user_id="e2e-life-partial-ingest",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://partial-ingest",
    )
    answer = workspace.answer_with_evidence("Atlas 如何发布？", workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-001B",
        branch="life",
        answer=answer.answer,
        citations_count=len(answer.citations),
        evidence_count=len(ingest.evidence_spans),
        evidence_block_count=len(ingest.evidence_blocks),
        evidence_span_count=len(ingest.evidence_spans),
        knowledge_item_count=len(ingest.knowledge_items),
        projection_job_failed_count=sum(1 for job in ingest.projection_jobs if job.status == "failed"),
        partial_failure_count=ingest.partial_failure_count,
    )


def _run_lifecycle_candidate_guard(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-candidate-guard"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "我的 api key 是 sk-secret-123。",
        user_id="e2e-life-candidate-guard",
        workspace_id=workspace_id,
        source_type="conversation",
        created_by="user",
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-002",
        branch="life",
        claim_admission_decision_count=len(ingest.admission_decisions),
        decision_count=len(ingest.decisions),
        pending_decision_count=sum(1 for decision in ingest.decisions if decision.status == "pending"),
        claim_states=tuple(claim.state for claim in ingest.claims),
    )


def _run_lifecycle_p0(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-p0"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "蓝绿发布会同时保留两套环境。发布时可以将一半流量切到绿色环境。",
        user_id="e2e-life",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://blue-green",
    )
    answer = workspace.answer_with_evidence("蓝绿发布如何切流量？", workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-003",
        branch="life",
        answer=answer.answer,
        citations_count=len(answer.citations),
        evidence_count=len(ingest.evidence_spans),
        evidence_block_count=len(ingest.evidence_blocks),
        evidence_span_count=len(ingest.evidence_spans),
        grounding_run_count=len(ingest.grounding_runs),
        claim_admission_decision_count=len(ingest.admission_decisions),
        grounding_status=answer.grounding_status,
        evidence_coverage=answer.evidence_coverage,
        missing_section_count=len(answer.missing_sections),
        claim_states=tuple(claim.state for claim in ingest.claims),
        admission_results=tuple(decision.admission_result for decision in ingest.admission_decisions),
        citation_evidence_span_ids=tuple(citation.evidence_span_id for citation in answer.citations),
        citation_evidence_block_ids=tuple(citation.evidence_block_id for citation in answer.citations),
        citation_artifact_ids=tuple(citation.artifact_id for citation in answer.citations),
        answer_claim_saved_count=answer.answer_claim_saved_count,
        active_claim_count_delta=answer.active_claim_count_delta,
    )


def _run_lifecycle_no_evidence(service: AgentService) -> E2EQualityRun:
    workspace = _workspace_service(service)
    answer = workspace.answer_with_evidence("完全不存在的主题是什么？", workspace_id="e2e-life-no-evidence")
    return E2EQualityRun(
        case_id="E2E-LIFE-004",
        branch="life",
        answer=answer.answer,
        citations_count=len(answer.citations),
        evidence_count=len(answer.citations),
        grounding_status=answer.grounding_status,
        evidence_coverage=answer.evidence_coverage,
        missing_section_count=len(answer.missing_sections),
    )


def _run_lifecycle_partial_coverage(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-partial-coverage"
    workspace = _workspace_service(service)
    workspace.ingest_knowledge(
        "第一节：蓝绿发布保留两套环境。\n\n第二节：回滚时切回蓝色环境。",
        user_id="e2e-life-partial-coverage",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://partial-coverage",
    )
    answer = workspace.answer_with_evidence("蓝绿发布保留什么环境？", workspace_id=workspace_id, limit=1)
    return E2EQualityRun(
        case_id="E2E-LIFE-004B",
        branch="life",
        answer=answer.answer,
        citations_count=len(answer.citations),
        evidence_count=len(answer.citations),
        grounding_status=answer.grounding_status,
        evidence_coverage=answer.evidence_coverage,
        missing_section_count=len(answer.missing_sections),
    )


def _run_lifecycle_solidify(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-solidify"
    workspace = _workspace_service(service)
    result = workspace.solidify_conversation(
        [
            ConversationMessage(role="user", content="我的部署窗口是每周三上午十点。"),
            ConversationMessage(role="assistant", content="我推断你可能喜欢夜间发布。"),
        ],
        user_id="e2e-life-solidify",
        workspace_id=workspace_id,
    )
    assistant_active = sum(
        1
        for claim in result.ingest_result.claims
        if claim.claim_type == "assistant_inference" and claim.state == "active"
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-005",
        branch="life",
        user_claim_count=result.user_claim_count,
        claim_admission_decision_count=len(result.ingest_result.admission_decisions),
        claim_states=tuple(claim.state for claim in result.ingest_result.claims),
        admission_results=tuple(
            decision.admission_result for decision in result.ingest_result.admission_decisions
        ),
        assistant_inference_active_count=assistant_active,
    )


def _run_lifecycle_conflict(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-conflict"
    workspace = _workspace_service(service)
    first = workspace.ingest_text(
        "Orion 功能默认开启。",
        user_id="e2e-life-conflict",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://orion-a",
    )
    second = workspace.ingest_text(
        "Orion 功能默认关闭。",
        user_id="e2e-life-conflict",
        workspace_id=workspace_id,
        source_type="document",
        source_ref="fixture://orion-b",
    )
    relations = workspace.store.list_knowledge_relations(workspace_id, relation_type="potential_conflict")
    answer = workspace.answer_with_evidence("Orion 功能默认是否开启？", workspace_id=workspace_id)
    claims = [*first.claims, *second.claims]
    return E2EQualityRun(
        case_id="E2E-LIFE-006",
        branch="life",
        answer=answer.answer,
        knowledge_relation_count=len(relations),
        relation_types=tuple(relation.relation_type for relation in relations),
        claim_states=tuple((workspace.store.get_claim(claim.claim_id) or claim).state for claim in claims),
        citation_evidence_span_ids=tuple(citation.evidence_span_id for citation in answer.citations),
        citation_evidence_block_ids=tuple(citation.evidence_block_id for citation in answer.citations),
        citation_artifact_ids=tuple(citation.artifact_id for citation in answer.citations),
    )


def _run_lifecycle_decision_policy(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-decision"
    workspace = _workspace_service(service)
    low_risk = workspace.ingest_text(
        "Redis 支持缓存。",
        user_id="e2e-life-decision",
        workspace_id=workspace_id,
        source_type="document",
    )
    high_risk = workspace.ingest_text(
        "我的 api key 是 sk-secret-123。",
        user_id="e2e-life-decision",
        workspace_id=workspace_id,
        source_type="conversation",
        created_by="user",
    )
    decisions = [*low_risk.decisions, *high_risk.decisions]
    return E2EQualityRun(
        case_id="E2E-LIFE-007",
        branch="life",
        decision_count=len(decisions),
        pending_decision_count=sum(1 for decision in decisions if decision.status == "pending"),
        claim_states=tuple(claim.state for claim in high_risk.claims),
    )


def _run_lifecycle_research(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-research"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "Kappa API rate limit 是每分钟 60 次。",
        user_id="e2e-life-research",
        workspace_id=workspace_id,
        source_type="document",
    )
    result = workspace.ingest_research_event(
        topic="Kappa API",
        title="Kappa API rate limit update",
        summary="Kappa API rate limit 是每分钟 120 次。",
        user_id="e2e-life-research",
        workspace_id=workspace_id,
        source_ref="fixture://kappa-research",
    )
    relations = workspace.store.list_knowledge_relations(workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-008",
        branch="life",
        research_event_count=len(workspace.store.list_research_events(workspace_id)),
        claim_admission_decision_count=len(result.ingest_result.admission_decisions),
        knowledge_relation_count=len(relations),
        relation_types=tuple(relation.relation_type for relation in relations),
    )


def _run_lifecycle_review_gap(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-review-gap"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "Redis 支持缓存。",
        user_id="e2e-life-review-gap",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.ingest_text(
        "Orion 功能默认开启。",
        user_id="e2e-life-review-gap",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.ingest_text(
        "Orion 功能默认关闭。",
        user_id="e2e-life-review-gap",
        workspace_id=workspace_id,
        source_type="document",
    )
    plan = workspace.plan_review_and_gaps(workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-009",
        branch="life",
        review_item_count=len(plan.review_items),
        knowledge_gap_count=len(plan.knowledge_gaps),
    )


def _run_lifecycle_graph_projection(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-graph"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "Redis 支持缓存。",
        user_id="e2e-life-graph",
        workspace_id=workspace_id,
        source_type="document",
    )
    result = workspace.project_knowledge_graph(workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-010",
        branch="life",
        graph_projection_count=len(result.projections),
        graph_projection_backlink_ok=result.backlink_ok,
    )


def _run_lifecycle_sem_compound_claims(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-compound"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "Atlas 使用蓝绿发布，并且发布时切换到绿色环境。",
        user_id="e2e-life-sem-compound",
        workspace_id=workspace_id,
        source_type="document",
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-001",
        branch="life_semantic",
        claim_admission_decision_count=len(ingest.admission_decisions),
        claim_states=tuple(claim.state for claim in ingest.claims),
        claim_quality_passed_count=sum(1 for claim in ingest.claims if claim.quality_gate.passed),
        claim_without_evidence_ref_count=sum(1 for claim in ingest.claims if not claim.evidence_refs),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_synonym_grounding(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-synonym"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "蓝绿发布的切流量步骤是将请求切换到绿色环境。",
        user_id="e2e-life-sem-synonym",
        workspace_id=workspace_id,
        source_type="document",
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-002",
        branch="life_semantic",
        grounding_run_count=len(ingest.grounding_runs),
        claim_states=tuple(claim.state for claim in ingest.claims),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_coverage_manifest(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-coverage"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_knowledge(
        "第一页：Feature X 在规范 A 默认开启。[OMITTED:规范B默认值]",
        user_id="e2e-life-sem-coverage",
        workspace_id=workspace_id,
        source_type="document",
    )
    answer = workspace.answer_with_evidence("Feature X 默认状态是什么？", workspace_id=workspace_id, limit=1)
    manifest = ingest.extraction_run.coverage_manifest or {}
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-003",
        branch="life_semantic",
        answer=answer.answer,
        citations_count=len(answer.citations),
        evidence_coverage=answer.evidence_coverage,
        missing_section_count=len(answer.missing_sections),
        coverage_manifest_omitted_count=int(manifest.get("omitted_region_count") or 0),
        semantic_component_names=_semantic_components(workspace),
    )


def _run_lifecycle_sem_scope_non_conflict(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-scope"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "服务端规范 A 中 Feature X 默认开启。",
        user_id="e2e-life-sem-scope",
        workspace_id=workspace_id,
        source_type="document",
    )
    ingest = workspace.ingest_text(
        "服务端规范 B 中 Feature X 默认关闭。",
        user_id="e2e-life-sem-scope",
        workspace_id=workspace_id,
        source_type="document",
    )
    relations = workspace.store.list_knowledge_relations(workspace_id, limit=20)
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-004",
        branch="life_semantic",
        relation_types=tuple(relation.relation_type for relation in relations),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


class _E2EConflictJudge:
    name = "e2e-structured-conflict-judge"

    def judge(
        self,
        candidate: ClaimRelationCandidate,
        new_claim: Claim,
        existing_claim: Claim,
    ) -> ClaimRelationAdjudication:
        return ClaimRelationAdjudication(
            relation_type="conflict",
            confidence=0.95,
            rationale="same-scope default state cannot be both enabled and disabled",
            requires_decision=True,
        )


def _run_lifecycle_sem_true_conflict(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-true-conflict"
    workspace = _workspace_service(service)
    previous_judge = workspace.relation_judge
    workspace.relation_judge = _E2EConflictJudge()
    try:
        first = workspace.ingest_text(
            "Feature X 默认开启。",
            user_id="e2e-life-sem-true-conflict",
            workspace_id=workspace_id,
            source_type="document",
        )
        second = workspace.ingest_text(
            "Feature X 默认关闭。",
            user_id="e2e-life-sem-true-conflict",
            workspace_id=workspace_id,
            source_type="document",
        )
    finally:
        workspace.relation_judge = previous_judge
    relations = workspace.store.list_knowledge_relations(workspace_id, limit=20)
    claims = [*first.claims, *second.claims]
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-005",
        branch="life_semantic",
        knowledge_relation_count=len(relations),
        relation_types=tuple(relation.relation_type for relation in relations),
        claim_states=tuple(workspace.store.get_claim(claim.claim_id).state for claim in claims if workspace.store.get_claim(claim.claim_id)),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=(*_grounding_verifiers(first), *_grounding_verifiers(second)),
    )


def _run_lifecycle_sem_table_evidence(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-table"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "| 服务 | 字段 | 默认值 |\n| Feature X | 灰度开关 | 默认开启 |",
        user_id="e2e-life-sem-table",
        workspace_id=workspace_id,
        source_type="document",
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-006",
        branch="life_semantic",
        table_evidence_block_count=sum(1 for block in ingest.evidence_blocks if block.block_type == "table"),
        claim_quality_passed_count=sum(1 for claim in ingest.claims if claim.quality_gate.passed),
        claim_without_evidence_ref_count=sum(1 for claim in ingest.claims if not claim.evidence_refs),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_answer_claim_not_saved(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-answer-claim"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "Atlas 发布时切换到绿色环境。",
        user_id="e2e-life-sem-answer-claim",
        workspace_id=workspace_id,
        source_type="document",
    )
    before = len(workspace.store.list_claims(workspace_id, limit=100))
    answer = workspace.answer_with_evidence("Atlas 发布时切到哪里？", workspace_id=workspace_id)
    after = len(workspace.store.list_claims(workspace_id, limit=100))
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-007",
        branch="life_semantic",
        citations_count=len(answer.citations),
        answer_claim_saved_count=answer.answer_claim_saved_count,
        active_claim_count_delta=max(0, after - before),
        semantic_component_names=_semantic_components(workspace),
    )


def _run_lifecycle_sem_claim_ask_increment(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-ask"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "服务端规范 A 中 Feature X 默认开启。服务端规范 B 中 Feature X 默认关闭。",
        user_id="e2e-life-sem-ask",
        workspace_id=workspace_id,
        source_type="document",
    )
    answer = workspace.answer_with_evidence("规范 A 中 Feature X 默认状态是什么？", workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-008",
        branch="life_semantic",
        answer=answer.answer,
        citations_count=len(answer.citations),
        citation_evidence_span_ids=tuple(citation.evidence_span_id for citation in answer.citations),
        citation_evidence_block_ids=tuple(citation.evidence_block_id for citation in answer.citations),
        citation_artifact_ids=tuple(citation.artifact_id for citation in answer.citations),
        claim_quality_passed_count=sum(1 for claim in ingest.claims if claim.quality_gate.passed),
        claim_without_evidence_ref_count=sum(1 for claim in ingest.claims if not claim.evidence_refs),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_solidify(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-solidify"
    workspace = _workspace_service(service)
    result = workspace.solidify_conversation(
        [
            ConversationMessage(role="user", content="Atlas 项目的部署窗口是每周三上午十点。"),
            ConversationMessage(role="assistant", content="这可能意味着你们希望避开周末发布，但这个推断需要你确认。"),
        ],
        user_id="e2e-life-sem-solidify",
        workspace_id=workspace_id,
    )
    assistant_active = sum(
        1
        for claim in result.ingest_result.claims
        if claim.source_role == "assistant_inference" and claim.state == "active"
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-009",
        branch="life_semantic",
        user_claim_count=result.user_claim_count,
        claim_states=tuple(claim.state for claim in result.ingest_result.claims),
        assistant_inference_active_count=assistant_active,
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(result.ingest_result),
    )


def _run_lifecycle_sem_research_impact(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-research-impact"
    workspace = _workspace_service(service)
    workspace.ingest_text(
        "Kappa API rate limit 是每分钟 60 次。",
        user_id="e2e-life-sem-research-impact",
        workspace_id=workspace_id,
        source_type="conversation",
        created_by="user",
    )
    result = workspace.ingest_research_event(
        topic="Kappa API",
        title="Kappa API rate limit update",
        summary="官方公告说明 Kappa API rate limit 是每分钟 120 次。",
        user_id="e2e-life-sem-research-impact",
        workspace_id=workspace_id,
        source_ref="https://example.com/kappa",
    )
    relations = workspace.store.list_knowledge_relations(workspace_id, limit=20)
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-010",
        branch="life_semantic",
        research_event_count=1 if result.event.research_event_id else 0,
        knowledge_relation_count=len(relations),
        relation_types=tuple(relation.relation_type for relation in relations),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(result.ingest_result),
    )


def _run_lifecycle_sem_review_eligibility(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-review"
    workspace = _workspace_service(service)
    valid = workspace.ingest_text(
        "Redis 支持缓存。",
        user_id="e2e-life-sem-review",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.ingest_text(
        "用户可能喜欢夜间发布。",
        user_id="e2e-life-sem-review",
        workspace_id=workspace_id,
        source_type="conversation",
        created_by="assistant",
    )
    workspace.ingest_text(
        "Orion 功能默认开启。",
        user_id="e2e-life-sem-review",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.ingest_text(
        "Orion 功能默认关闭。",
        user_id="e2e-life-sem-review",
        workspace_id=workspace_id,
        source_type="document",
    )
    plan = workspace.plan_review_and_gaps(workspace_id=workspace_id)
    reviewed_claims = [
        workspace.store.get_claim(item.claim_id)
        for item in plan.review_items
    ]
    invalid_review = sum(
        1 for claim in reviewed_claims
        if claim is None or not claim.quality_gate.passed or claim.source_role == "assistant_inference"
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-011",
        branch="life_semantic",
        review_item_count=len(plan.review_items),
        knowledge_gap_count=len(plan.knowledge_gaps),
        review_invalid_claim_count=invalid_review,
        claim_quality_passed_count=sum(1 for claim in valid.claims if claim.quality_gate.passed),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(valid),
    )


def _run_lifecycle_sem_graph_eligibility(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-graph"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "Redis 支持缓存。",
        user_id="e2e-life-sem-graph",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.ingest_text(
        "用户可能喜欢夜间发布。",
        user_id="e2e-life-sem-graph",
        workspace_id=workspace_id,
        source_type="conversation",
        created_by="assistant",
    )
    result = workspace.project_knowledge_graph(workspace_id=workspace_id)
    violations = 0
    for projection in result.projections:
        claim = workspace.store.get_claim(projection.source_claim_id)
        if claim is None or not claim.quality_gate.passed or claim.source_role == "assistant_inference":
            violations += 1
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-012",
        branch="life_semantic",
        graph_projection_count=len(result.projections),
        graph_projection_backlink_ok=result.backlink_ok,
        projection_eligibility_violation_count=violations,
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_delete_privacy(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-delete"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "Delta 的 api key 是 sk-secret-123。",
        user_id="e2e-life-sem-delete",
        workspace_id=workspace_id,
        source_type="document",
    )
    workspace.project_knowledge_graph(workspace_id=workspace_id)
    result = workspace.delete_artifact_cascade(ingest.artifact.artifact_id)
    states = tuple(
        workspace.store.get_claim(claim_id).state
        for claim_id in result.affected_claim_ids
        if workspace.store.get_claim(claim_id) is not None
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-014",
        branch="life_semantic",
        deleted_claim_count=len(result.affected_claim_ids),
        claim_states=states,
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


def _run_lifecycle_sem_replay_diff(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-replay"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "Orion 版本 v2 默认开启。",
        user_id="e2e-life-sem-replay",
        workspace_id=workspace_id,
        source_type="document",
    )
    diff = workspace.replay_semantic_extraction_diff(
        ingest.artifact.artifact_id,
        prompt_version="replay-v2",
    )
    diff_count = (
        len(diff.added_claims)
        + len(diff.removed_claims)
        + len(diff.changed_scope_claims)
        + len(diff.changed_support_claims)
    )
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-015",
        branch="life_semantic",
        replay_diff_count=diff_count,
        semantic_component_names=_semantic_components(workspace),
    )


def _run_lifecycle_sem_correction(service: AgentService) -> E2EQualityRun:
    workspace_id = "e2e-life-sem-correction"
    workspace = _workspace_service(service)
    ingest = workspace.ingest_text(
        "Atlas 部署窗口是周三上午十点。",
        user_id="e2e-life-sem-correction",
        workspace_id=workspace_id,
        source_type="document",
    )
    old_claim = ingest.claims[0]
    correction = workspace.correct_claim(
        old_claim.claim_id,
        "Atlas 部署窗口是周四上午十点。",
        user_id="e2e-life-sem-correction",
    )
    answer = workspace.answer_with_evidence("Atlas 部署窗口是什么时候？", workspace_id=workspace_id)
    return E2EQualityRun(
        case_id="E2E-LIFE-SEM-013",
        branch="life_semantic",
        answer=answer.answer,
        knowledge_relation_count=1,
        relation_types=(correction.relation.relation_type,),
        claim_states=(correction.old_claim.state, correction.new_claim.state),
        semantic_component_names=_semantic_components(workspace),
        grounding_verifiers=_grounding_verifiers(ingest),
    )


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
        note_count=_workspace_note_count(service, user_id),
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
        note_count=_workspace_note_count(service, user_id),
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
        note_count=_workspace_note_count(service, user_id),
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
        note_count=_workspace_note_count(service, user_id),
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
        note_count=_workspace_note_count(service, user_id),
        dependency_edges=dependency_edges,
    )


def _run_github_mcp_search_code_question(service: AgentService) -> E2EQualityRun:
    return _run_github_mcp_prompt(
        service,
        case_id="E2E-GH-MCP-001",
        prompt="在 github/github-mcp-server 里 search_code 是在哪里实现的？",
        expected_tool_name="github.search_code",
    )


def _run_github_mcp_file_question(service: AgentService) -> E2EQualityRun:
    return _run_github_mcp_prompt(
        service,
        case_id="E2E-GH-MCP-002",
        prompt="帮我读取 github/github-mcp-server 的 README.md，说明它支持哪些 toolsets",
        expected_tool_name="github.get_file_contents",
    )


def _run_github_mcp_repo_search_question(service: AgentService) -> E2EQualityRun:
    return _run_github_mcp_prompt(
        service,
        case_id="E2E-GH-MCP-003",
        prompt="搜索 GitHub 上 stars:>10000 topic:agent language:python 的仓库",
        expected_tool_name="github.search_repositories",
    )


def _run_github_mcp_repo_qualified_code_question(service: AgentService) -> E2EQualityRun:
    return _run_github_mcp_prompt(
        service,
        case_id="E2E-GH-MCP-004",
        prompt="repo:openai/openai-python filename:client.py 里 client 初始化逻辑在哪？",
        expected_tool_name="github.search_code",
    )


def _run_github_mcp_local_memory_question(service: AgentService) -> E2EQualityRun:
    _register_fake_github_mcp_tools(service)
    prompt = "我之前关于 Agent tool use 的笔记里有哪些结论？"
    user_id = "e2e-e2e-gh-mcp-005"
    result = service.execute_entry(EntryInput(
        text=prompt,
        user_id=user_id,
        session_id="e2e-gh-mcp-005-session",
        source_platform="e2e_quality",
    ))
    snapshot = service.get_run_snapshot(result.run_id or "")
    audit_events = service.query_tool_audit(
        user_id=user_id,
        run_id=result.run_id,
        limit=20,
    ) if result.run_id else []
    return E2EQualityRun(
        case_id="E2E-GH-MCP-005",
        branch="github_mcp",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(str(step.get("step_id") or "") for step in (result.steps or [])),
        answer=result.reply_text or "",
        tool_names=tuple(reversed([str(event["tool_name"]) for event in audit_events])),
        tool_call_trace_count=len(audit_events),
        failed_tool_call_count=sum(
            1 for event in audit_events if not bool(event.get("artifact_ok"))
        ),
        tool_error_kinds=tuple(
            str(event.get("error_kind"))
            for event in audit_events
            if event.get("error_kind")
        ),
        metadata={
            "prompt": prompt,
            "audit_events": audit_events,
        },
    )


def _run_github_mcp_prompt(
    service: AgentService,
    *,
    case_id: str,
    prompt: str,
    expected_tool_name: str,
) -> E2EQualityRun:
    from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

    _register_fake_github_mcp_tools(service)
    user_id = f"e2e-{case_id.lower()}"
    react_calls: list[dict[str, object]] = []

    def _mock_github_react(_prompt, _deps, allowed):
        call_index = len(react_calls)
        react_calls.append({
            "allowed": sorted(str(tool_name) for tool_name in allowed),
            "expected_tool_name": expected_tool_name,
        })
        if call_index == 0:
            if expected_tool_name not in allowed:
                return _NativeReactOutcome(parse_failed=True)
            return _NativeReactOutcome(
                thought="需要通过 GitHub MCP 读取远程仓库证据。",
                tool_name=expected_tool_name,
                tool_input=_github_mcp_tool_args(expected_tool_name, prompt),
                native_call_id=f"{case_id}:github-react:1",
            )
        return _NativeReactOutcome(
            done=True,
            thought="GitHub MCP 工具已经返回证据，可以结束本步骤。",
            result={
                "answer": (
                    f"已通过 {expected_tool_name} 读取 GitHub 远程仓库证据，"
                    f"可回答：{prompt}"
                )
            },
        )

    with patch(
        "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
        _mock_github_react,
    ):
        result = service.execute_entry(EntryInput(
            text=prompt,
            user_id=user_id,
            session_id=f"{case_id.lower()}-session",
            source_platform="e2e_quality",
        ))

    snapshot = service.get_run_snapshot(result.run_id or "")
    audit_events = service.query_tool_audit(
        user_id=user_id,
        run_id=result.run_id,
        limit=20,
    ) if result.run_id else []
    tool_names = tuple(reversed([str(event["tool_name"]) for event in audit_events]))
    return E2EQualityRun(
        case_id=case_id,
        branch="github_mcp",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(str(step.get("step_id") or "") for step in (result.steps or [])),
        answer=result.reply_text or "",
        tool_names=tool_names,
        tool_call_trace_count=len(audit_events),
        failed_tool_call_count=sum(
            1 for event in audit_events if not bool(event.get("artifact_ok"))
        ),
        tool_error_kinds=tuple(
            str(event.get("error_kind"))
            for event in audit_events
            if event.get("error_kind")
        ),
        metadata={
            "prompt": prompt,
            "react_calls": react_calls,
            "audit_events": audit_events,
        },
    )


def _register_fake_github_mcp_tools(service: AgentService) -> None:
    for github_tool in _build_fake_github_mcp_tools():
        service.tool_executor.register(github_tool)


def _build_fake_github_mcp_tools():
    @tool(
        "github.search_code",
        description="Search code in GitHub repositories that the configured token can read.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="github:repo:read",
            timeout_seconds=20.0,
            max_retries=1,
            rate_limit_per_minute=30,
            allowed_domains=("github.com",),
        ),
    )
    def github_search_code(query: str, user_id: str = "default", run_id: str | None = None):
        return tool_response(tool_success({
            "provider": "github_mcp_fake",
            "results": [{
                "title": "github-mcp-server search_code implementation",
                "content": f"Matched code query: {query}",
                "url": "https://github.com/github/github-mcp-server/search?q=search_code",
            }],
        }))

    @tool(
        "github.get_file_contents",
        description="Read file contents from a GitHub repository that the configured token can read.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="github:repo:read",
            timeout_seconds=20.0,
            max_retries=1,
            rate_limit_per_minute=30,
            allowed_domains=("github.com",),
        ),
    )
    def github_get_file_contents(
        owner: str,
        repo: str,
        path: str,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        return tool_response(tool_success({
            "provider": "github_mcp_fake",
            "owner": owner,
            "repo": repo,
            "path": path,
            "content": f"# {repo}\n\nFake file content for {path}.",
            "url": f"https://github.com/{owner}/{repo}/blob/main/{path}",
        }))

    @tool(
        "github.search_repositories",
        description="Search GitHub repositories visible to the configured token.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="github:repo:read",
            timeout_seconds=20.0,
            max_retries=1,
            rate_limit_per_minute=30,
            allowed_domains=("github.com",),
        ),
    )
    def github_search_repositories(query: str, user_id: str = "default", run_id: str | None = None):
        return tool_response(tool_success({
            "provider": "github_mcp_fake",
            "results": [{
                "name": "example/agent",
                "description": f"Repository matched query: {query}",
                "url": "https://github.com/example/agent",
            }],
        }))

    return [
        github_search_code,
        github_get_file_contents,
        github_search_repositories,
    ]


def _github_mcp_tool_args(tool_name: str, prompt: str) -> dict[str, object]:
    if tool_name == "github.get_file_contents":
        owner, repo = _github_repo_from_prompt(prompt, default=("github", "github-mcp-server"))
        return {"owner": owner, "repo": repo, "path": _github_path_from_prompt(prompt)}
    if tool_name == "github.search_repositories":
        return {"query": prompt}
    return {"query": prompt}


def _github_repo_from_prompt(
    prompt: str,
    *,
    default: tuple[str, str],
) -> tuple[str, str]:
    import re

    match = re.search(r"(?:github\.com/|repo:)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", prompt)
    if match:
        return match.group(1), match.group(2)
    return default


def _github_path_from_prompt(prompt: str) -> str:
    import re

    match = re.search(r"\b([A-Za-z0-9_.\-/]+(?:README\.md|\.md|\.py|\.ts|\.tsx|\.js|\.go))\b", prompt)
    if match:
        path = match.group(1)
        return path.rsplit("/", 1)[-1] if path.startswith("github/") else path
    return "README.md"


def _run_notion_mcp_search_question(service: AgentService) -> E2EQualityRun:
    return _run_notion_mcp_prompt(
        service,
        case_id="E2E-NOTION-MCP-001",
        prompt="在 Notion 里搜索 Orion 项目的会议纪要",
        expected_tool_name="notion.search",
    )


def _run_notion_mcp_page_question(service: AgentService) -> E2EQualityRun:
    return _run_notion_mcp_prompt(
        service,
        case_id="E2E-NOTION-MCP-002",
        prompt="读取 Notion 页面 1a6b35e6e67f802fa7e1d27686f017f2 并总结内容",
        expected_tool_name="notion.retrieve_page_markdown",
    )


def _run_notion_mcp_write_request(service: AgentService) -> E2EQualityRun:
    _register_fake_notion_mcp_tools(service)
    prompt = "在 Notion 创建一个 Orion 项目总结页面"
    user_id = "e2e-e2e-notion-mcp-003"
    result = service.execute_entry(EntryInput(
        text=prompt,
        user_id=user_id,
        session_id="e2e-notion-mcp-003-session",
        source_platform="e2e_quality",
    ))
    snapshot = service.get_run_snapshot(result.run_id or "")
    audit_events = service.query_tool_audit(
        user_id=user_id,
        run_id=result.run_id,
        limit=20,
    ) if result.run_id else []
    return E2EQualityRun(
        case_id="E2E-NOTION-MCP-003",
        branch="notion_mcp",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(str(step.get("step_id") or "") for step in (result.steps or [])),
        answer=result.reply_text or "",
        tool_names=tuple(reversed([str(event["tool_name"]) for event in audit_events])),
        tool_call_trace_count=len(audit_events),
        failed_tool_call_count=sum(
            1 for event in audit_events if not bool(event.get("artifact_ok"))
        ),
        tool_error_kinds=tuple(
            str(event.get("error_kind"))
            for event in audit_events
            if event.get("error_kind")
        ),
        metadata={
            "prompt": prompt,
            "audit_events": audit_events,
        },
    )


def _run_notion_mcp_prompt(
    service: AgentService,
    *,
    case_id: str,
    prompt: str,
    expected_tool_name: str,
) -> E2EQualityRun:
    from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

    _register_fake_notion_mcp_tools(service)
    user_id = f"e2e-{case_id.lower()}"
    react_calls: list[dict[str, object]] = []

    def _mock_notion_react(_prompt, _deps, allowed):
        call_index = len(react_calls)
        react_calls.append({
            "allowed": sorted(str(tool_name) for tool_name in allowed),
            "expected_tool_name": expected_tool_name,
        })
        if call_index == 0:
            if expected_tool_name not in allowed:
                return _NativeReactOutcome(parse_failed=True)
            return _NativeReactOutcome(
                thought="需要通过 Notion MCP 读取 workspace 证据。",
                tool_name=expected_tool_name,
                tool_input=_notion_mcp_tool_args(expected_tool_name, prompt),
                native_call_id=f"{case_id}:notion-react:1",
            )
        return _NativeReactOutcome(
            done=True,
            thought="Notion MCP 工具已经返回证据，可以结束本步骤。",
            result={
                "answer": (
                    f"已通过 {expected_tool_name} 读取 Notion workspace 证据，"
                    f"可回答：{prompt}"
                )
            },
        )

    with patch(
        "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
        _mock_notion_react,
    ):
        result = service.execute_entry(EntryInput(
            text=prompt,
            user_id=user_id,
            session_id=f"{case_id.lower()}-session",
            source_platform="e2e_quality",
        ))

    snapshot = service.get_run_snapshot(result.run_id or "")
    audit_events = service.query_tool_audit(
        user_id=user_id,
        run_id=result.run_id,
        limit=20,
    ) if result.run_id else []
    tool_names = tuple(reversed([str(event["tool_name"]) for event in audit_events]))
    return E2EQualityRun(
        case_id=case_id,
        branch="notion_mcp",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(str(step.get("step_id") or "") for step in (result.steps or [])),
        answer=result.reply_text or "",
        tool_names=tool_names,
        tool_call_trace_count=len(audit_events),
        failed_tool_call_count=sum(
            1 for event in audit_events if not bool(event.get("artifact_ok"))
        ),
        tool_error_kinds=tuple(
            str(event.get("error_kind"))
            for event in audit_events
            if event.get("error_kind")
        ),
        metadata={
            "prompt": prompt,
            "react_calls": react_calls,
            "audit_events": audit_events,
        },
    )


def _register_fake_notion_mcp_tools(service: AgentService) -> None:
    for notion_tool in _build_fake_notion_mcp_tools():
        service.tool_executor.register(notion_tool)


def _build_fake_notion_mcp_tools():
    @tool(
        "notion.search",
        description="Search pages and data sources visible to the configured Notion integration.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="notion:workspace:read",
            timeout_seconds=20.0,
            max_retries=1,
            rate_limit_per_minute=30,
            allowed_domains=("notion.so", "api.notion.com"),
        ),
    )
    def notion_search(query: str, user_id: str = "default", run_id: str | None = None):
        return tool_response(tool_success({
            "provider": "notion_mcp_fake",
            "results": [{
                "title": "Orion meeting notes",
                "content": f"Matched Notion query: {query}",
                "url": "https://www.notion.so/orion-meeting-notes",
            }],
        }))

    @tool(
        "notion.retrieve_page_markdown",
        description="Read a Notion page's full content as Markdown.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="notion:workspace:read",
            timeout_seconds=20.0,
            max_retries=1,
            rate_limit_per_minute=30,
            allowed_domains=("notion.so", "api.notion.com"),
        ),
    )
    def notion_retrieve_page_markdown(
        page_id: str,
        include_transcript: bool = False,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        return tool_response(tool_success({
            "provider": "notion_mcp_fake",
            "page_id": page_id,
            "include_transcript": include_transcript,
            "content": f"# Notion page {page_id}\n\nFake markdown page content.",
            "url": f"https://www.notion.so/{page_id}",
        }))

    return [notion_search, notion_retrieve_page_markdown]


def _notion_mcp_tool_args(tool_name: str, prompt: str) -> dict[str, object]:
    if tool_name == "notion.retrieve_page_markdown":
        return {
            "page_id": _notion_page_id_from_prompt(prompt),
            "include_transcript": "会议" in prompt or "meeting" in prompt.lower(),
        }
    return {"query": prompt}


def _notion_page_id_from_prompt(prompt: str) -> str:
    import re

    match = re.search(r"\b([0-9a-fA-F]{32}|[0-9a-fA-F-]{36})\b", prompt)
    if match:
        return match.group(1).replace("-", "")
    return "1a6b35e6e67f802fa7e1d27686f017f2"


def _run_gpt_researcher_a2a_question(service: AgentService) -> E2EQualityRun:
    _register_fake_gpt_researcher_a2a_tool(service)
    prompt = "用 GPT Researcher A2A 调研 Agent2Agent 协议采用情况，并生成研究报告"
    user_id = "e2e-e2e-gptr-a2a-001"
    result = service.execute_entry(EntryInput(
        text=prompt,
        user_id=user_id,
        session_id="e2e-gptr-a2a-001-session",
        source_platform="e2e_quality",
    ))
    snapshot = service.get_run_snapshot(result.run_id or "")
    audit_events = service.query_tool_audit(
        user_id=user_id,
        run_id=result.run_id,
        limit=20,
    ) if result.run_id else []
    return E2EQualityRun(
        case_id="E2E-GPTR-A2A-001",
        branch="gpt_researcher_a2a",
        intents=tuple(result.intents),
        run_status=result.run_status or "",
        workflow_id=snapshot.workflow_id if snapshot else "",
        step_ids=tuple(str(step.get("step_id") or "") for step in (result.steps or [])),
        answer=result.reply_text or "",
        tool_names=tuple(reversed([str(event["tool_name"]) for event in audit_events])),
        tool_call_trace_count=len(audit_events),
        failed_tool_call_count=sum(
            1 for event in audit_events if not bool(event.get("artifact_ok"))
        ),
        tool_error_kinds=tuple(
            str(event.get("error_kind"))
            for event in audit_events
            if event.get("error_kind")
        ),
        metadata={
            "prompt": prompt,
            "audit_events": audit_events,
        },
    )


def _register_fake_gpt_researcher_a2a_tool(service: AgentService) -> None:
    @tool(
        "gpt_researcher.a2a_research",
        description="Fake GPT Researcher A2A research report tool for full-chain e2e.",
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="medium",
            side_effects=("external_network",),
            permission_scope="a2a:gpt_researcher:research",
            timeout_seconds=120.0,
            max_retries=1,
            retry_backoff_seconds=1.0,
            rate_limit_per_minute=5,
            allowed_domains=("localhost", "127.0.0.1"),
        ),
    )
    def gpt_researcher_a2a_research(
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        return tool_response(tool_success({
            "provider": "gpt_researcher_a2a_fake",
            "task_id": "fake-a2a-task-1",
            "context_id": "fake-a2a-context-1",
            "state": "completed",
            "report": (
                "# GPT Researcher A2A Report\n\n"
                f"Agent2Agent adoption research for: {topic}\n\n"
                "The fake report proves the full entry -> router -> workflow -> "
                "ToolGateway -> audit chain invoked GPT Researcher A2A."
            ),
            "metadata": {
                "report_type": report_type,
                "report_source": report_source,
                "tone": tone,
                "max_search_results": max_search_results,
                "user_id": user_id,
                "run_id": run_id,
            },
            "artifacts": [],
        }))

    service.tool_executor.register(gpt_researcher_a2a_research)


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
    ("E2E-LIFE-001", _run_lifecycle_artifact_evidence),
    ("E2E-LIFE-001B", _run_lifecycle_partial_ingest),
    ("E2E-LIFE-002", _run_lifecycle_candidate_guard),
    ("E2E-LIFE-003", _run_lifecycle_p0),
    ("E2E-LIFE-004", _run_lifecycle_no_evidence),
    ("E2E-LIFE-004B", _run_lifecycle_partial_coverage),
    ("E2E-LIFE-005", _run_lifecycle_solidify),
    ("E2E-LIFE-006", _run_lifecycle_conflict),
    ("E2E-LIFE-007", _run_lifecycle_decision_policy),
    ("E2E-LIFE-008", _run_lifecycle_research),
    ("E2E-LIFE-009", _run_lifecycle_review_gap),
    ("E2E-LIFE-010", _run_lifecycle_graph_projection),
    ("E2E-LIFE-SEM-001", _run_lifecycle_sem_compound_claims),
    ("E2E-LIFE-SEM-002", _run_lifecycle_sem_synonym_grounding),
    ("E2E-LIFE-SEM-003", _run_lifecycle_sem_coverage_manifest),
    ("E2E-LIFE-SEM-004", _run_lifecycle_sem_scope_non_conflict),
    ("E2E-LIFE-SEM-005", _run_lifecycle_sem_true_conflict),
    ("E2E-LIFE-SEM-006", _run_lifecycle_sem_table_evidence),
    ("E2E-LIFE-SEM-007", _run_lifecycle_sem_answer_claim_not_saved),
    ("E2E-LIFE-SEM-008", _run_lifecycle_sem_claim_ask_increment),
    ("E2E-LIFE-SEM-009", _run_lifecycle_sem_solidify),
    ("E2E-LIFE-SEM-010", _run_lifecycle_sem_research_impact),
    ("E2E-LIFE-SEM-011", _run_lifecycle_sem_review_eligibility),
    ("E2E-LIFE-SEM-012", _run_lifecycle_sem_graph_eligibility),
    ("E2E-LIFE-SEM-013", _run_lifecycle_sem_correction),
    ("E2E-LIFE-SEM-014", _run_lifecycle_sem_delete_privacy),
    ("E2E-LIFE-SEM-015", _run_lifecycle_sem_replay_diff),
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
    ("E2E-GH-MCP-001", _run_github_mcp_search_code_question),
    ("E2E-GH-MCP-002", _run_github_mcp_file_question),
    ("E2E-GH-MCP-003", _run_github_mcp_repo_search_question),
    ("E2E-GH-MCP-004", _run_github_mcp_repo_qualified_code_question),
    ("E2E-GH-MCP-005", _run_github_mcp_local_memory_question),
    ("E2E-NOTION-MCP-001", _run_notion_mcp_search_question),
    ("E2E-NOTION-MCP-002", _run_notion_mcp_page_question),
    ("E2E-NOTION-MCP-003", _run_notion_mcp_write_request),
    ("E2E-GPTR-A2A-001", _run_gpt_researcher_a2a_question),
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
        "tool_names": run.tool_names,
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
        matches_count=max(
            len(ask_result.matches),
            len(getattr(ask_result, "match_refs", []) or []),
        ) if ask_result else 0,
        citations_count=len(ask_result.citations) if ask_result else 0,
        evidence_count=max(len(ask_result.evidence), len(ask_result.citations)) if ask_result else 0,
        llm_call_count=llm_call_count,
        verification_score=(
            float(getattr(verification, "evidence_score", 0.0) or 0.0)
            or (1.0 if (ask_result and ask_result.citations) else 0.0)
        ),
        grounding_status=str(
            getattr(repair, "final_grounding_status", "")
            or ((ask_result.repair_telemetry or {}).get("grounding_status", "") if ask_result else "")
        ),
        claim_statuses=tuple(
            str(getattr(item, "status", ""))
            for item in (getattr(verification, "claim_checks", []) if verification else [])
        ),
        web_tried=bool(getattr(ctx, "web_tried", False)) if ctx else False,
        note_count=note_count,
        dependency_edges=dependency_edges,
    )


def _workspace_note_count(service: AgentService, user_id: str) -> int:
    return len(
        service.workspace_service.store.list_knowledge_items(
            user_id,
            state="active",
            limit=500,
        )
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
        matches_count=max(
            len(ask_result.matches),
            len(getattr(ask_result, "match_refs", []) or []),
        ) if ask_result else 0,
        citations_count=len(ask_result.citations) if ask_result else 0,
        evidence_count=max(len(ask_result.evidence), len(ask_result.citations)) if ask_result else 0,
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

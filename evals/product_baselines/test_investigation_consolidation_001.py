"""INVESTIGATION-CONSOLIDATION-001 current-interaction demand baseline."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import perf_counter
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

import pytest

from evals.e2e_quality.container_resources import (
    DockerStatsSampler,
    discover_gpt_researcher_container,
)
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.infra.storage.postgres_agent_run_store import (
    PostgresAgentRunStore,
)
from personal_agent.kernel.contracts.agent import (
    CAPACITY_OCCUPYING_AGENT_RUN_STATUSES,
)


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "INVESTIGATION-CONSOLIDATION-001-CURRENT"
_REVISION_CASE_ID = "INVESTIGATION-CONSOLIDATION-001-REVISION"
_BACKGROUND_CASE_ID = "INVESTIGATION-CONSOLIDATION-001-BACKGROUND"
_REPETITIONS = 4
_REVISION_REPETITIONS = 5
_BACKGROUND_REPETITIONS = 5
_RESOURCE_EVIDENCE_ENV = "PERSONAL_AGENT_INVESTIGATION_RESOURCE_EVIDENCE"


def _resource_evidence_enabled() -> bool:
    return os.getenv(_RESOURCE_EVIDENCE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    request: str
    required_terms: tuple[str, ...]
    official_source_groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class _RevisionScenario:
    scenario_id: str
    initial_request: str
    continue_request: str
    required_terms: tuple[str, ...]
    withdrawn_plan_terms: tuple[str, ...]
    official_source_groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class _BackgroundScenario:
    scenario_id: str
    request: str
    required_terms: tuple[str, ...]
    official_source_groups: tuple[tuple[str, ...], ...]


_SCENARIOS = (
    _Scenario(
        scenario_id="tool-protocol-boundary",
        request=(
            "请实际查阅 OpenAI 官方工具文档和 MCP 官方 tools 规范，在这次回复中比较"
            "工具选择、权限边界和结果契约，给出带官方 URL 的中文结论。"
        ),
        required_terms=("工具选择", "权限边界", "结果契约"),
        official_source_groups=(
            (
                "developers.openai.com",
                "platform.openai.com",
                "openai.github.io",
                "openai.com",
            ),
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
        ),
    ),
    _Scenario(
        scenario_id="durable-recovery-boundary",
        request=(
            "请实际查阅 Temporal 和 Restate 官方文档，在这次回复中比较重试、业务幂等"
            "和恢复后对账边界，给出带官方 URL 的中文结论。"
        ),
        required_terms=("重试", "幂等", "恢复"),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
    _Scenario(
        scenario_id="plan-progress-recovery",
        request=(
            "请实际查阅 Gemini CLI 官方资料和 Hermes Agent 官方仓库，在这次回复中比较"
            "复杂任务的计划、进度更新和恢复方式，给出带官方 URL 的中文结论。"
        ),
        required_terms=("计划", "进度", "恢复"),
        official_source_groups=(
            ("geminicli.com", "github.com/google-gemini/gemini-cli"),
            (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            ),
        ),
    ),
    _Scenario(
        scenario_id="tool-selection-and-completion",
        request=(
            "请实际查阅 OpenAI Agents SDK 和 Anthropic 工具使用官方文档，在这次回复中"
            "比较工具选择、调用治理和任务完成判断，给出带官方 URL 的中文结论。"
        ),
        required_terms=("工具选择", "调用", "完成"),
        official_source_groups=(
            ("openai.github.io", "developers.openai.com", "openai.com"),
            ("docs.anthropic.com", "platform.claude.com"),
        ),
    ),
    _Scenario(
        scenario_id="checkpoint-and-side-effects",
        request=(
            "请实际查阅 LangGraph checkpoint 和 Temporal durable execution 官方资料，"
            "在这次回复中比较 checkpoint、replay 和副作用恢复边界，给出带官方 URL "
            "的中文结论。"
        ),
        required_terms=("checkpoint", "replay", "副作用"),
        official_source_groups=(
            ("langchain-ai.github.io", "docs.langchain.com"),
            ("docs.temporal.io", "temporal.io"),
        ),
    ),
)


_REVISION_SCENARIOS = (
    _RevisionScenario(
        scenario_id="withdraw-download-benchmark",
        initial_request=(
            "请先实际查阅 OpenAI 官方开发者文档和 MCP 官方 tools/resources 规范，"
            "分析结构化输出、来源追溯、下载性能基准与发布检查，形成阶段性清单供我"
            "补充验收条件后再完成。"
        ),
        continue_request=(
            "范围调整：撤回下载性能基准，保留结构化输出和来源追溯，并新增缺少可复查"
            "来源时发布必须失败。现在完成，以“结构化边界”“来源追溯”“发布失败条件”"
            "三个章节组织，并保留对应官方 URL。"
        ),
        required_terms=("结构化边界", "来源追溯", "发布失败条件"),
        withdrawn_plan_terms=("下载性能基准",),
        official_source_groups=(
            (
                "developers.openai.com",
                "platform.openai.com",
                "openai.com",
            ),
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
        ),
    ),
    _RevisionScenario(
        scenario_id="reject-ordered-delivery",
        initial_request=(
            "请先实际查阅 Temporal 和 Restate 官方文档，分析有序投递、durable execution、"
            "重试和幂等边界，形成阶段性清单供我补充现场事实后再完成。"
        ),
        continue_request=(
            "补充事实：生产 broker 不保证跨重启顺序，撤回依赖有序投递的候选。现在完成，"
            "以“业务幂等”“恢复后对账”“验收条件”三个章节组织，并保留官方 URL。"
        ),
        required_terms=("业务幂等", "恢复后对账", "验收条件"),
        withdrawn_plan_terms=("依赖有序投递",),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
    _RevisionScenario(
        scenario_id="tighten-recommendation-evidence",
        initial_request=(
            "请先实际查阅 OpenAI 官方开发者文档、Gemini CLI 官方资料和 Hermes Agent "
            "官方仓库，比较复杂任务的义务保留与进度恢复，形成阶段性清单供我补充最终"
            "验收口径后再完成。"
        ),
        continue_request=(
            "验收口径收紧：原比较范围不变，每条采用建议和不采用建议都必须给出官方 URL "
            "与可执行验证条件。现在完成，以“采用建议”“不采用边界”“验证条件”组织。"
        ),
        required_terms=("采用建议", "不采用边界", "验证条件"),
        withdrawn_plan_terms=(),
        official_source_groups=(
            (
                "developers.openai.com",
                "platform.openai.com",
                "openai.github.io",
                "openai.com",
            ),
            ("geminicli.com", "github.com/google-gemini/gemini-cli"),
            (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            ),
        ),
    ),
    _RevisionScenario(
        scenario_id="replace-state-only-recovery",
        initial_request=(
            "请先实际查阅 LangGraph persistence 和 Temporal durable execution 官方资料，"
            "比较状态快照、事件重放和副作用恢复，形成阶段性清单供我补充运行约束后再完成。"
        ),
        continue_request=(
            "运行约束补充：撤回“只恢复状态就足够”的候选，新增外部副作用必须幂等且恢复后"
            "必须对账。现在完成，以“状态恢复”“副作用边界”“恢复后对账”三个章节组织，"
            "并保留官方 URL。"
        ),
        required_terms=("状态恢复", "副作用边界", "恢复后对账"),
        withdrawn_plan_terms=("只恢复状态就足够",),
        official_source_groups=(
            ("langchain-ai.github.io", "docs.langchain.com"),
            ("docs.temporal.io", "temporal.io"),
        ),
    ),
)


_BACKGROUND_SCENARIOS = (
    _BackgroundScenario(
        scenario_id="protocol-release-comparison",
        request=(
            "请在后台持续调查 MCP 与 A2A 最近正式发布的协议变化，至少比较两项，覆盖"
            "协议机制、信任边界和迁移建议，只采用官方来源。首次请求返回后请独立推进，"
            "我稍后只查询并领取带逐项 URL 的中文报告。"
        ),
        required_terms=("协议机制", "信任边界", "迁移建议"),
        official_source_groups=(
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
            (
                "a2a-protocol.org",
                "google.github.io/a2a",
                "github.com/a2aproject",
            ),
        ),
    ),
    _BackgroundScenario(
        scenario_id="durable-execution-comparison",
        request=(
            "请在后台持续调查 Temporal 与 Restate 的 durable execution 边界，比较重试、"
            "业务幂等和恢复后对账，只采用官方来源。首次请求返回后请独立推进，我稍后"
            "只查询并领取带逐项 URL 的中文报告。"
        ),
        required_terms=("重试", "业务幂等", "恢复后对账"),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
    _BackgroundScenario(
        scenario_id="agent-plan-recovery-comparison",
        request=(
            "请在后台持续调查 Gemini CLI 与 Hermes Agent 对复杂任务计划、进度更新和恢复"
            "的正式机制，只采用官方资料。首次请求返回后请独立推进，我稍后只查询并领取"
            "带逐项 URL 的中文报告。"
        ),
        required_terms=("计划", "进度", "恢复"),
        official_source_groups=(
            ("geminicli.com", "github.com/google-gemini/gemini-cli"),
            (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            ),
        ),
    ),
    _BackgroundScenario(
        scenario_id="tool-governance-comparison",
        request=(
            "请在后台持续调查 OpenAI Agents SDK 与 Anthropic 官方工具使用机制，比较工具"
            "选择、调用前治理和完成判断，只采用官方来源。首次请求返回后请独立推进，"
            "我稍后只查询并领取带逐项 URL 的中文报告。"
        ),
        required_terms=("工具选择", "治理", "完成"),
        official_source_groups=(
            ("openai.github.io", "developers.openai.com", "openai.com"),
            ("docs.anthropic.com", "platform.claude.com"),
        ),
    ),
)


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    started = perf_counter()
    result = _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": text}],
        },
    )
    elapsed = perf_counter() - started
    trace = _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )
    return result, trace, elapsed


def _turn_messages(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    started = perf_counter()
    result = _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages": messages,
        },
    )
    elapsed = perf_counter() - started
    trace = _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )
    return result, trace, elapsed


def _source_coverage(
    answer: str,
    groups: tuple[tuple[str, ...], ...],
) -> tuple[bool, ...]:
    lowered = answer.lower()
    return tuple(any(host in lowered for host in group) for group in groups)


def _provider_source_urls(
    run_store: PostgresAgentRunStore,
    final_view: dict[str, Any],
) -> tuple[str, ...]:
    urls: set[str] = set()
    for execution_ref in final_view.get("execution_refs") or ():
        if not isinstance(execution_ref, dict):
            continue
        execution_id = str(execution_ref.get("execution_id") or "")
        if not execution_id:
            continue
        run = run_store.get(execution_id)
        if run is None or run.definition.agent_id != "gpt_researcher":
            continue
        result = run.projection.result
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("source_urls", "visited_urls"):
            values = metadata.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, str) and value.strip():
                    urls.add(value.strip())
                elif isinstance(value, dict):
                    url = value.get("url")
                    if isinstance(url, str) and url.strip():
                        urls.add(url.strip())
    return tuple(sorted(urls))


def _project_selected(result: dict[str, Any], trace: dict[str, Any]) -> bool:
    if result.get("project_reference"):
        return True
    return any(
        item.get("capability_id") == "start_durable_investigation"
        for item in trace.get("inputs", [])
        if isinstance(item, dict)
    )


def _provider_failures(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in trace.get("inputs", [])
        if isinstance(item, dict)
        and item.get("kind") == "tool_result"
        and item.get("capability_id") != "verify_interaction_draft"
        and (
            item.get("status") != "succeeded"
            or not isinstance(item.get("payload"), dict)
            or not item["payload"].get("ok", False)
        )
    ]


def _successful_execution_digests(trace: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(item["execution_request_digest"])
        for item in trace.get("inputs", [])
        if isinstance(item, dict)
        and item.get("status") == "succeeded"
        and item.get("capability_id") != "verify_interaction_draft"
        and item.get("execution_request_digest")
    )


def _active_plan_text(plan: object) -> str:
    if not isinstance(plan, dict):
        return ""
    return json.dumps(
        {
            "goal": plan.get("goal", ""),
            "steps": [
                step
                for step in plan.get("steps", [])
                if isinstance(step, dict) and step.get("status") != "superseded"
            ],
        },
        ensure_ascii=False,
    ).casefold()


def _plan_is_terminal(plan: object) -> bool:
    return isinstance(plan, dict) and bool(plan.get("steps")) and all(
        isinstance(step, dict)
        and step.get("status") in {"completed", "superseded"}
        for step in plan["steps"]
    )


def _repeated_proposal_keys(view: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    keys = [
        (str(item["logical_subgoal_id"]), int(item["subgoal_version"]))
        for item in view.get("accepted_execution_proposals", [])
        if isinstance(item, dict)
        and item.get("logical_subgoal_id")
        and item.get("subgoal_version")
    ]
    return tuple(sorted({key for key in keys if keys.count(key) > 1}))


def _environment_failed(worker_log: str, view: dict[str, Any]) -> bool:
    evidence = worker_log + json.dumps(view, ensure_ascii=False)
    return any(
        marker in evidence
        for marker in (
            "structured parse failed",
            "ModelCallDeadlineExceeded",
            "provider call exceeded",
            "NOT_ENOUGH_BALANCE",
            "HTTP 401",
            "HTTP 402",
            "HTTP 429",
            "HTTP 432",
            "Error code: 503",
            "exceeds your plan's set usage limit",
            "local_overload",
        )
    )


def test_current_interaction_research_does_not_need_a_durable_project(
    live_web_search_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    reports: list[dict[str, Any]] = []
    all_inputs: list[str] = []
    for scenario in _SCENARIOS:
        for repetition in range(1, _REPETITIONS + 1):
            all_inputs.append(scenario.request)
            user_id = (
                f"investigation-consolidation-current-{scenario.scenario_id}-"
                f"{repetition}"
            )
            result, trace, elapsed = _turn(
                live_web_search_process,
                user_id=user_id,
                conversation_id=f"{user_id}-conversation",
                text=scenario.request,
            )
            answer = str(result.get("message", {}).get("content", ""))
            normalized_answer = answer.casefold()
            term_coverage = tuple(
                term.casefold() in normalized_answer
                for term in scenario.required_terms
            )
            source_coverage = _source_coverage(
                answer,
                scenario.official_source_groups,
            )
            project_selected = _project_selected(result, trace)
            provider_failures = _provider_failures(trace)
            delivered = (
                result.get("disposition") == "answer"
                and all(term_coverage)
                and all(source_coverage)
                and not project_selected
            )
            reports.append({
                "scenario_id": scenario.scenario_id,
                "repetition": repetition,
                "delivered": delivered,
                "term_coverage": term_coverage,
                "source_coverage": source_coverage,
                "project_selected": project_selected,
                "provider_failures": provider_failures,
                "elapsed_seconds": round(elapsed, 6),
                "usage": trace.get("usage", {}),
                "result": result,
                "interaction_trace": trace,
            })

    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="investigation-consolidation-current-cohort",
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": len(_SCENARIOS),
                "repetitions": _REPETITIONS,
                "sample_count": len(reports),
                "isolated_database": True,
            }),
            config_cohort="current-conversation-with-project-capability",
            grader_version="investigation-consolidation-001-current-v2",
        ),
        report={
            "sample_count": len(reports),
            "delivered_count": sum(bool(item["delivered"]) for item in reports),
            "project_selected_count": sum(
                bool(item["project_selected"]) for item in reports
            ),
            "provider_failure_count": sum(
                bool(item["provider_failures"]) for item in reports
            ),
            "reports": reports,
        },
    )

    assert len(reports) == 20
    assert all(item["delivered"] for item in reports), json.dumps(
        [
            {
                "scenario_id": item["scenario_id"],
                "repetition": item["repetition"],
                "term_coverage": item["term_coverage"],
                "source_coverage": item["source_coverage"],
                "project_selected": item["project_selected"],
                "provider_failure_count": len(item["provider_failures"]),
            }
            for item in reports
            if not item["delivered"]
        ],
        ensure_ascii=False,
    )


def test_cross_turn_revision_recovers_without_a_durable_project(
    live_web_search_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    reports: list[dict[str, Any]] = []
    all_inputs: list[tuple[str, str]] = []
    for scenario in _REVISION_SCENARIOS:
        for repetition in range(1, _REVISION_REPETITIONS + 1):
            all_inputs.append((scenario.initial_request, scenario.continue_request))
            user_id = (
                f"investigation-consolidation-revision-{scenario.scenario_id}-"
                f"{repetition}"
            )
            conversation_id = f"{user_id}-conversation"
            first_messages = [
                {"role": "user", "content": scenario.initial_request},
            ]
            first, first_trace, first_elapsed = _turn_messages(
                live_web_search_process,
                user_id=user_id,
                conversation_id=conversation_id,
                messages=first_messages,
            )
            live_web_search_process.restart()
            second_messages = [
                *first_messages,
                {
                    "role": "assistant",
                    "content": str(first.get("message", {}).get("content", "")),
                },
                {"role": "user", "content": scenario.continue_request},
            ]
            second, second_trace, second_elapsed = _turn_messages(
                live_web_search_process,
                user_id=user_id,
                conversation_id=conversation_id,
                messages=second_messages,
            )
            answer = str(second.get("message", {}).get("content", ""))
            normalized_answer = answer.casefold()
            term_coverage = tuple(
                term.casefold() in normalized_answer
                for term in scenario.required_terms
            )
            source_coverage = _source_coverage(
                answer,
                scenario.official_source_groups,
            )
            first_project_selected = _project_selected(first, first_trace)
            second_project_selected = _project_selected(second, second_trace)
            repeated_execution_digests = sorted(
                _successful_execution_digests(first_trace)
                & _successful_execution_digests(second_trace)
            )
            active_plan_text = _active_plan_text(second.get("working_plan"))
            stale_plan_terms = tuple(
                term
                for term in scenario.withdrawn_plan_terms
                if term.casefold() in active_plan_text
            )
            provider_failures = [
                *_provider_failures(first_trace),
                *_provider_failures(second_trace),
            ]
            delivered = (
                first.get("disposition") == "plan_ready"
                and isinstance(first.get("working_plan"), dict)
                and second.get("disposition") == "answer"
                and all(term_coverage)
                and all(source_coverage)
                and _plan_is_terminal(second.get("working_plan"))
                and not stale_plan_terms
                and not repeated_execution_digests
                and not first_project_selected
                and not second_project_selected
            )
            reports.append({
                "scenario_id": scenario.scenario_id,
                "repetition": repetition,
                "delivered": delivered,
                "term_coverage": term_coverage,
                "source_coverage": source_coverage,
                "stale_plan_terms": stale_plan_terms,
                "repeated_execution_digests": repeated_execution_digests,
                "project_selected": (
                    first_project_selected or second_project_selected
                ),
                "provider_failures": provider_failures,
                "first_elapsed_seconds": round(first_elapsed, 6),
                "second_elapsed_seconds": round(second_elapsed, 6),
                "first": first,
                "first_trace": first_trace,
                "second": second,
                "second_trace": second_trace,
            })

    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_REVISION_CASE_ID,
            role=product_evidence_role(_REVISION_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="investigation-consolidation-revision-cohort",
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": len(_REVISION_SCENARIOS),
                "repetitions": _REVISION_REPETITIONS,
                "sample_count": len(reports),
                "web_restart_between_turns": True,
                "isolated_database": True,
            }),
            config_cohort="cross-turn-conversation-with-project-capability",
            grader_version="investigation-consolidation-001-revision-v1",
        ),
        report={
            "sample_count": len(reports),
            "delivered_count": sum(bool(item["delivered"]) for item in reports),
            "project_selected_count": sum(
                bool(item["project_selected"]) for item in reports
            ),
            "provider_failure_count": sum(
                bool(item["provider_failures"]) for item in reports
            ),
            "repeated_execution_count": sum(
                bool(item["repeated_execution_digests"]) for item in reports
            ),
            "reports": reports,
        },
    )

    assert len(reports) == 20
    assert all(item["delivered"] for item in reports), json.dumps(
        [
            {
                "scenario_id": item["scenario_id"],
                "repetition": item["repetition"],
                "term_coverage": item["term_coverage"],
                "source_coverage": item["source_coverage"],
                "stale_plan_terms": item["stale_plan_terms"],
                "repeated_execution_count": len(
                    item["repeated_execution_digests"]
                ),
                "project_selected": item["project_selected"],
                "provider_failure_count": len(item["provider_failures"]),
            }
            for item in reports
            if not item["delivered"]
        ],
        ensure_ascii=False,
    )


def test_background_work_advances_without_another_conversation_turn(
    live_web_search_process: LiveWebProcess,
    live_investigation_worker: tuple[Any, Path],
    product_evidence_recorder: ProductEvidenceRecorder,
    postgres_url: str,
    request: pytest.FixtureRequest,
) -> None:
    worker, worker_log_path = live_investigation_worker
    capture_resources = _resource_evidence_enabled()
    resource_started_at = perf_counter()
    resource_sampler: DockerStatsSampler | None = None
    resource_container: str | None = None
    active_run_samples: list[dict[str, Any]] = []
    run_store = PostgresAgentRunStore(postgres_url)
    configured_capacity = int(
        live_web_search_process.child_env.get(
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_CONCURRENT_RUNS",
            "4",
        )
    )
    if capture_resources:
        try:
            resource_container = discover_gpt_researcher_container()
        except (OSError, RuntimeError) as exc:
            pytest.fail(f"GPT Researcher resource evidence unavailable: {exc}")
        resource_sampler = DockerStatsSampler(resource_container)
        resource_sampler.start()
        request.addfinalizer(resource_sampler.stop)

    def sample_capacity() -> None:
        if not capture_resources:
            return
        records = run_store.list(agent_id="gpt_researcher")
        status_counts: dict[str, int] = {}
        for record in records:
            status = record.projection.status
            status_counts[status] = status_counts.get(status, 0) + 1
        active_run_samples.append({
            "elapsed_seconds": round(perf_counter() - resource_started_at, 3),
            "capacity_occupying_count": sum(
                count
                for status, count in status_counts.items()
                if status in CAPACITY_OCCUPYING_AGENT_RUN_STATUSES
            ),
            "status_counts": status_counts,
        })

    reports: list[dict[str, Any]] = []
    all_inputs: list[str] = []
    submissions: list[dict[str, Any]] = []
    cohort_log_offset = worker_log_path.stat().st_size
    for scenario in _BACKGROUND_SCENARIOS:
        for repetition in range(1, _BACKGROUND_REPETITIONS + 1):
            all_inputs.append(scenario.request)
            user_id = (
                f"investigation-consolidation-background-{scenario.scenario_id}-"
                f"{repetition}"
            )
            conversation_id = f"{user_id}-conversation"
            started, initial_trace, initial_elapsed = _turn(
                live_web_search_process,
                user_id=user_id,
                conversation_id=conversation_id,
                text=scenario.request,
            )
            project_ref = started.get("project_reference")
            project_selected = _project_selected(started, initial_trace)
            project_url: str | None = None
            report_url: str | None = None
            if isinstance(project_ref, dict) and project_ref.get("project_id"):
                query = urlencode({
                    "tenant_id": str(project_ref["tenant_id"]),
                    "user_id": str(project_ref["user_id"]),
                })
                project_url = (
                    f"{live_web_search_process.base_url}/api/investigation-projects/"
                    f"{project_ref['project_id']}?{query}"
                )
                report_url = (
                    f"{live_web_search_process.base_url}/api/"
                    f"investigation-projects/{project_ref['project_id']}/"
                    f"report?{query}"
                )
            submissions.append({
                "scenario": scenario,
                "repetition": repetition,
                "started": started,
                "initial_trace": initial_trace,
                "initial_elapsed": initial_elapsed,
                "project_selected": project_selected,
                "project_url": project_url,
                "report_url": report_url,
                "final_view": {},
                "observation_errors": [],
            })
            sample_capacity()

    # The entire fixed cohort shares one observation window.  A runaway project
    # must not turn the remaining samples into serial ten-minute waits.
    live_web_search_process.restart()
    pending = {
        index
        for index, submission in enumerate(submissions)
        if submission["project_url"] is not None
    }
    deadline = time.monotonic() + 600
    while pending and time.monotonic() < deadline and worker.poll() is None:
        terminal: set[int] = set()
        for index in pending:
            submission = submissions[index]
            try:
                final_view = _get_json(str(submission["project_url"]))
            except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
                submission["observation_errors"].append({
                    "type": type(exc).__name__,
                    "status": getattr(exc, "code", None),
                    "message": str(exc),
                })
                continue
            submission["final_view"] = final_view
            if final_view.get("state") in {
                "completed",
                "failed",
                "cancelled",
                "paused",
            }:
                terminal.add(index)
        pending.difference_update(terminal)
        sample_capacity()
        if pending:
            # Observe the cohort once per cadence. Each request borrows one
            # pooled Postgres connection, so twenty projects do not turn a
            # five-second cadence into one hundred seconds.
            time.sleep(5)

    sample_capacity()
    docker_resource_evidence = (
        resource_sampler.stop()
        if resource_sampler is not None
        else {
            "captured": False,
            "reason": f"set {_RESOURCE_EVIDENCE_ENV}=true",
        }
    )
    capacity_evidence = {
        "captured": capture_resources,
        "configured_max_concurrent_runs": configured_capacity,
        "sample_count": len(active_run_samples),
        "max_capacity_occupying_runs": max(
            (
                item["capacity_occupying_count"]
                for item in active_run_samples
            ),
            default=0,
        ),
        "samples": active_run_samples,
    }

    worker_log = worker_log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )[cohort_log_offset:]
    worker_exited = worker.poll() is not None
    for submission in submissions:
        scenario = submission["scenario"]
        final_view = submission["final_view"]
        report_response: dict[str, Any] | None = None
        if (
            final_view.get("state") == "completed"
            and final_view.get("completion_report")
            and submission["report_url"] is not None
        ):
            report_response = _get_json(str(submission["report_url"]))
        answer = str((report_response or {}).get("content", ""))
        normalized_answer = answer.casefold()
        term_coverage = tuple(
            term.casefold() in normalized_answer
            for term in scenario.required_terms
        )
        source_coverage = _source_coverage(
            answer,
            scenario.official_source_groups,
        )
        provider_source_urls = _provider_source_urls(run_store, final_view)
        provider_source_coverage = _source_coverage(
            "\n".join(provider_source_urls),
            scenario.official_source_groups,
        )
        repeated_proposal_keys = _repeated_proposal_keys(final_view)
        observation_errors = submission["observation_errors"]
        environment_failed = (
            worker_exited
            or _environment_failed("", final_view)
            or (not final_view and bool(observation_errors))
        )
        delivered = (
            submission["started"].get("disposition") == "background_started"
            and submission["project_selected"]
            and final_view.get("state") == "completed"
            and isinstance(final_view.get("completion_report"), dict)
            and all(term_coverage)
            and all(source_coverage)
            and all(provider_source_coverage)
            and not repeated_proposal_keys
            and not environment_failed
        )
        reports.append({
            "scenario_id": scenario.scenario_id,
            "repetition": submission["repetition"],
            "delivered": delivered,
            "project_selected": submission["project_selected"],
            "term_coverage": term_coverage,
            "source_coverage": source_coverage,
            "provider_source_urls": provider_source_urls,
            "provider_source_coverage": provider_source_coverage,
            "repeated_proposal_keys": repeated_proposal_keys,
            "observation_errors": observation_errors,
            "environment_failed": environment_failed,
            "initial_elapsed_seconds": round(submission["initial_elapsed"], 6),
            "started": submission["started"],
            "initial_trace": submission["initial_trace"],
            "final_view": final_view,
            "report_response": report_response,
        })

    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_BACKGROUND_CASE_ID,
            role=product_evidence_role(_BACKGROUND_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="investigation-consolidation-background-cohort",
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": len(_BACKGROUND_SCENARIOS),
                "repetitions": _BACKGROUND_REPETITIONS,
                "sample_count": len(reports),
                "no_followup_conversation_turn": True,
                "web_restart_after_creation": True,
                "isolated_database": True,
                "resource_evidence_enabled": capture_resources,
                "resource_container": resource_container,
                "configured_max_concurrent_runs": configured_capacity,
            }),
            config_cohort=canonical_evidence_digest({
                "profile": "background-project-with-independent-worker",
                "resource_sampling": capture_resources,
                "structured_model": live_web_search_process.settings.structured.model,
                "structured_base_url": str(
                    live_web_search_process.settings.structured.base_url
                ),
                "structured_output_transport": (
                    live_web_search_process.settings.structured.output_transport
                ),
                "structured_extra_body": (
                    live_web_search_process.settings.structured.extra_body
                ),
                "structured_timeout_seconds": (
                    live_web_search_process.settings.structured.timeout_seconds
                ),
                "structured_max_retries": (
                    live_web_search_process.settings.structured.max_retries
                ),
                "web_search_provider": (
                    live_web_search_process.settings.web_search.provider
                ),
                "gpt_researcher_max_search_results": int(
                    live_web_search_process.child_env.get(
                        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS",
                        "0",
                    )
                ),
                    "gpt_researcher_max_concurrent_runs": configured_capacity,
                "observation_window_seconds": 600,
                "grader": (
                    "investigation-consolidation-001-background-"
                    "v3-resource-provenance"
                ),
            }),
            grader_version=(
                "investigation-consolidation-001-background-v3-resource-provenance"
            ),
        ),
        report={
            "sample_count": len(reports),
            "delivered_count": sum(bool(item["delivered"]) for item in reports),
            "project_selected_count": sum(
                bool(item["project_selected"]) for item in reports
            ),
            "environment_failure_count": sum(
                bool(item["environment_failed"]) for item in reports
            ),
            "repeated_proposal_count": sum(
                bool(item["repeated_proposal_keys"]) for item in reports
            ),
            "worker_exited": worker_exited,
            "worker_log_tail": worker_log[-20_000:],
            "gpt_researcher_docker_resources": docker_resource_evidence,
            "gpt_researcher_capacity": capacity_evidence,
            "reports": reports,
        },
    )

    assert len(reports) == 20
    assert all(item["delivered"] for item in reports), json.dumps(
        [
            {
                "scenario_id": item["scenario_id"],
                "repetition": item["repetition"],
                "project_selected": item["project_selected"],
                "state": item["final_view"].get("state"),
                "term_coverage": item["term_coverage"],
                "source_coverage": item["source_coverage"],
                "provider_source_coverage": item[
                    "provider_source_coverage"
                ],
                "repeated_proposal_count": len(item["repeated_proposal_keys"]),
                "environment_failed": item["environment_failed"],
            }
            for item in reports
            if not item["delivered"]
        ],
        ensure_ascii=False,
    )

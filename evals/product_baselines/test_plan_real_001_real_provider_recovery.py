"""PLAN-REAL-001 live baseline for real-provider fact recovery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest

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


_CASE_ID = "PLAN-REAL-001"
_MAX_MODEL_TURNS = 7
_MAX_TOTAL_TOKENS = 128_000
_NODE_ID = (
    "evals/product_baselines/test_plan_real_001_real_provider_recovery.py::"
    "test_plan_real_001_real_provider_recovery"
)


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    initial_request: str
    continue_request: str
    required_answer_terms: tuple[str, ...]
    official_source_groups: tuple[tuple[str, ...], ...]


_SCENARIOS = (
    _Scenario(
        scenario_id="source-comparison",
        initial_request=(
            "在展示任何阶段方案前，请先实际查阅 OpenAI 官方开发者文档、"
            "https://geminicli.com/docs/cli/plan-mode/ 和 "
            "https://github.com/NousResearch/hermes-agent/blob/"
            "3c5fd918e3e2537cd74f4f88c990c5de5cbd9f63/tools/todo_tool.py，核对"
            "复杂任务中如何保留未完成义务、记录进度以及在上下文压缩后恢复。"
            "然后形成写明具体约束和官方 URL 的阶段方案供我审阅；如果没有实际"
            "取得三方资料就直接说明。等我补充最终展示要求后再完成，不要启动后台任务。"
        ),
        continue_request=(
            "证据和事实要求不变。现在完成最终结果，并按“恢复机制、完成条件、"
            "不采用边界”三部分组织，每部分保留可复查的官方 URL；不要重新查"
            "已经取得的资料。"
        ),
        required_answer_terms=("OpenAI", "Gemini", "Hermes", "不采用"),
        official_source_groups=(
            ("developers.openai.com", "platform.openai.com", "openai.github.io"),
            ("geminicli.com", "github.com/google-gemini/gemini-cli"),
            (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            ),
        ),
    ),
    _Scenario(
        scenario_id="product-constraints",
        initial_request=(
            "在展示任何阶段方案前，请先实际查阅 OpenAI 官方开发者文档，以及 "
            "https://modelcontextprotocol.io/specification/2025-06-18/server/tools "
            "和 https://modelcontextprotocol.io/specification/2025-06-18/server/resources，"
            "核对可下载引用报告涉及的结构化输出、Tool result 与 Resource content "
            "边界。然后形成写明具体约束和官方 URL 的阶段方案供我审阅；如果没有"
            "实际取得两方资料就直接说明。等我补充最终展示要求后再完成，不要修改"
            "代码，也不要启动后台任务。"
        ),
        continue_request=(
            "事实范围不变。现在完成最终结果，并给每项约束标注高、中、低风险及"
            "对应的发布失败条件，保留可复查的官方 URL；不要重新查已经取得的资料。"
        ),
        required_answer_terms=("结构化", "MCP", "风险", "失败"),
        official_source_groups=(
            ("developers.openai.com", "platform.openai.com", "openai.com"),
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
        ),
    ),
    _Scenario(
        scenario_id="incident-analysis",
        initial_request=(
            "在展示任何阶段方案前，请先实际查阅 "
            "https://docs.temporal.io/evaluate/understanding-temporal 和 "
            "https://docs.restate.dev/foundations/key-concepts，核对服务重启后重复通知"
            "涉及的 durable execution、重试、幂等与恢复边界。然后形成写明具体"
            "约束和官方 URL 的阶段方案供我审阅；如果没有实际取得两方资料就直接"
            "说明。等我补充最终展示要求后再完成，不要修改代码，也不要启动后台任务。"
        ),
        continue_request=(
            "事实范围不变。现在完成最终结果，并按执行系统、业务幂等和完成判断三个"
            "责任阶段给出结论与验收条件，每个阶段保留可复查的官方 URL；不要重新"
            "查已经取得的资料。"
        ),
        required_answer_terms=("Temporal", "Restate", "幂等", "验收"),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
)


def _turn(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {"conversation_id": conversation_id, "messages": messages},
    )


def _trace(server: LiveWebProcess, turn: dict[str, Any]) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{turn['interaction_run_ref']}"
    )


def _tool_results(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in trace.get("inputs", [])
        if item.get("kind") == "tool_result"
    ]


def _executed_web_results(trace: dict[str, Any]) -> list[dict[str, Any]]:
    executed = set(trace.get("execution_order", []))
    return [
        item
        for item in _tool_results(trace)
        if item.get("action_id") in executed
        and item.get("capability_id") == "web_search"
    ]


def _failed_tool_results(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in _tool_results(trace)
        if item.get("status") != "succeeded"
        or not isinstance(item.get("payload"), dict)
        or not item["payload"].get("ok", False)
    ]


def _official_source_coverage(
    trace: dict[str, Any],
    scenario: _Scenario,
) -> tuple[bool, ...]:
    successful = json.dumps(
        [
            item
            for item in _tool_results(trace)
            if item.get("status") == "succeeded"
        ],
        ensure_ascii=False,
    ).lower()
    return tuple(
        any(host in successful for host in group)
        for group in scenario.official_source_groups
    )


def _answer_source_coverage(
    answer: str,
    scenario: _Scenario,
) -> tuple[bool, ...]:
    lowered = answer.lower()
    return tuple(
        any(host in lowered for host in group)
        for group in scenario.official_source_groups
    )


def _plan_counts(plan: object) -> tuple[int, int]:
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return 0, 0
    completed = sum(step.get("status") == "completed" for step in plan["steps"])
    pending = sum(step.get("status") == "pending" for step in plan["steps"])
    return completed, pending


def _failure_from_http(error: HTTPError | TimeoutError) -> dict[str, Any]:
    return {
        "failure_class": (
            "provider_failure" if isinstance(error, HTTPError) else "request_timeout"
        ),
        "exception_type": type(error).__name__,
        "http_status": error.code if isinstance(error, HTTPError) else None,
    }


def _config_cohort(server: LiveWebProcess) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "structured_extra_body_digest": canonical_evidence_digest(
            settings.structured.extra_body
        ),
        "structured_contract_revision": "AgentTurnDecision:v1",
        "web_search_provider": settings.web_search.provider,
        "web_search_base_url": settings.web_search.base_url,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "budget": {
            "max_model_turns": _MAX_MODEL_TURNS,
            "max_tool_calls": settings.interaction_loop.max_tool_calls,
            "max_total_tokens": _MAX_TOTAL_TOKENS,
        },
    })


def _capture(
    recorder: ProductEvidenceRecorder,
    server: LiveWebProcess,
    *,
    scenario: _Scenario,
    repetition: int,
    report: dict[str, Any],
) -> None:
    recorder.capture(
        nodeid=_NODE_ID,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="default",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest((
                scenario.initial_request,
                scenario.continue_request,
            )),
            initial_state_digest=canonical_evidence_digest({"seeded_facts": ()}),
            config_cohort=_config_cohort(server),
            grader_version="plan-real-001-deterministic-v2",
        ),
        report={
            "case_id": _CASE_ID,
            "scenario_id": scenario.scenario_id,
            "repetition": repetition,
            **report,
        },
    )


@pytest.mark.parametrize("repetition", range(1, 6), ids=lambda value: f"run-{value}")
@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=lambda scenario: scenario.scenario_id,
)
def test_plan_real_001_real_provider_recovery(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    expected_transport = os.getenv("PERSONAL_AGENT_PLAN_REAL_EXPECTED_TRANSPORT")
    if expected_transport:
        assert live_web_process.settings.structured.output_transport == expected_transport

    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
    ] = str(_MAX_MODEL_TURNS)
    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
    ] = str(_MAX_TOTAL_TOKENS)
    live_web_process.restart()
    conversation_id = f"plan-real-001-{scenario.scenario_id}-{repetition}"
    first_messages = [{"role": "user", "content": scenario.initial_request}]
    assert all(
        internal not in scenario.initial_request
        for internal in (
            "Planner",
            "Workflow",
            "InvestigationProject",
        )
    )
    try:
        first = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=first_messages,
        )
    except (HTTPError, TimeoutError) as error:
        metrics = {"failure_stage": "evidence_turn", **_failure_from_http(error)}
        _capture(
            product_evidence_recorder,
            live_web_process,
            scenario=scenario,
            repetition=repetition,
            report={"result_metrics": metrics},
        )
        pytest.fail(str(metrics))

    first_trace = _trace(live_web_process, first)
    first_plan = first.get("working_plan")
    first_coverage = _official_source_coverage(first_trace, scenario)
    first_failed_tools = _failed_tool_results(first_trace)

    live_web_process.restart()
    second_messages = [
        *first_messages,
        {"role": "assistant", "content": str(first["message"]["content"])},
        {"role": "user", "content": scenario.continue_request},
    ]
    try:
        second = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=second_messages,
        )
    except (HTTPError, TimeoutError) as error:
        metrics = {"failure_stage": "recovery_turn", **_failure_from_http(error)}
        _capture(
            product_evidence_recorder,
            live_web_process,
            scenario=scenario,
            repetition=repetition,
            report={
                "first": first,
                "first_trace": first_trace,
                "result_metrics": metrics,
            },
        )
        pytest.fail(str(metrics))

    second_trace = _trace(live_web_process, second)
    second_plan = second.get("working_plan")
    completed, pending = _plan_counts(second_plan)
    second_web_results = _executed_web_results(second_trace)
    second_failed_tools = _failed_tool_results(second_trace)
    answer = str(second.get("message", {}).get("content", ""))
    answer_terms_present = tuple(
        term.lower() in answer.lower() for term in scenario.required_answer_terms
    )
    answer_source_coverage = _answer_source_coverage(answer, scenario)
    same_plan_recovered = (
        isinstance(first_plan, dict)
        and isinstance(second_plan, dict)
        and second_plan.get("plan_id") == first_plan.get("plan_id")
    )
    all_steps_completed = (
        isinstance(second_plan, dict)
        and completed > 0
        and pending == 0
        and completed == len(second_plan.get("steps", []))
    )
    delivered = (
        first.get("disposition") == "plan_ready"
        and all(first_coverage)
        and second.get("disposition") == "answer"
        and same_plan_recovered
        and all_steps_completed
        and all(answer_terms_present)
        and all(answer_source_coverage)
    )
    repeated_fact_consumption = delivered and bool(second_web_results)
    failed_tools = first_failed_tools + second_failed_tools
    if failed_tools:
        failure_class = "provider_failure"
    elif not all(first_coverage):
        failure_class = "insufficient_official_evidence"
    elif repeated_fact_consumption:
        failure_class = "repeated_fact_consumption"
    elif delivered:
        failure_class = "delivered"
    else:
        failure_class = "semantic_recovery_failure"
    metrics = {
        "failure_class": failure_class,
        "first_disposition": first.get("disposition"),
        "final_disposition": second.get("disposition"),
        "official_source_coverage": first_coverage,
        "answer_terms_present": answer_terms_present,
        "answer_source_coverage": answer_source_coverage,
        "same_plan_recovered": same_plan_recovered,
        "completed_step_count": completed,
        "pending_step_count": pending,
        "first_failed_tool_result_count": len(first_failed_tools),
        "second_failed_tool_result_count": len(second_failed_tools),
        "recovery_web_search_count": len(second_web_results),
        "first_usage": first_trace.get("usage"),
        "recovery_usage": second_trace.get("usage"),
    }
    _capture(
        product_evidence_recorder,
        live_web_process,
        scenario=scenario,
        repetition=repetition,
        report={
            "initial_request": scenario.initial_request,
            "continue_request": scenario.continue_request,
            "first": first,
            "first_trace": first_trace,
            "second": second,
            "second_trace": second_trace,
            "result_metrics": metrics,
        },
    )

    assert failure_class == "delivered", metrics
    assert len(second_web_results) == 0, metrics

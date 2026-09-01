"""PLAN-STAB-001 live baseline for foreground-plan stability."""

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


_MODEL_TURNS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
_TOOL_CALLS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"
_TOTAL_TOKENS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
_CASE_ID = "PLAN-STAB-001"
_NODE_ID = (
    "evals/product_baselines/test_plan_stab_001_working_plan_stability.py::"
    "test_plan_stab_001_working_plan_stability"
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
            "请只基于 OpenAI 官方开发者文档、Google Gemini CLI 官方 GitHub 仓库和 "
            "NousResearch Hermes Agent 官方 GitHub 仓库，比较它们在复杂任务中如何保持"
            "未完成义务、何时记录或更新进度、上下文压缩后如何恢复，并结合本工程给出"
            "有来源的采用与不采用建议。请直接开始，不要启动后台任务，也无需等我确认。"
        ),
        continue_request="继续完成，并确保最终建议分别说明采用与不采用的边界。",
        required_answer_terms=("OpenAI", "Gemini", "Hermes"),
        official_source_groups=(
            ("developers.openai.com", "platform.openai.com", "openai.github.io"),
            ("github.com/google-gemini/gemini-cli",),
            (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            ),
        ),
    ),
    _Scenario(
        scenario_id="product-change",
        initial_request=(
            "我们准备为知识问答增加用户可下载的引用报告。请先核对 OpenAI 官方开发者"
            "文档关于结构化输出的约束和 Model Context Protocol 官方规范关于资源与工具"
            "边界的要求，再给出用户结果定义、当前约束、最小实现边界和可验收发布检查。"
            "请直接开始分析，不要修改代码，不要启动后台任务，也无需等我确认。"
        ),
        continue_request=(
            "继续完成；发布检查里增加一项：报告缺少可复查来源时必须失败，不要扩大实现范围。"
        ),
        required_answer_terms=("用户", "来源", "发布"),
        official_source_groups=(
            ("developers.openai.com", "platform.openai.com", "openai.com"),
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
        ),
    ),
    _Scenario(
        scenario_id="incident-analysis",
        initial_request=(
            "线上长对话在服务重启后偶尔重复发送通知。请只依据 Temporal 和 Restate 官方"
            "文档核对 durable execution、重试与幂等边界，给出可复现条件、按责任阶段区分的"
            "原因、最小修复候选和回归验收标准。请直接开始，不要修改代码，不要启动后台任务，"
            "也无需等我确认。"
        ),
        continue_request=(
            "继续完成；把验收标准调整为还必须证明重启后没有重复外部副作用。"
        ),
        required_answer_terms=("重启", "幂等", "验收"),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
)


def _restart_with_budget(
    server: LiveWebProcess,
    *,
    max_model_turns: int,
    max_tool_calls: int,
    max_total_tokens: int,
) -> None:
    server.child_env[_MODEL_TURNS_ENV] = str(max_model_turns)
    server.child_env[_TOOL_CALLS_ENV] = str(max_tool_calls)
    server.child_env[_TOTAL_TOKENS_ENV] = str(max_total_tokens)
    server.restart()


def _turn(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "messages": messages,
            "interaction_mode": "auto",
        },
    )


def _trace(server: LiveWebProcess, turn: dict[str, Any]) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{turn['interaction_run_ref']}"
    )


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
        "structured_contract_revision": "ModelActionProtocol:v2",
        "web_search_provider": settings.web_search.provider,
        "web_search_base_url": settings.web_search.base_url,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "first_turn_budget": {
            "max_model_turns": 1,
            "max_tool_calls": 0,
            "max_total_tokens": 64_000,
        },
        "continuation_budget": {
            "max_model_turns": settings.interaction_loop.max_model_turns,
            "max_tool_calls": settings.interaction_loop.max_tool_calls,
            "max_total_tokens": 128_000,
        },
    })


def _failure_from_http(error: HTTPError | TimeoutError) -> dict[str, Any]:
    return {
        "failure_class": (
            "provider_failure" if isinstance(error, HTTPError) else "request_timeout"
        ),
        "exception_type": type(error).__name__,
        "http_status": error.code if isinstance(error, HTTPError) else None,
    }


def _tool_results(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in trace.get("inputs", [])
        if item.get("kind") == "tool_result"
    ]


def _failed_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        item
        for item in tool_results
        if item.get("status") != "succeeded"
        or not isinstance(item.get("payload"), dict)
        or not item["payload"].get("ok", False)
    ]


def _tool_failure_class(failed: list[dict[str, Any]]) -> str:
    provider_kinds = {"provider_failure", "rate_limit", "timeout", "transient"}
    kinds = {
        str(item.get("payload", {}).get("error_kind") or "unknown")
        for item in failed
    }
    return "provider_failure" if provider_kinds.intersection(kinds) else "execution_failure"


def _official_source_coverage(
    tool_results: list[dict[str, Any]],
    scenario: _Scenario,
) -> tuple[bool, ...]:
    successful = json.dumps(
        [item for item in tool_results if item.get("status") == "succeeded"],
        ensure_ascii=False,
    ).lower()
    return tuple(
        any(host in successful for host in group)
        for group in scenario.official_source_groups
    )


def _plan_counts(plan: object) -> tuple[int, int]:
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return 0, 0
    completed = sum(step.get("status") == "completed" for step in plan["steps"])
    pending = sum(
        step.get("status") in {"pending", "in_progress"}
        for step in plan["steps"]
    )
    return completed, pending


def _feedback_reason_codes(trace: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["reason_code"])
        for item in trace.get("inputs", [])
        if item.get("kind") == "decision_feedback" and item.get("reason_code")
    )


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
            interaction_mode="auto",
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
            grader_version="plan-stab-001-deterministic-v1",
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
def test_plan_stab_001_working_plan_stability(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    expected_transport = os.getenv("PERSONAL_AGENT_PLAN_STAB_EXPECTED_TRANSPORT")
    if expected_transport:
        assert live_web_process.settings.structured.output_transport == expected_transport

    conversation_id = f"plan-stab-001-{scenario.scenario_id}-{repetition}"
    first_messages = [{"role": "user", "content": scenario.initial_request}]
    _restart_with_budget(
        live_web_process,
        max_model_turns=1,
        max_tool_calls=0,
        max_total_tokens=64_000,
    )
    try:
        first = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=first_messages,
        )
    except (HTTPError, TimeoutError) as error:
        metrics = {
            "failure_stage": "initial_turn",
            **_failure_from_http(error),
        }
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
    if not isinstance(first_plan, dict):
        metrics = {
            "failure_class": "semantic_plan_missing",
            "failure_stage": "initial_turn",
            "first_disposition": first.get("disposition"),
            "feedback_reason_codes": _feedback_reason_codes(first_trace),
            "usage": first_trace.get("usage"),
        }
        _capture(
            product_evidence_recorder,
            live_web_process,
            scenario=scenario,
            repetition=repetition,
            report={
                "initial_request": scenario.initial_request,
                "first": first,
                "first_trace": first_trace,
                "result_metrics": metrics,
            },
        )
        pytest.fail(str(metrics))

    _restart_with_budget(
        live_web_process,
        max_model_turns=live_web_process.settings.interaction_loop.max_model_turns,
        max_tool_calls=live_web_process.settings.interaction_loop.max_tool_calls,
        max_total_tokens=128_000,
    )
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
        metrics = {
            "failure_stage": "continuation_turn",
            **_failure_from_http(error),
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
                "result_metrics": metrics,
            },
        )
        pytest.fail(str(metrics))

    second_trace = _trace(live_web_process, second)
    final_plan = second.get("working_plan")
    completed, pending = _plan_counts(final_plan)
    tool_results = _tool_results(second_trace)
    failed_tools = _failed_tool_results(tool_results)
    source_coverage = _official_source_coverage(tool_results, scenario)
    answer = str(second.get("message", {}).get("content", ""))
    answer_terms_present = tuple(
        term.lower() in answer.lower() for term in scenario.required_answer_terms
    )
    all_steps_completed = (
        isinstance(final_plan, dict)
        and completed > 0
        and pending == 0
        and completed == len(final_plan.get("steps", []))
    )
    delivered = (
        second.get("disposition") == "answer"
        and all_steps_completed
        and all(source_coverage)
        and all(answer_terms_present)
    )
    feedback_codes = _feedback_reason_codes(second_trace)
    if failed_tools:
        failure_class = _tool_failure_class(failed_tools)
    elif not all(source_coverage):
        failure_class = "insufficient_official_evidence"
    elif delivered:
        failure_class = "delivered"
    else:
        failure_class = "semantic_transition_failure"
    metrics = {
        "failure_class": failure_class,
        "first_disposition": first.get("disposition"),
        "final_disposition": second.get("disposition"),
        "official_source_coverage": source_coverage,
        "answer_terms_present": answer_terms_present,
        "completed_step_count": completed,
        "pending_step_count": pending,
        "failed_tool_result_count": len(failed_tools),
        "feedback_reason_codes": feedback_codes,
        "active_step_feedback_count": feedback_codes.count(
            "working_plan_active_step_required"
        ),
        "usage": second_trace.get("usage"),
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
    assert isinstance(final_plan, dict)
    assert final_plan["plan_id"] == first_plan["plan_id"]
    assert final_plan["revision"] > first_plan["revision"]
    execution_order = second_trace.get("execution_order", [])
    assert len(execution_order) == len(set(execution_order)), metrics

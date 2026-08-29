"""PLAN-REPLAN-001 live baseline for revising obsolete obligations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
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
from personal_agent.application.conversation.interaction_intent import (
    _DERIVATION_INSTRUCTION,
)
from personal_agent.tools.interaction_verifier import _VERIFICATION_INSTRUCTION


_CASE_ID = "PLAN-REPLAN-001"
_MAX_MODEL_TURNS = 7
_MAX_TOTAL_TOKENS = 128_000
_NODE_ID = (
    "evals/product_baselines/test_plan_replan_001_obligation_revision.py::"
    "test_plan_replan_001_obligation_revision"
)


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    initial_request: str
    continue_request: str
    required_answer_terms: tuple[str, ...]
    forbidden_answer_patterns: tuple[str, ...]
    required_plan_terms: tuple[str, ...]
    withdrawn_plan_terms: tuple[str, ...]
    official_source_groups: tuple[tuple[str, ...], ...]
    required_criteria_scope_terms: tuple[str, ...] = ()


_SCENARIOS = (
    _Scenario(
        scenario_id="new-evidence-rejects-candidate",
        initial_request=(
            "线上通知在服务重启后偶尔重复。请先实际查阅 Temporal 和 Restate 官方文档，"
            "核对有序投递、durable execution、重试和幂等边界，再形成一份阶段性分析"
            "清单供我补充现场事实；不要修改代码，也不要启动后台任务。"
        ),
        continue_request=(
            "补充现场事实：生产 broker 明确不保证跨重启的消息顺序，原先依赖有序投递"
            "的候选不再成立。请完成分析，撤回该候选，保留仍有效的重启风险分析，"
            "并以“业务幂等”“恢复后对账”“验收条件”三个章节给出最终结果；每章保留"
            "Temporal 或 Restate 官方 URL。"
        ),
        required_answer_terms=("业务幂等", "恢复后对账", "验收条件"),
        forbidden_answer_patterns=(r"(?m)^#{1,6}\s*有序投递方案\s*$",),
        required_plan_terms=("业务幂等", "恢复后对账", "验收条件"),
        withdrawn_plan_terms=("依赖有序投递",),
        official_source_groups=(
            ("docs.temporal.io", "temporal.io"),
            ("docs.restate.dev", "restate.dev"),
        ),
    ),
    _Scenario(
        scenario_id="withdraw-and-add-result",
        initial_request=(
            "我们在设计可下载的引用报告。请先实际查阅 OpenAI 官方开发者文档和 MCP "
            "官方 tools/resources 规范，分析结构化输出、来源追溯、下载性能基准与发布"
            "检查，再形成一份阶段性分析清单供我确认范围；不要修改代码，也不要启动"
            "后台任务。"
        ),
        continue_request=(
            "范围调整：撤回下载性能基准，不要在最终交付中提供该结果；保留结构化输出"
            "和来源追溯，并新增“缺少可复查来源时发布必须失败”。现在完成，以“结构化"
            "边界”“来源追溯”“发布失败条件”三个章节组织，并保留对应官方 URL。"
        ),
        required_answer_terms=("结构化边界", "来源追溯", "发布失败条件"),
        forbidden_answer_patterns=(r"(?m)^#{1,6}\s*下载性能基准\s*$",),
        required_plan_terms=("结构化", "来源追溯", "发布失败"),
        withdrawn_plan_terms=("下载性能基准",),
        official_source_groups=(
            ("developers.openai.com", "platform.openai.com", "openai.com"),
            ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
        ),
    ),
    _Scenario(
        scenario_id="tighten-acceptance-criteria",
        initial_request=(
            "请先实际查阅 OpenAI 官方开发者文档、Gemini CLI 官方资料和 Hermes Agent "
            "官方仓库，比较复杂任务中的义务保留与进度恢复，再形成一份阶段性比较清单"
            "供我补充最终验收口径；不要修改代码，也不要启动后台任务。"
        ),
        continue_request=(
            "验收口径收紧：原比较范围不变，但每条采用建议和不采用建议都必须同时给出"
            "官方 URL 与可执行验证条件。现在完成，并以“采用建议”“不采用边界”“验证"
            "条件”三个章节组织。"
        ),
        required_answer_terms=("采用建议", "不采用边界", "验证条件"),
        forbidden_answer_patterns=(),
        required_plan_terms=("采用建议", "不采用", "验证条件"),
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
        required_criteria_scope_terms=("openai", "gemini cli", "hermes"),
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
        {
            "conversation_id": conversation_id,
            "messages": messages,
        },
    )


def _trace(server: LiveWebProcess, turn: dict[str, Any]) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/{turn['interaction_run_ref']}"
    )


def _tool_results(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in trace.get("inputs", [])
        if item.get("kind") == "tool_result"
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
    traces: tuple[dict[str, Any], ...],
    scenario: _Scenario,
) -> tuple[bool, ...]:
    successful = json.dumps(
        [
            item
            for trace in traces
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


def _criteria_scope_coverage(
    trace: dict[str, Any],
    scenario: _Scenario,
) -> tuple[bool, ...]:
    criteria = json.dumps(
        trace.get("review_criteria", {}).get("criteria", []),
        ensure_ascii=False,
    ).lower()
    return tuple(
        term in criteria for term in scenario.required_criteria_scope_terms
    )


def _plan_contract(
    plan: dict[str, Any] | None,
    scenario: _Scenario,
) -> tuple[tuple[bool, ...], tuple[bool, ...], tuple[bool, ...]]:
    if not isinstance(plan, dict):
        return (
            tuple(False for _ in scenario.required_plan_terms),
            tuple(False for _ in scenario.withdrawn_plan_terms),
            tuple(False for _ in scenario.withdrawn_plan_terms),
        )
    active_plan_text = json.dumps(
        {
            "goal": plan.get("goal", ""),
            "steps": [
                {
                    "description": step.get("description", ""),
                    "status": step.get("status", ""),
                }
                for step in plan.get("steps", [])
                if isinstance(step, dict) and step.get("status") != "superseded"
            ],
        },
        ensure_ascii=False,
    ).lower()
    active_step_descriptions = [
        str(step.get("description", "")).lower()
        for step in plan.get("steps", [])
        if isinstance(step, dict) and step.get("status") != "superseded"
    ]
    superseded_step_count = sum(
        isinstance(step, dict) and step.get("status") == "superseded"
        for step in plan.get("steps", [])
    )
    return (
        tuple(
            term.lower() in active_plan_text
            for term in scenario.required_plan_terms
        ),
        tuple(
            any(
                term.lower() in description
                and not any(
                    marker in description
                    for marker in (
                        "撤回",
                        "取消",
                        "不再成立",
                        "已无效",
                        "排除",
                        "不包含",
                    )
                )
                for description in active_step_descriptions
            )
            for term in scenario.withdrawn_plan_terms
        ),
        tuple(
            superseded_step_count > 0
            for term in scenario.withdrawn_plan_terms
        ),
    )


def _plan_counts(plan: object) -> tuple[int, int, int]:
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return 0, 0, 0
    completed = sum(step.get("status") == "completed" for step in plan["steps"])
    pending = sum(step.get("status") == "pending" for step in plan["steps"])
    superseded = sum(step.get("status") == "superseded" for step in plan["steps"])
    return completed, pending, superseded


def _feedback_reason_codes(trace: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["reason_code"])
        for item in trace.get("inputs", [])
        if item.get("kind") == "decision_feedback" and item.get("reason_code")
    )


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
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "structured_contract_revision": (
            "ModelActionProtocol:v2+InteractionIntentProposal:lifecycle-v2+"
            "ConversationWorkingPlan:superseded"
        ),
        "review_instruction_digest": canonical_evidence_digest(
            _DERIVATION_INSTRUCTION
        ),
        "verifier_instruction_digest": canonical_evidence_digest(
            _VERIFICATION_INSTRUCTION
        ),
        "web_search_provider": settings.web_search.provider,
        "web_search_base_url": settings.web_search.base_url,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "turn_budget": {
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
            grader_version="plan-replan-001-deterministic-v10",
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
def test_plan_replan_001_obligation_revision(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    expected_transport = os.getenv("PERSONAL_AGENT_PLAN_REPLAN_EXPECTED_TRANSPORT")
    if expected_transport:
        assert live_web_process.settings.structured.output_transport == expected_transport

    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
    ] = str(_MAX_MODEL_TURNS)
    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
    ] = str(_MAX_TOTAL_TOKENS)
    live_web_process.restart()
    conversation_id = f"plan-replan-001-{scenario.scenario_id}-{repetition}"
    first_messages = [{"role": "user", "content": scenario.initial_request}]
    try:
        first = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=first_messages,
        )
    except (HTTPError, TimeoutError) as error:
        metrics = {"failure_stage": "initial_turn", **_failure_from_http(error)}
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
    _, first_pending, _ = _plan_counts(first_plan)
    if (
        not isinstance(first_plan, dict)
        or first.get("disposition") != "plan_ready"
        or first_pending == 0
    ):
        metrics = {
            "failure_class": "semantic_pending_plan_missing",
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
        metrics = {"failure_stage": "revision_turn", **_failure_from_http(error)}
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
    completed, pending, superseded = _plan_counts(final_plan)
    failed_tools = [
        *_failed_tool_results(first_trace),
        *_failed_tool_results(second_trace),
    ]
    failed_provider_tools = [
        item
        for item in failed_tools
        if item.get("capability_id") != "verify_interaction_draft"
    ]
    failed_verifications = [
        item
        for item in failed_tools
        if item.get("capability_id") == "verify_interaction_draft"
    ]
    source_coverage = _official_source_coverage(
        (first_trace, second_trace),
        scenario,
    )
    answer = str(second.get("message", {}).get("content", ""))
    answer_terms_present = tuple(
        term.lower() in answer.lower() for term in scenario.required_answer_terms
    )
    answer_source_coverage = _answer_source_coverage(answer, scenario)
    criteria_scope_coverage = _criteria_scope_coverage(second_trace, scenario)
    stale_patterns_present = tuple(
        bool(re.search(pattern, answer))
        for pattern in scenario.forbidden_answer_patterns
    )
    (
        plan_terms_present,
        withdrawn_active_plan_terms_present,
        withdrawn_superseded_plan_terms_present,
    ) = _plan_contract(
        final_plan,
        scenario,
    )
    same_plan_revised = (
        isinstance(final_plan, dict)
        and final_plan.get("plan_id") == first_plan.get("plan_id")
        and isinstance(final_plan.get("revision"), int)
        and final_plan["revision"] > first_plan.get("revision", -1)
    )
    final_steps = final_plan.get("steps", []) if isinstance(final_plan, dict) else []
    all_steps_terminal = (
        bool(final_steps)
        and pending == 0
        and completed + superseded == len(final_steps)
    )
    feedback_codes = _feedback_reason_codes(second_trace)
    repeated_plan_feedback_count = feedback_codes.count("working_plan_no_change")
    delivered = (
        second.get("disposition") == "answer"
        and same_plan_revised
        and all_steps_terminal
        and all(source_coverage)
        and all(answer_source_coverage)
        and all(answer_terms_present)
        and not any(stale_patterns_present)
        and not any(withdrawn_active_plan_terms_present)
        and all(withdrawn_superseded_plan_terms_present)
    )
    if failed_provider_tools:
        failure_class = "provider_failure"
    elif not all(source_coverage):
        failure_class = "insufficient_official_evidence"
    elif delivered:
        failure_class = "delivered"
    elif repeated_plan_feedback_count >= 3:
        failure_class = "repeated_plan_revision_loop"
    else:
        failure_class = "stale_obligation_failure"
    metrics = {
        "failure_class": failure_class,
        "first_disposition": first.get("disposition"),
        "final_disposition": second.get("disposition"),
        "same_plan_revised": same_plan_revised,
        "official_source_coverage": source_coverage,
        "answer_source_coverage": answer_source_coverage,
        "criteria_scope_coverage": criteria_scope_coverage,
        "answer_terms_present": answer_terms_present,
        "stale_patterns_present": stale_patterns_present,
        "plan_terms_present": plan_terms_present,
        "withdrawn_active_plan_terms_present": withdrawn_active_plan_terms_present,
        "withdrawn_superseded_plan_terms_present": (
            withdrawn_superseded_plan_terms_present
        ),
        "completed_step_count": completed,
        "pending_step_count": pending,
        "superseded_step_count": superseded,
        "failed_tool_result_count": len(failed_tools),
        "failed_provider_tool_result_count": len(failed_provider_tools),
        "failed_verification_count": len(failed_verifications),
        "feedback_reason_codes": feedback_codes,
        "repeated_plan_feedback_count": repeated_plan_feedback_count,
        "initial_usage": first_trace.get("usage"),
        "revision_usage": second_trace.get("usage"),
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
    execution_order = second_trace.get("execution_order", [])
    assert len(execution_order) == len(set(execution_order)), metrics

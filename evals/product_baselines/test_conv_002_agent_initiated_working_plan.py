"""CONV-002 paired product E2E for agent-initiated foreground planning."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlparse

from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


_MODEL_TURNS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
_TOOL_CALLS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"
_TOTAL_TOKENS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"


def _turn(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "messages": messages,
            "interaction_mode": "auto",
        },
    )


def _assert_expected_transport(server: LiveWebProcess) -> None:
    expected = os.environ.get("PERSONAL_AGENT_CONV_002_EXPECTED_TRANSPORT")
    if expected:
        actual = server.settings.structured.output_transport
        assert actual == expected, (
            "CONV-002 comparison profile transport mismatch: "
            f"expected {expected!r}, got {actual!r}"
        )


def _restart_with_budget(
    server: LiveWebProcess,
    *,
    max_model_turns: int,
    max_tool_calls: int,
    max_total_tokens: int = 64000,
) -> None:
    server.child_env[_MODEL_TURNS_ENV] = str(max_model_turns)
    server.child_env[_TOOL_CALLS_ENV] = str(max_tool_calls)
    server.child_env[_TOTAL_TOKENS_ENV] = str(max_total_tokens)
    server.restart()


def _conv_002_config_cohort(settings, *, first_turn_budget: dict[str, int], continuation_budget: dict[str, int]) -> str:
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
        "first_turn_budget": first_turn_budget,
        "continuation_budget": continuation_budget,
    })


def _request_failure_fields(error: HTTPError | TimeoutError) -> dict[str, object]:
    is_provider_failure = isinstance(error, HTTPError)
    return {
        "failure_class": (
            "provider_failure" if is_provider_failure else "request_timeout"
        ),
        "failure_reason": (
            "http_error" if is_provider_failure else "client_deadline_exceeded"
        ),
        "exception_type": type(error).__name__,
        "http_status": error.code if is_provider_failure else None,
    }


def _tool_failure_fields(
    failed_results: list[dict[str, object]],
) -> dict[str, object]:
    error_kind_counts: dict[str, int] = {}
    for result in failed_results:
        payload = result.get("payload")
        error_kind = (
            str(payload.get("error_kind") or "unknown")
            if isinstance(payload, dict)
            else "unknown"
        )
        error_kind_counts[error_kind] = error_kind_counts.get(error_kind, 0) + 1
    provider_error_kinds = {"provider_failure", "rate_limit", "timeout", "transient"}
    failure_class = (
        "provider_failure"
        if provider_error_kinds.intersection(error_kind_counts)
        else "execution_failure"
    )
    return {
        "failure_class": failure_class,
        "failed_tool_result_count": len(failed_results),
        "failed_tool_error_kind_counts": error_kind_counts,
    }


def _capture_request_failure(
    recorder: ProductEvidenceRecorder,
    server: LiveWebProcess,
    *,
    conversation_id: str,
    initial_request: str,
    continue_request: str,
    sample_id: str,
    stage: str,
    error: HTTPError | TimeoutError,
) -> None:
    settings = server.settings
    recorder.capture(
        nodeid=(
            "evals/product_baselines/"
            "test_conv_002_agent_initiated_working_plan.py::"
            "test_conv_002_agent_initiates_and_recovers_foreground_coordination"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-002",
            role=product_evidence_role("CONV-002"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, continue_request)
            ),
            initial_state_digest=canonical_evidence_digest({"seeded_facts": ()}),
            config_cohort=_conv_002_config_cohort(
                settings,
                first_turn_budget={"max_model_turns": 1, "max_tool_calls": 0},
                continuation_budget={
                    "max_model_turns": settings.interaction_loop.max_model_turns,
                    "max_tool_calls": settings.interaction_loop.max_tool_calls,
                    "max_total_tokens": 128000,
                },
            ),
            grader_version="conv-002-result-classification-v2",
        ),
        report={
            "case_id": "CONV-002",
            "conversation_id": conversation_id,
            "sample_id": sample_id,
            "failure_stage": stage,
            "response_detail": "redacted",
            **_request_failure_fields(error),
        },
    )


def test_conv_002_agent_initiates_and_recovers_foreground_coordination(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    conversation_id = "conv-002-agent-initiated-coordination"
    initial_request = (
        "请只基于 OpenAI 官方开发者文档、Google Gemini CLI 官方 GitHub 仓库和 NousResearch "
        "Hermes Agent 官方 GitHub 仓库，比较它们在复杂任务中如何保持未完成义务、何时主动"
        "记录或更新进度、上下文压缩后如何恢复，并结合本工程给出有来源的采用与不采用建议。"
        "请直接开始，不要启动后台任务，也无需等我确认。"
    )
    assert all(
        internal not in initial_request
        for internal in (
            "Plan",
            "plan",
            "计划",
            "步骤",
            "Planner",
            "Workflow",
        )
    )
    continue_request = "继续完成。"
    sample_id = os.environ.get("PERSONAL_AGENT_CONV_002_SAMPLE_ID", "unlabeled")
    _assert_expected_transport(live_web_process)

    _restart_with_budget(
        live_web_process,
        max_model_turns=1,
        max_tool_calls=0,
    )
    first_messages = [{"role": "user", "content": initial_request}]
    try:
        first = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=first_messages,
        )
    except (HTTPError, TimeoutError) as exc:
        _capture_request_failure(
            product_evidence_recorder,
            live_web_process,
            conversation_id=conversation_id,
            initial_request=initial_request,
            continue_request=continue_request,
            sample_id=sample_id,
            stage="initial_turn",
            error=exc,
        )
        raise
    first_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{first['interaction_run_ref']}"
    )

    _restart_with_budget(
        live_web_process,
        max_model_turns=live_web_process.settings.interaction_loop.max_model_turns,
        max_tool_calls=live_web_process.settings.interaction_loop.max_tool_calls,
        max_total_tokens=128000,
    )
    report: dict[str, object] = {
        "case_id": "CONV-002",
        "conversation_id": conversation_id,
        "initial_request": initial_request,
        "first": first,
        "first_trace": first_trace,
    }
    first_plan = first.get("working_plan")
    if first_plan is None:
        report["result_metrics"] = {
            "sample_id": sample_id,
            "failure_class": "semantic_completion_failure",
            "failure_stage": "initial_turn",
            "reason": "missing_working_plan",
        }
    settings = live_web_process.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/"
            "test_conv_002_agent_initiated_working_plan.py::"
            "test_conv_002_agent_initiates_and_recovers_foreground_coordination"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-002",
            role=product_evidence_role("CONV-002"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, continue_request)
            ),
            initial_state_digest=canonical_evidence_digest({
                "seeded_facts": (),
            }),
            config_cohort=_conv_002_config_cohort(
                settings,
                first_turn_budget={
                    "max_model_turns": 1,
                    "max_tool_calls": 0,
                },
                continuation_budget={
                    "max_model_turns": settings.interaction_loop.max_model_turns,
                    "max_tool_calls": settings.interaction_loop.max_tool_calls,
                    "max_total_tokens": 128000,
                },
            ),
            grader_version="conv-002-result-classification-v2",
        ),
        report=report,
    )
    assert first_plan is not None, (
        "首轮无法执行外部检索时没有保留用户可观察的剩余义务"
    )
    assert first["disposition"] == "limitation"
    assert any(step["status"] == "pending" for step in first_plan["steps"])
    assert first_trace["execution_order"] == []

    second_messages = [
        *first_messages,
        {"role": "assistant", "content": str(first["message"]["content"])},
        {"role": "user", "content": continue_request},
    ]
    try:
        second = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=second_messages,
        )
    except (HTTPError, TimeoutError) as exc:
        report["result_metrics"] = {
            "sample_id": sample_id,
            "failure_stage": "continuation_turn",
            **_request_failure_fields(exc),
        }
        raise
    second_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{second['interaction_run_ref']}"
    )
    report.update({
        "continue_request": continue_request,
        "second": second,
        "second_trace": second_trace,
    })

    final_plan = second.get("working_plan")
    final_answer = str(second["message"]["content"])
    tool_results = [
        item
        for item in second_trace["inputs"]
        if item["kind"] == "tool_result"
    ]
    failed_tool_results = [
        item
        for item in tool_results
        if item.get("status") != "succeeded"
        or not item.get("payload", {}).get("ok", False)
    ]
    successful_evidence = json.dumps(
        [item for item in tool_results if item not in failed_tool_results],
        ensure_ascii=False,
    ).lower()
    source_coverage = {
        "openai": any(
            host in successful_evidence
            for host in ("developers.openai.com", "openai.github.io")
        ),
        "gemini": "github.com/google-gemini/gemini-cli" in successful_evidence,
        "hermes": any(
            host in successful_evidence
            for host in (
                "github.com/nousresearch/hermes-agent",
                "hermes-agent.nousresearch.com",
            )
        ),
    }
    completed_step_count = (
        sum(step["status"] == "completed" for step in final_plan["steps"])
        if isinstance(final_plan, dict)
        else 0
    )
    pending_step_count = (
        sum(step["status"] == "pending" for step in final_plan["steps"])
        if isinstance(final_plan, dict)
        else 0
    )
    semantic_delivery_complete = (
        second["disposition"] == "answer"
        and isinstance(final_plan, dict)
        and pending_step_count == 0
        and completed_step_count == len(final_plan["steps"])
        and all(name in final_answer for name in ("OpenAI", "Gemini", "Hermes"))
        and any(term in final_answer for term in ("来源", "官方", "仓库", "文档"))
    )
    tool_failure_fields: dict[str, object] = {
        "failed_tool_result_count": 0,
        "failed_tool_error_kind_counts": {},
    }
    if failed_tool_results:
        tool_failure_fields = _tool_failure_fields(failed_tool_results)
        failure_class = str(tool_failure_fields["failure_class"])
    elif not all(source_coverage.values()):
        failure_class = "insufficient_official_evidence"
    elif not semantic_delivery_complete:
        failure_class = "semantic_completion_failure"
    else:
        failure_class = "delivered"
    result_metrics = {
        "sample_id": sample_id,
        "failure_class": failure_class,
        "official_source_coverage": source_coverage,
        **{
            key: value
            for key, value in tool_failure_fields.items()
            if key != "failure_class"
        },
        "completed_step_count": completed_step_count,
        "pending_step_count": pending_step_count,
        "semantic_delivery_complete": semantic_delivery_complete,
        "usage": second_trace["usage"],
    }
    report["result_metrics"] = result_metrics

    assert not failed_tool_results, result_metrics
    assert all(source_coverage.values()), result_metrics
    assert semantic_delivery_complete, result_metrics
    assert isinstance(final_plan, dict)
    assert final_plan["plan_id"] == first_plan["plan_id"]
    assert final_plan["revision"] > first_plan["revision"]
    assert len(second_trace["execution_order"]) == len(
        set(second_trace["execution_order"])
    )

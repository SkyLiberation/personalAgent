"""Formal target E2E for the unsupported background-continuation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

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


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "BACKGROUND-CONTINUATION-LIMITATION-001"
_REPETITIONS = 5
_GRADER_VERSION = "background-continuation-limitation-001-v2-per-sample"


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    request: str


_SCENARIOS = (
    _Scenario(
        scenario_id="protocol-release-comparison",
        request=(
            "请在后台持续调查 MCP 与 A2A 最近正式发布的协议变化，至少比较两项，覆盖"
            "协议机制、信任边界和迁移建议，只采用官方来源。首次请求返回后请独立推进，"
            "我稍后只查询并领取带逐项 URL 的中文报告。"
        ),
    ),
    _Scenario(
        scenario_id="durable-execution-comparison",
        request=(
            "请在后台持续调查 Temporal 与 Restate 的 durable execution 边界，比较重试、"
            "业务幂等和恢复后对账，只采用官方来源。首次请求返回后请独立推进，我稍后"
            "只查询并领取带逐项 URL 的中文报告。"
        ),
    ),
    _Scenario(
        scenario_id="agent-plan-recovery-comparison",
        request=(
            "请在后台持续调查 Gemini CLI 与 Hermes Agent 对复杂任务计划、进度更新和恢复"
            "的正式机制，只采用官方资料。首次请求返回后请独立推进，我稍后只查询并领取"
            "带逐项 URL 的中文报告。"
        ),
    ),
    _Scenario(
        scenario_id="tool-governance-comparison",
        request=(
            "请在后台持续调查 OpenAI Agents SDK 与 Anthropic 官方工具使用机制，比较工具"
            "选择、调用前治理和完成判断，只采用官方来源。首次请求返回后请独立推进，"
            "我稍后只查询并领取带逐项 URL 的中文报告。"
        ),
    ),
)

_SAMPLES = tuple(
    (scenario, repetition)
    for scenario in _SCENARIOS
    for repetition in range(1, _REPETITIONS + 1)
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


@pytest.mark.parametrize(
    ("scenario", "repetition"),
    _SAMPLES,
    ids=[
        f"{scenario.scenario_id}-run-{repetition}"
        for scenario, repetition in _SAMPLES
    ],
)
def test_background_continuation_fails_closed_without_starting_work(
    request,
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
):
    settings = live_web_search_process.settings
    user_id = "background-continuation-limitation-cohort"
    conversation_id = f"background-limitation-{scenario.scenario_id}-{repetition}"
    initial_state = {
        "scenario_id": scenario.scenario_id,
        "repetition": repetition,
        "isolated_conversation": conversation_id,
        "initial_background_work": 0,
    }
    product_evidence_recorder.enroll(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(scenario.request),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=canonical_evidence_digest({
                "model": settings.structured.model,
                "base_url": str(settings.structured.base_url),
                "output_transport": settings.structured.output_transport,
                "extra_body": settings.structured.extra_body,
                "timeout_seconds": settings.structured.timeout_seconds,
                "max_retries": settings.structured.max_retries,
                "intent_contract": "interaction_intent:background_continuation:v1",
                "dataset_revision": "background-continuation-4x5-v2-per-sample",
            }),
            grader_version=_GRADER_VERSION,
        ),
    )

    try:
        result, trace, elapsed = _turn(
            live_web_search_process,
            user_id=user_id,
            conversation_id=conversation_id,
            text=scenario.request,
        )
        error = None
    except (HTTPError, URLError, TimeoutError) as exc:
        result = {}
        trace = {}
        elapsed = 0.0
        error = {
            "type": type(exc).__name__,
            "status": getattr(exc, "code", None),
            "message": str(exc),
        }

    usage = trace.get("usage") or {}
    feedback = [
        item
        for item in trace.get("inputs") or ()
        if isinstance(item, dict)
        and item.get("reason_code") == "capability_missing"
    ]
    message = result.get("message")
    message_content = (
        str(message.get("content", ""))
        if isinstance(message, dict)
        else str(message or "")
    )
    limited = result.get("disposition") == "limitation"
    capability_missing = bool(feedback)
    no_execution = (
        int(usage.get("tool_calls") or 0) == 0
        and int(usage.get("agent_calls") or 0) == 0
        and int(usage.get("model_turns") or 0) == 0
    )
    passed = bool(
        error is None
        and limited
        and capability_missing
        and no_execution
        and "没有启动后台工作" in message_content
    )
    report = {
        "case_id": _CASE_ID,
        "scenario_id": scenario.scenario_id,
        "repetition": repetition,
        "natural_user_text": scenario.request,
        "initial_state": initial_state,
        "result": result,
        "interaction_trace": trace,
        "result_metrics": {
            "passed": passed,
            "not_limited": not limited,
            "capability_missing_absent": not capability_missing,
            "execution_started": not no_execution,
            "provider_failure": error is not None,
            "elapsed_seconds": round(elapsed, 6),
            "model_calls": usage.get("model_calls"),
            "total_tokens": usage.get("total_tokens"),
        },
        "error": error,
    }
    product_evidence_recorder.capture_report(report)

    assert passed, report["result_metrics"]

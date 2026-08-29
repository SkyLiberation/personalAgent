"""CONVERSATION-RESEARCH-DELIVERY-001 current production-path baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os
import re
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse

import pytest

from evals.e2e_quality.failure_diagnostics import diagnose_earliest_failure
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

_CASE_ID = "CONVERSATION-RESEARCH-DELIVERY-001"
_DATASET_REVISION = "conversation-research-delivery-20-v2-per-sample"
_GRADER_VERSION = "conversation-research-delivery-user-outcome-v3-concepts"
_REPETITIONS = 4
_CONCEPT_SEGMENT_SPLIT = re.compile(r"[\r\n。！？；]+")


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    request: str
    required_concepts: tuple[tuple[str, ...], ...]
    official_source_groups: tuple[tuple[str, ...], ...]


_SCENARIOS = (
    _Scenario(
        scenario_id="tool-protocol-boundary",
        request=(
            "请实际查阅 OpenAI 官方工具文档和 MCP 官方 tools 规范，在这次回复中比较"
            "工具选择、权限边界和结果契约，给出带官方 URL 的中文结论。"
        ),
        required_concepts=(("工具", "选择"), ("权限", "边界"), ("结果", "契约")),
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
        required_concepts=(("重试",), ("幂等",), ("恢复",)),
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
        required_concepts=(("计划",), ("进度",), ("恢复",)),
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
        required_concepts=(("工具", "选择"), ("调用",), ("完成",)),
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
        required_concepts=(("checkpoint",), ("replay",), ("副作用",)),
        official_source_groups=(
            ("langchain-ai.github.io", "docs.langchain.com"),
            ("docs.temporal.io", "temporal.io"),
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
) -> tuple[dict[str, Any], dict[str, Any], float, dict[str, Any] | None]:
    started = perf_counter()
    try:
        result = _post_json(
            f"{server.base_url}/api/conversation/turn",
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "messages": [{"role": "user", "content": text}],
                "interaction_mode": "auto",
            },
        )
        trace = _get_json(
            f"{server.base_url}/api/conversation/runs/"
            f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
        )
        error = None
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        result = {}
        trace = {}
        error = {
            "type": type(exc).__name__,
            "status": getattr(exc, "code", None),
            "message": str(exc),
        }
    return result, trace, perf_counter() - started, error


def _source_coverage(
    answer: str,
    groups: tuple[tuple[str, ...], ...],
) -> tuple[bool, ...]:
    normalized = answer.casefold()
    return tuple(any(host in normalized for host in group) for group in groups)


def _concept_coverage(
    answer: str,
    required_concepts: tuple[tuple[str, ...], ...],
) -> tuple[bool, ...]:
    """Require every atom of one concept in the same sentence or heading."""

    segments = tuple(
        segment.casefold().strip()
        for segment in _CONCEPT_SEGMENT_SPLIT.split(answer)
        if segment.strip()
    )
    return tuple(
        any(
            all(atom.casefold() in segment for atom in concept)
            for segment in segments
        )
        for concept in required_concepts
    )


def _feedback_counts(trace: dict[str, Any]) -> dict[str, int]:
    counts = Counter(
        str(item["reason_code"])
        for item in trace.get("inputs", ())
        if isinstance(item, dict)
        and item.get("kind") == "decision_feedback"
        and item.get("reason_code")
    )
    return dict(sorted(counts.items()))


def _execution_counts(trace: dict[str, Any]) -> dict[str, int]:
    inputs = [item for item in trace.get("inputs", ()) if isinstance(item, dict)]
    return {
        "tool_succeeded": sum(
            item.get("kind") == "tool_result" and item.get("status") == "succeeded"
            for item in inputs
        ),
        "tool_failed": sum(
            item.get("kind") == "tool_result" and item.get("status") != "succeeded"
            for item in inputs
        ),
        "agent_succeeded": sum(
            item.get("kind") == "agent_artifact"
            and item.get("status") == "succeeded"
            for item in inputs
        ),
        "agent_failed": sum(
            item.get("kind") == "agent_artifact"
            and item.get("status") != "succeeded"
            for item in inputs
        ),
    }


def _config_cohort(server: LiveWebProcess) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "structured_extra_body": settings.structured.extra_body,
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "max_model_turns": settings.interaction_loop.max_model_turns,
        "max_tool_calls": settings.interaction_loop.max_tool_calls,
        "max_agent_calls": settings.interaction_loop.max_agent_calls,
        "max_total_tokens": settings.interaction_loop.max_total_tokens,
        "web_search_provider": settings.web_search.provider,
        "web_search_provider_host": urlparse(
            settings.web_search.base_url or ""
        ).hostname,
        "a2a_enabled": settings.gpt_researcher_a2a.enabled,
        "a2a_provider_host": urlparse(
            settings.gpt_researcher_a2a.endpoint
        ).hostname,
        "a2a_timeout_seconds": settings.gpt_researcher_a2a.timeout_seconds,
        "a2a_max_search_results": settings.gpt_researcher_a2a.max_search_results,
        "formal_entrypoint": "POST /api/conversation/turn",
        "interaction_mode": "auto",
        "request_timeout_seconds": float(
            os.getenv("PERSONAL_AGENT_E2E_REQUEST_TIMEOUT_SECONDS", "300")
        ),
        "persistence": "production-postgres-composition",
        "dataset_revision": _DATASET_REVISION,
    })


@pytest.mark.parametrize(
    ("scenario", "repetition"),
    _SAMPLES,
    ids=[
        f"{scenario.scenario_id}-run-{repetition}"
        for scenario, repetition in _SAMPLES
    ],
)
def test_conversation_research_delivery_001(
    request: pytest.FixtureRequest,
    live_web_search_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    user_id = "conversation-research-delivery-cohort"
    conversation_id = f"conversation-research-{scenario.scenario_id}-{repetition}"
    initial_state = {
        "isolated_user": True,
        "isolated_conversation": conversation_id,
        "scenario_id": scenario.scenario_id,
        "repetition": repetition,
        "initial_conversation_count": 0,
        "restart_server_after_entry_error": True,
        "dataset_revision": _DATASET_REVISION,
    }
    product_evidence_recorder.enroll(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(scenario.request),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(live_web_search_process),
            grader_version=_GRADER_VERSION,
        ),
    )

    result, trace, elapsed, entry_error = _turn(
        live_web_search_process,
        user_id=user_id,
        conversation_id=conversation_id,
        text=scenario.request,
    )
    if entry_error is not None:
        live_web_search_process.restart()
    answer = str(result.get("message", {}).get("content", ""))
    concept_coverage = _concept_coverage(answer, scenario.required_concepts)
    source_coverage = _source_coverage(
        answer,
        scenario.official_source_groups,
    )
    usage = trace.get("usage") or {}
    delivered = (
        result.get("disposition") == "answer"
        and all(concept_coverage)
        and all(source_coverage)
    )
    report = {
        "case_id": _CASE_ID,
        "scenario_id": scenario.scenario_id,
        "repetition": repetition,
        "natural_user_text": scenario.request,
        "initial_state": initial_state,
        "entry_error": entry_error,
        "disposition": result.get("disposition"),
        "concept_coverage": concept_coverage,
        "source_coverage": source_coverage,
        "feedback_counts": _feedback_counts(trace),
        "execution_counts": _execution_counts(trace),
        "elapsed_seconds": round(elapsed, 6),
        "usage": usage,
        "result": result,
        "interaction_trace": trace,
        "delivered": delivered,
    }
    failure_diagnostic = diagnose_earliest_failure(
        delivered=delivered,
        entry_error=entry_error,
        interaction_trace=trace,
        required_source_groups=scenario.official_source_groups,
    )
    report["earliest_failure"] = failure_diagnostic.model_dump(mode="json")
    report["result_metrics"] = {
        "delivered": delivered,
        "entry_error": entry_error is not None,
        "tool_arguments_rejected": (
            report["feedback_counts"].get("invalid_arguments", 0) > 0
        ),
        "elapsed_seconds": report["elapsed_seconds"],
        "model_turns": usage.get("model_turns"),
        "usage_incomplete": not isinstance(usage.get("total_tokens"), int),
        "total_tokens": usage.get("total_tokens") or 0,
    }
    product_evidence_recorder.capture_report(report)

    assert delivered, report["result_metrics"]

"""MULTI-AGENT-VALUE-001 paired real-provider product experiment."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from time import perf_counter
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlparse

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _require_live_dependencies,
    _yield_started_server,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_CASE_PREFIX = "MULTI-AGENT-VALUE-001"
_DATASET_REVISION = "multi-agent-value-001-3x5-v1"
_GRADER_VERSION = "multi-agent-value-001-deterministic-v1"
_URL_PATTERN = re.compile(r"https?://[^\s)\]}>，。；;]+")


@dataclass(frozen=True, slots=True)
class _Scenario:
    category: str
    request: str
    required_term_groups: tuple[tuple[str, ...], ...]
    official_domains: tuple[str, ...]

    def case_id(self, repetition: int) -> str:
        return f"{_CASE_PREFIX}-{self.category.upper()}-{repetition:02d}"


_SCENARIOS = (
    _Scenario(
        category="protocol",
        request=(
            "请研究 Agent2Agent（A2A）协议，并基于官方协议资料说明协议目标、"
            "Task/Message/Artifact 交互机制、认证授权等信任边界和适用限制。"
            "给出结构化中文结论，并为关键判断附可直接访问的来源 URL。"
        ),
        required_term_groups=(
            ("目标", "互操作"),
            ("Task", "任务"),
            ("Message", "消息"),
            ("Artifact", "产物"),
            ("信任", "安全", "认证", "授权"),
            ("限制", "边界", "局限"),
        ),
        official_domains=("a2a-protocol.org", "github.com"),
    ),
    _Scenario(
        category="protocol_boundary",
        request=(
            "请依据 MCP 与 A2A 的官方资料比较两者的责任边界，说明工具或资源访问、"
            "智能体协作、身份与授权、任务生命周期及失败处理的差异。"
            "最后给出何时选择两者或组合使用的中文建议，并附来源 URL。"
        ),
        required_term_groups=(
            ("MCP",),
            ("A2A",),
            ("工具", "资源", "数据"),
            ("智能体", "代理"),
            ("认证", "授权", "安全", "身份"),
            ("建议", "选择", "适用", "组合"),
        ),
        official_domains=("modelcontextprotocol.io", "a2a-protocol.org"),
    ),
    _Scenario(
        category="durable_runtime",
        request=(
            "请基于 LangGraph、Temporal 与 Restate 的官方资料，为需要长时间运行、"
            "失败恢复和外部副作用的 Agent 调查任务比较 checkpoint、replay、重试、"
            "幂等与补偿边界。给出结构化中文选型建议和来源 URL。"
        ),
        required_term_groups=(
            ("LangGraph",),
            ("Temporal",),
            ("Restate",),
            ("checkpoint", "检查点", "恢复", "replay", "重放"),
            ("幂等", "补偿", "重试"),
            ("建议", "选型", "选择"),
        ),
        official_domains=(
            "docs.langchain.com",
            "docs.temporal.io",
            "docs.restate.dev",
        ),
    ),
)


@pytest.fixture(scope="module")
def multi_agent_value_web_process(
    server_temp_dir,
) -> LiveWebProcess:
    role = _role()
    settings = _require_live_dependencies()
    server = _new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": (
                "true" if role == "target" else "false"
            ),
        },
    )
    yield from _yield_started_server(server)


def _role() -> Literal["baseline", "target"]:
    value = os.getenv(
        "PERSONAL_AGENT_MULTI_AGENT_VALUE_001_EVIDENCE_ROLE",
        "target",
    )
    if value not in {"baseline", "target"}:
        raise ValueError(
            "PERSONAL_AGENT_MULTI_AGENT_VALUE_001_EVIDENCE_ROLE must be "
            "'baseline' or 'target'"
        )
    return cast(Literal["baseline", "target"], value)


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    text: str,
) -> dict[str, Any]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "messages": [{"role": "user", "content": text}],
            "interaction_mode": "auto",
        },
    )


def _trace(
    server: LiveWebProcess,
    *,
    user_id: str,
    turn: dict[str, Any],
) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{turn['interaction_run_ref']}?"
        + urlencode({"user_id": user_id})
    )


def _grade(
    scenario: _Scenario,
    *,
    marker: str,
    result: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    answer = str(result.get("message", {}).get("content", ""))
    lowered = answer.lower()
    term_results = [
        any(term.lower() in lowered for term in alternatives)
        for alternatives in scenario.required_term_groups
    ]
    urls = sorted(set(_URL_PATTERN.findall(answer)))
    domains = sorted({
        urlparse(url).hostname or ""
        for url in urls
        if urlparse(url).hostname
    })
    official_hits = sorted({
        official
        for official in scenario.official_domains
        if any(domain == official or domain.endswith(f".{official}") for domain in domains)
    })
    agent_artifacts = [
        item
        for item in trace.get("inputs", [])
        if isinstance(item, dict) and item.get("kind") == "agent_artifact"
    ]
    succeeded_artifacts = [
        item
        for item in agent_artifacts
        if item.get("status") == "succeeded"
        and item.get("payload", {}).get("status") in {"completed", "completed_degraded"}
    ]
    delivered = (
        result.get("disposition") == "answer"
        and marker in answer
        and all(term_results)
        and len(urls) >= 2
        and bool(official_hits)
    )
    score_components = {
        "answer": result.get("disposition") == "answer",
        "marker": marker in answer,
        "required_terms": sum(term_results),
        "required_terms_total": len(term_results),
        "url_count_capped": min(len(urls), 3),
        "official_domain_count_capped": min(len(official_hits), 2),
    }
    score = (
        int(score_components["answer"])
        + int(score_components["marker"])
        + int(score_components["required_terms"])
        + int(score_components["url_count_capped"])
        + int(score_components["official_domain_count_capped"])
    )
    score_max = 2 + len(term_results) + 3 + min(len(scenario.official_domains), 2)
    return {
        "delivered": delivered,
        "score": score,
        "score_max": score_max,
        "term_results": term_results,
        "urls": urls,
        "official_domain_hits": official_hits,
        "agent_artifact_count": len(agent_artifacts),
        "succeeded_agent_artifact_count": len(succeeded_artifacts),
        "delegation_consumed": bool(succeeded_artifacts),
    }


def _config_cohort(server: LiveWebProcess, *, role: str) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "max_model_turns": settings.interaction_loop.max_model_turns,
        "max_tool_calls": settings.interaction_loop.max_tool_calls,
        "max_agent_calls": settings.interaction_loop.max_agent_calls,
        "max_total_tokens": settings.interaction_loop.max_total_tokens,
        "a2a_enabled": role == "target",
        "a2a_timeout_seconds": settings.gpt_researcher_a2a.timeout_seconds,
        "formal_entrypoint": "POST /api/conversation/turn",
        "interaction_mode": "auto",
        "persistence": "production-postgres-composition",
        "dataset_revision": _DATASET_REVISION,
    })


@pytest.mark.parametrize("repetition", range(1, 6), ids=lambda value: f"run-{value}")
@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=lambda scenario: scenario.category,
)
def test_multi_agent_value_001_paired_user_outcome(
    multi_agent_value_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    live_web_process = multi_agent_value_web_process
    role = _role()
    expected_enabled = role == "target"
    actual_enabled = live_web_process.child_env.get(
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED", "false"
    ).lower() == "true"
    assert actual_enabled is expected_enabled

    marker = f"MAV-{scenario.category.upper()}-{repetition:02d}-Q7X9"
    request_text = (
        f"{scenario.request} 在最终结论末尾保留公开验收标记 {marker}。"
    )
    user_id = f"multi-agent-value-{scenario.category}-{repetition:02d}"
    initial_state = {
        "isolated_user": True,
        "dataset_revision": _DATASET_REVISION,
    }
    started = perf_counter()
    result = _turn(
        live_web_process,
        user_id=user_id,
        conversation_id=f"multi-agent-value-{scenario.category}-{repetition:02d}",
        text=request_text,
    )
    duration = perf_counter() - started
    trace = _trace(
        live_web_process,
        user_id=user_id,
        turn=result,
    )
    grade = _grade(
        scenario,
        marker=marker,
        result=result,
        trace=trace,
    )
    report = {
        "case_id": scenario.case_id(repetition),
        "comparison_role": role,
        "category": scenario.category,
        "repetition": repetition,
        "natural_user_text": request_text,
        "initial_state": initial_state,
        "result": result,
        "interaction_trace": trace,
        "result_metrics": {
            **grade,
            "failure_class": (
                "delivered" if grade["delivered"] else "required_user_result_missing"
            ),
            "end_to_end_seconds": round(duration, 6),
            "first_user_visible_seconds": round(duration, 6),
            "first_visible_equals_response_completion": True,
            "usage": trace.get("usage"),
        },
    }
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_multi_agent_value_001.py::"
            "test_multi_agent_value_001_paired_user_outcome"
        ),
        identity=ProductEvidenceIdentity(
            case_id=scenario.case_id(repetition),
            role=role,
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(request_text),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(live_web_process, role=role),
            grader_version=_GRADER_VERSION,
        ),
        report=report,
    )
    assert grade["delivered"], report["result_metrics"]

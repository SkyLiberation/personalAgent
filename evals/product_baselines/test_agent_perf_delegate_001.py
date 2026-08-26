"""AGENT-PERF-001 real delegated-agent performance cohort."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
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

_CASE_ID = "AGENT-PERF-001-DELEGATE"
_GRADER_VERSION = "agent-perf-001-delegate-user-outcome-v3"
_DATASET_REVISION = "agent-perf-001-delegate-20-v2"


@dataclass(frozen=True, slots=True)
class _Topic:
    subject: str
    preferred_sources: str
    authoritative_domains: tuple[str, ...]
    required_terms: tuple[str, ...]


_TOPICS = (
    _Topic(
        subject="A2A Agent Card 的能力发现与安全边界",
        preferred_sources="A2A 协议官网、Google 官方发布或官方 GitHub 仓库",
        authoritative_domains=(
            "a2a-protocol.org",
            "developers.googleblog.com",
            "github.com",
        ),
        required_terms=("Agent Card", "安全"),
    ),
    _Topic(
        subject="MCP 工具发现与授权责任边界",
        preferred_sources="MCP 官方规范网站或官方 GitHub 仓库",
        authoritative_domains=("modelcontextprotocol.io", "github.com"),
        required_terms=("MCP", "授权"),
    ),
    _Topic(
        subject="Temporal durable execution 的重试与幂等边界",
        preferred_sources="Temporal 官方文档",
        authoritative_domains=("docs.temporal.io", "temporal.io"),
        required_terms=("Temporal", "幂等"),
    ),
    _Topic(
        subject="Restate durable execution 的 journal 与恢复边界",
        preferred_sources="Restate 官方文档或官方 GitHub 仓库",
        authoritative_domains=("docs.restate.dev", "restate.dev", "github.com"),
        required_terms=("Restate", "恢复"),
    ),
)


@pytest.fixture(scope="module")
def delegated_web_process(server_temp_dir) -> LiveWebProcess:
    settings = _require_live_dependencies()
    server = _new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "true",
        },
    )
    yield from _yield_started_server(server)


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


def _config_cohort(server: LiveWebProcess) -> str:
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
        "a2a_provider": "gpt_researcher",
        "a2a_timeout_seconds": settings.gpt_researcher_a2a.timeout_seconds,
        "a2a_max_search_results": settings.gpt_researcher_a2a.max_search_results,
        "formal_entrypoint": "POST /api/conversation/turn",
        "interaction_mode": "auto",
        "persistence": "production-postgres-composition",
        "dataset_revision": _DATASET_REVISION,
        "streaming": False,
    })


@pytest.mark.parametrize("repetition", range(1, 21), ids=lambda value: f"run-{value}")
def test_agent_perf_001_delegated_user_outcome(
    delegated_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    repetition: int,
) -> None:
    live_web_process = delegated_web_process
    assert live_web_process.child_env.get(
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED", "false"
    ).lower() == "true"
    topic = _TOPICS[(repetition - 1) % len(_TOPICS)]
    marker = f"PERF-DELEGATE-{repetition:02d}-7Q9X"
    request_text = (
        "请委托一个独立的外部研究助手查阅权威来源，再由你核验并给出简洁中文结论。"
        f"主题是“{topic.subject}”；优先依据{topic.preferred_sources}，至少附一个对应的"
        "可直接访问来源 URL，并在结论末尾保留"
        f"公开验收标记 {marker}。"
    )
    user_id = f"agent-perf-delegate-{repetition:02d}"
    initial_state = {
        "isolated_user": True,
        "dataset_revision": _DATASET_REVISION,
    }
    started = perf_counter()
    result = _turn(
        live_web_process,
        user_id=user_id,
        conversation_id=f"agent-perf-delegate-{repetition:02d}",
        text=request_text,
    )
    duration = perf_counter() - started
    trace = _trace(
        live_web_process,
        user_id=user_id,
        turn=result,
    )
    answer = str(result.get("message", {}).get("content", ""))
    agent_artifacts = [
        item
        for item in trace.get("inputs", [])
        if isinstance(item, dict)
        and item.get("kind") == "agent_artifact"
        and item.get("status") == "succeeded"
        and item.get("payload", {}).get("status") in {"completed", "completed_degraded"}
    ]
    artifact_lengths = [
        int(artifact.get("content_length") or 0)
        for item in agent_artifacts
        for artifact in item.get("payload", {}).get("artifacts", [])
        if isinstance(artifact, dict)
    ]
    authoritative_domain_hits = [
        domain for domain in topic.authoritative_domains if domain in answer
    ]
    delivered = (
        result.get("disposition") == "answer"
        and marker in answer
        and all(term.lower() in answer.lower() for term in topic.required_terms)
        and bool(authoritative_domain_hits)
        and bool(agent_artifacts)
        and max(artifact_lengths, default=0) > 200
    )
    if delivered:
        failure_class = "delivered"
    elif not agent_artifacts:
        failure_class = "delegated_result_missing"
    elif not authoritative_domain_hits:
        failure_class = "authoritative_source_missing"
    else:
        failure_class = "final_result_contract_missing"
    report = {
        "case_id": _CASE_ID,
        "task_family": "delegate",
        "repetition": repetition,
        "natural_user_text": request_text,
        "initial_state": initial_state,
        "result": result,
        "interaction_trace": trace,
        "result_metrics": {
            "delivered": delivered,
            "failure_class": failure_class,
            "end_to_end_seconds": round(duration, 6),
            "first_user_visible_seconds": round(duration, 6),
            "first_visible_equals_response_completion": True,
            "streaming_available": False,
            "usage": trace.get("usage"),
            "agent_artifact_count": len(agent_artifacts),
            "artifact_lengths": artifact_lengths,
            "authoritative_domain_hits": authoritative_domain_hits,
            "required_provider": "gpt_researcher",
        },
    }
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_agent_perf_delegate_001.py::"
            "test_agent_perf_001_delegated_user_outcome"
        ),
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role="baseline",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(request_text),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(live_web_process),
            grader_version=_GRADER_VERSION,
        ),
        report=report,
    )
    assert delivered, report["result_metrics"]

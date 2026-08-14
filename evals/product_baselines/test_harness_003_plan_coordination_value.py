"""HARNESS-003 baseline: a working plan must preserve usable committed work."""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

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
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = pytest.mark.integration

_MODEL_TURNS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
_TOOL_CALLS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"
_TOTAL_TOKENS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
_FIRST_TURN_TOOL_BUDGET = 4


@pytest.fixture(scope="module")
def harness_003_values() -> dict[str, str]:
    seed = os.environ.get(
        "PERSONAL_AGENT_HARNESS_003_EVIDENCE_SEED",
        uuid4().hex,
    )
    return {
        "seed": seed,
        "old_threshold": f"old-{seed[:12]}",
        "new_threshold": f"new-{seed[-12:]}",
        **{
            name: f"{name.lower()}-{seed}-{index}"
            for index, name in enumerate(("ALPHA", "BETA", "GAMMA"), start=1)
        },
    }


@pytest.fixture(scope="module")
def live_harness_003_web_process(
    server_temp_dir: Path,
    harness_003_values: dict[str, str],
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    fixture = (
        Path(__file__).parents[1]
        / "e2e_quality"
        / "fixtures"
        / "frozen_document_mcp.py"
    )
    mcp_config = {
        "enabled": True,
        "servers": [{
            "server_id": "frozen-documents",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(fixture)],
            "tools": [{
                "remote_name": "read_document",
                "name": "frozen_documents.read",
                "description": (
                    "Read the complete exact text of frozen comparison document "
                    "ALPHA, BETA, or GAMMA by document_id."
                ),
                "resource_locator_arg": "document_id",
                "semantic_domains": ["frozen_documents"],
                "resource_types": ["document"],
                "operations": ["read"],
                "trust_level": "trusted",
                "credential_mode": "none",
                "data_egress_class": "none",
                "attestation_status": "pinned",
                "freshness_profile": "static",
                "output_contract": "exact frozen document text",
                "evidence_contract": "provider output bound to document_id",
                "failure_semantics": "typed failure without substitute content",
                "exposure": "public_agent",
                "side_effects": ["none"],
                "permission_scope": "frozen_documents:read",
            }],
        }],
    }
    overrides = {
        "PERSONAL_AGENT_MCP_SERVERS": json.dumps(mcp_config),
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
        "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        _MODEL_TURNS_ENV: str(settings.interaction_loop.max_model_turns),
        _TOOL_CALLS_ENV: str(_FIRST_TURN_TOOL_BUDGET),
        _TOTAL_TOKENS_ENV: "64000",
        **{
            f"CTX_E2E_FACT_{name}": harness_003_values[name]
            for name in ("ALPHA", "BETA", "GAMMA")
        },
    }
    yield from _yield_started_server(
        _new_live_web_process(
            server_temp_dir,
            settings,
            child_env_overrides=overrides,
        )
    )


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


def _trace(server: LiveWebProcess, result: dict[str, object]) -> dict[str, object]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}"
    )


def _source_reads(trace: dict[str, object]) -> tuple[str, ...]:
    executed_action_ids = set(trace["execution_order"])
    reads: list[str] = []
    for item in trace["inputs"]:
        if (
            item.get("kind") != "tool_result"
            or item.get("capability_id") != "frozen_documents.read"
            or item.get("status") != "succeeded"
            or item.get("action_id") not in executed_action_ids
        ):
            continue
        payload = json.dumps(item.get("payload"), ensure_ascii=False)
        document = next(
            (
                name
                for name in ("ALPHA", "BETA", "GAMMA")
                if f"Frozen document {name}" in payload
            ),
            None,
        )
        if document is not None:
            reads.append(document)
    return tuple(reads)


def test_harness_003_preserves_partial_results_across_steering_boundary(
    live_harness_003_web_process: LiveWebProcess,
    harness_003_values: dict[str, str],
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    server = live_harness_003_web_process
    conversation_id = f"harness-003-{harness_003_values['seed'][:12]}"
    old_threshold = harness_003_values["old_threshold"]
    new_threshold = harness_003_values["new_threshold"]
    initial_request = (
        "ALPHA、BETA、GAMMA 是三个按次计费的档案源，每份最多访问一次。"
        "如果一次返回内容太长，可以继续查看已经取得的副本，但不要再次访问原始档案。"
        "请逐字找出每份档案中 CTX-EVIDENCE 行的口令，列出资料编号与对应口令，"
        f"并在最终结果中注明当前阈值 {old_threshold}。"
        "直接开始，无需等我确认，也不要启动后台任务。"
    )
    assert all(
        internal not in initial_request
        for internal in (
            "Plan",
            "plan",
            "计划",
            "步骤",
            "Tool",
            "Planner",
            "Workflow",
            "InvestigationProject",
        )
    )
    first_messages = [{"role": "user", "content": initial_request}]
    first = _turn(
        server,
        conversation_id=conversation_id,
        messages=first_messages,
    )
    first_trace = _trace(server, first)

    server.child_env[_MODEL_TURNS_ENV] = str(
        server.settings.interaction_loop.max_model_turns
    )
    server.child_env[_TOOL_CALLS_ENV] = str(
        server.settings.interaction_loop.max_tool_calls
    )
    server.child_env[_TOTAL_TOKENS_ENV] = "128000"
    server.restart()

    steering_request = (
        f"继续完成。阈值改为 {new_threshold}，{old_threshold} 已作废；"
        "最终只使用新阈值，其他交付要求不变。"
    )
    second_messages = [
        *first_messages,
        {"role": "assistant", "content": str(first["message"]["content"])},
        {"role": "user", "content": steering_request},
    ]
    second = _turn(
        server,
        conversation_id=conversation_id,
        messages=second_messages,
    )
    second_trace = _trace(server, second)

    simple_request = "请用一句话解释什么是幂等。"
    simple = _turn(
        server,
        conversation_id=f"harness-003-simple-{harness_003_values['seed'][:12]}",
        messages=[{"role": "user", "content": simple_request}],
    )
    simple_trace = _trace(server, simple)

    first_reads = _source_reads(first_trace)
    second_reads = _source_reads(second_trace)
    all_reads = first_reads + second_reads
    answer = str(second["message"]["content"])
    report = {
        "case_id": "HARNESS-003",
        "conversation_id": conversation_id,
        "initial_request": initial_request,
        "steering_request": steering_request,
        "scenario_values": harness_003_values,
        "first": first,
        "first_trace": first_trace,
        "second": second,
        "second_trace": second_trace,
        "simple_counterfactual": {
            "request": simple_request,
            "result": simple,
            "trace": simple_trace,
        },
        "source_reads": {
            "first": first_reads,
            "second": second_reads,
            "combined": all_reads,
        },
    }
    settings = server.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/"
            "test_harness_003_plan_coordination_value.py::"
            "test_harness_003_preserves_partial_results_across_steering_boundary"
        ),
        identity=ProductEvidenceIdentity(
            case_id="HARNESS-003",
            role=product_evidence_role("HARNESS-003"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, steering_request, simple_request)
            ),
            initial_state_digest=canonical_evidence_digest({
                name: harness_003_values[name]
                for name in ("ALPHA", "BETA", "GAMMA")
            }),
            config_cohort=canonical_evidence_digest({
                "structured_model": settings.structured.model,
                "interaction_policy_revision": (
                    settings.interaction_loop.policy_revision
                ),
                "first_turn_budget": {
                    "max_model_turns": settings.interaction_loop.max_model_turns,
                    "max_tool_calls": _FIRST_TURN_TOOL_BUDGET,
                    "max_total_tokens": 64000,
                },
                "continuation_budget": {
                    "max_model_turns": settings.interaction_loop.max_model_turns,
                    "max_tool_calls": settings.interaction_loop.max_tool_calls,
                    "max_total_tokens": 128000,
                },
            }),
            grader_version="harness-003-result-contract-v2",
        ),
        report=report,
    )

    assert first["disposition"] == "limitation", (
        "首轮没有在真实非零调用预算边界停下，场景未形成部分完成反事实"
    )
    assert first_reads, "首轮没有产生任何可复用的正式执行结果"
    assert second["disposition"] == "answer"
    assert all(
        harness_003_values[name] in answer
        for name in ("ALPHA", "BETA", "GAMMA")
    ), "跨轮继续后遗漏了已经取得或仍需取得的用户结果"
    assert f"当前阈值：{new_threshold}" in answer
    assert f"当前阈值：{old_threshold}" not in answer, (
        "最终结果仍把用户已经撤回的旧阈值作为当前值"
    )
    assert all(all_reads.count(name) == 1 for name in ("ALPHA", "BETA", "GAMMA")), (
        "跨轮继续重复访问了按次计费的原始档案"
    )
    assert simple["disposition"] == "answer"
    assert simple.get("working_plan") is None
    assert simple_trace.get("working_plan") is None
